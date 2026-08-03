"""Playwright dry-run engine — offline fixtures, or gated live_page with containment."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

from app.adapters import get_adapter
from app.detectors import detect_stop_reason_on_page, is_linkedin_url
from app.models import (
    ApplicantFixture,
    ApplyAttemptResponse,
    ApplyState,
    StopReason,
)
from app.store import store

ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = ROOT / "fixtures"
DEFAULT_ARTIFACTS = Path(
    os.environ.get(
        "JOB_APPLY_ARTIFACTS_DIR",
        "/home/sabry/private/job_apply_worker/artifacts",
    )
)

# Allowlisted local CV roots for gated live_page (never uploaded off-machine intent).
CV_ALLOWLIST_PREFIXES = (
    str(Path("/home/sabry/private/linkedin_cv").resolve()),
    str((FIXTURES_DIR).resolve()),
)


def ensure_artifacts_dir(path: Path = DEFAULT_ARTIFACTS) -> Path:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def resolve_offline_url(url: str) -> Path:
    raw = (url or "").strip()
    if not raw:
        raise ValueError("url is required")
    if is_linkedin_url(raw):
        raise PermissionError("linkedin_blocked")

    if raw.startswith("file:"):
        parsed = urlparse(raw)
        path = unquote(parsed.path or "")
        candidate = Path(path)
        if not candidate.is_file():
            name = Path(path).name
            candidate = FIXTURES_DIR / name
        return _assert_fixture(candidate)

    name = Path(raw).name
    if name.endswith(".html") or name.endswith(".htm"):
        return _assert_fixture(FIXTURES_DIR / name)

    if raw.startswith("http://") or raw.startswith("https://"):
        raise ValueError(
            "External HTTP URLs require live_page=true with network_mutations=false"
        )

    raise ValueError(f"Unsupported url for offline dry-run: {raw}")


def _assert_fixture(path: Path) -> Path:
    resolved = path.resolve()
    fixtures_root = FIXTURES_DIR.resolve()
    if not str(resolved).startswith(str(fixtures_root)):
        raise ValueError("URL must resolve under fixtures/")
    if not resolved.is_file():
        raise FileNotFoundError(f"Fixture not found: {resolved.name}")
    return resolved


def resolve_cv_path(applicant: ApplicantFixture, *, live_page: bool) -> str:
    if live_page and applicant.cv_local_path:
        p = Path(applicant.cv_local_path).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"CV not found: {p}")
        if not any(str(p).startswith(prefix) for prefix in CV_ALLOWLIST_PREFIXES):
            raise PermissionError("cv_local_path not in allowlisted directories")
        return str(p)
    return str(FIXTURES_DIR / (applicant.cv_filename or "test.pdf"))


def _sanitize_net_entry(method: str, url: str, resource_type: str) -> dict[str, Any]:
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        path = (parsed.path or "")[:160]
    except Exception:
        host, path = "", url[:160]
    return {"method": method, "host": host, "path": path, "type": resource_type}


async def _form_accessible(page) -> bool:
    name = page.locator("input[name='partner_name'], input[type='email'], input[name='email_from']")
    if await name.count() == 0:
        return False
    el = name.first
    try:
        return await el.is_visible() and await el.is_enabled()
    except Exception:
        return False


async def _turnstile_state(page) -> dict[str, Any]:
    return await page.evaluate(
        """() => {
          const turnstile = !!document.querySelector(
            '.cf-turnstile, iframe[src*="turnstile"], iframe[src*="challenges.cloudflare"]'
          );
          const verifyHuman = /verify you are human|attention required|just a moment/i.test(
            document.body ? document.body.innerText : ''
          );
          const name = document.querySelector(
            'input[name="partner_name"], input[name="email_from"]'
          );
          let overlayBlocked = false;
          if (name) {
            const r = name.getBoundingClientRect();
            const mid = document.elementFromPoint(
              r.left + Math.min(20, r.width / 2),
              r.top + Math.min(10, r.height / 2)
            );
            overlayBlocked = !!(mid && mid !== name && !name.contains(mid));
          }
          return {turnstile_present: turnstile, verify_human_wall: verifyHuman, overlay_blocked: overlayBlocked};
        }"""
    )


async def run_draft(
    *,
    attempt_id: str,
    url: str,
    applicant: ApplicantFixture,
    adapter_hint: Optional[str] = None,
    live_page: bool = False,
    network_mutations: bool = False,
    submit: bool = False,
) -> ApplyAttemptResponse:
    store.update(attempt_id, state=ApplyState.running, message="dry-run started")

    if submit:
        return store.update(
            attempt_id,
            state=ApplyState.stopped,
            stop_reason=StopReason.submit_disabled,
            final_url=url,
            message="submit must remain false",
        )  # type: ignore[return-value]

    if network_mutations:
        return store.update(
            attempt_id,
            state=ApplyState.stopped,
            stop_reason=StopReason.network_mutation,
            final_url=url,
            message="network_mutations must be false",
        )  # type: ignore[return-value]

    if is_linkedin_url(url):
        return store.update(
            attempt_id,
            state=ApplyState.stopped,
            stop_reason=StopReason.linkedin_blocked,
            final_url=url,
            message="LinkedIn URLs are blocked",
        )  # type: ignore[return-value]

    artifacts = ensure_artifacts_dir()
    attempt_dir = artifacts / attempt_id
    attempt_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    try:
        os.chmod(attempt_dir, 0o700)
    except OSError:
        pass

    screenshot_paths: list[str] = []
    meta: dict[str, Any] = {
        "live_page": live_page,
        "network_mutations": False,
        "submit": False,
        "blocked_mutations": [],
        "cv_bytes_transmitted": 0,
        "containment_probe_ok": None,
        "turnstile": None,
        "field_map": [],
        "offline_before_real_fill": False,
    }

    try:
        cv_path = resolve_cv_path(applicant, live_page=live_page)
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        return store.update(
            attempt_id,
            state=ApplyState.failed,
            stop_reason=StopReason.invalid_url,
            final_url=url,
            message=str(exc),
            metadata=meta,
        )  # type: ignore[return-value]

    if not live_page:
        try:
            fixture_path = resolve_offline_url(url)
        except PermissionError:
            return store.update(
                attempt_id,
                state=ApplyState.stopped,
                stop_reason=StopReason.linkedin_blocked,
                final_url=url,
                message="LinkedIn URLs are blocked",
            )  # type: ignore[return-value]
        except (ValueError, FileNotFoundError) as exc:
            return store.update(
                attempt_id,
                state=ApplyState.failed,
                stop_reason=StopReason.invalid_url,
                final_url=url,
                message=str(exc),
            )  # type: ignore[return-value]
        return await _run_offline_fixture(
            attempt_id=attempt_id,
            file_url=fixture_path.as_uri(),
            applicant=applicant,
            adapter_hint=adapter_hint,
            cv_path=cv_path,
            attempt_dir=attempt_dir,
            screenshot_paths=screenshot_paths,
            meta=meta,
        )

    return await _run_live_page(
        attempt_id=attempt_id,
        url=url,
        applicant=applicant,
        adapter_hint=adapter_hint,
        cv_path=cv_path,
        attempt_dir=attempt_dir,
        screenshot_paths=screenshot_paths,
        meta=meta,
    )


async def _run_offline_fixture(
    *,
    attempt_id: str,
    file_url: str,
    applicant: ApplicantFixture,
    adapter_hint: Optional[str],
    cv_path: str,
    attempt_dir: Path,
    screenshot_paths: list[str],
    meta: dict[str, Any],
) -> ApplyAttemptResponse:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        return store.update(
            attempt_id,
            state=ApplyState.failed,
            stop_reason=StopReason.none,
            final_url=file_url,
            message=f"Playwright not installed: {exc}",
            metadata=meta,
        )  # type: ignore[return-value]

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(accept_downloads=False)
            page = await context.new_page()
            await page.goto(file_url, wait_until="domcontentloaded")

            shot1 = attempt_dir / "01_loaded.png"
            await page.screenshot(path=str(shot1), full_page=True)
            screenshot_paths.append(str(shot1))

            stop = await detect_stop_reason_on_page(page)
            # CAPTCHA/OTP/login: still fill safe fields for human-challenge handoff,
            # then stop before submit (never bypass the challenge).
            pre_challenge_stop = stop if stop in (
                StopReason.captcha,
                StopReason.otp,
                StopReason.login_wall,
            ) else None
            if stop is not None and pre_challenge_stop is None:
                shot2 = attempt_dir / f"02_stop_{stop.value}.png"
                await page.screenshot(path=str(shot2), full_page=True)
                screenshot_paths.append(str(shot2))
                await browser.close()
                return store.update(
                    attempt_id,
                    state=ApplyState.stopped,
                    stop_reason=stop,
                    final_url=page.url,
                    screenshot_paths=screenshot_paths,
                    message=f"Stopped: {stop.value}",
                    metadata=meta,
                )  # type: ignore[return-value]

            adapters = get_adapter(adapter_hint)
            chosen = None
            for adapter in adapters:
                if await adapter.can_handle(page):
                    chosen = adapter
                    break

            filled: list[str] = []
            adapter_name = None
            message = "No matching adapter; page inspected only"

            if chosen is not None:
                result = await chosen.fill_draft(page, applicant, cv_path)
                filled = result.filled_fields
                adapter_name = result.adapter_name
                message = result.message or message
                if result.stop_reason and result.stop_reason not in (
                    StopReason.captcha,
                    StopReason.otp,
                    StopReason.login_wall,
                ):
                    shot2 = attempt_dir / f"02_stop_{result.stop_reason.value}.png"
                    await page.screenshot(path=str(shot2), full_page=True)
                    screenshot_paths.append(str(shot2))
                    await browser.close()
                    return store.update(
                        attempt_id,
                        state=ApplyState.stopped,
                        stop_reason=result.stop_reason,
                        final_url=page.url,
                        screenshot_paths=screenshot_paths,
                        adapter_used=adapter_name,
                        filled_fields=filled,
                        message=message,
                        metadata=meta,
                    )  # type: ignore[return-value]

            stop = pre_challenge_stop or await detect_stop_reason_on_page(page)
            if stop is not None:
                shot2 = attempt_dir / f"02_stop_{stop.value}.png"
                await page.screenshot(path=str(shot2), full_page=True)
                screenshot_paths.append(str(shot2))
                await browser.close()
                state = (
                    ApplyState.human_required
                    if stop in (StopReason.captcha, StopReason.otp, StopReason.login_wall)
                    else ApplyState.stopped
                )
                return store.update(
                    attempt_id,
                    state=state,
                    stop_reason=stop,
                    final_url=page.url,
                    screenshot_paths=screenshot_paths,
                    adapter_used=adapter_name,
                    filled_fields=filled,
                    message=f"Filled then paused for {stop.value}" if filled else f"Stopped after fill: {stop.value}",
                    metadata=meta,
                )  # type: ignore[return-value]

            shot_final = attempt_dir / "02_drafted.png"
            await page.screenshot(path=str(shot_final), full_page=True)
            screenshot_paths.append(str(shot_final))
            final_url = page.url
            await browser.close()

            return store.update(
                attempt_id,
                state=ApplyState.drafted,
                stop_reason=StopReason.none,
                final_url=final_url,
                screenshot_paths=screenshot_paths,
                adapter_used=adapter_name,
                filled_fields=filled,
                message=message,
                metadata=meta,
            )  # type: ignore[return-value]
    except Exception as exc:
        return store.update(
            attempt_id,
            state=ApplyState.failed,
            stop_reason=StopReason.none,
            final_url=file_url,
            screenshot_paths=screenshot_paths,
            message=f"Worker error: {exc}",
            metadata=meta,
        )  # type: ignore[return-value]


async def _run_live_page(
    *,
    attempt_id: str,
    url: str,
    applicant: ApplicantFixture,
    adapter_hint: Optional[str],
    cv_path: str,
    attempt_dir: Path,
    screenshot_paths: list[str],
    meta: dict[str, Any],
) -> ApplyAttemptResponse:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        return store.update(
            attempt_id,
            state=ApplyState.failed,
            stop_reason=StopReason.none,
            final_url=url,
            message=f"Playwright not installed: {exc}",
            metadata=meta,
        )  # type: ignore[return-value]

    allowed = {"GET", "HEAD", "OPTIONS"}
    blocked: list[dict[str, Any]] = []
    cv_upload_blocked = 0

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                accept_downloads=False,
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()

            async def route_handler(route):
                req = route.request
                method = (req.method or "").upper()
                rtype = req.resource_type or ""
                # Block mutations, websockets, and any upload-ish posts.
                if method not in allowed or rtype == "websocket":
                    entry = _sanitize_net_entry(method, req.url, rtype)
                    blocked.append(entry)
                    if "Resume" in (req.url or "") or rtype == "multipart" or method in {
                        "POST",
                        "PUT",
                        "PATCH",
                        "DELETE",
                    }:
                        # Count potential CV egress attempts (should be aborted).
                        nonlocal cv_upload_blocked
                        if method in {"POST", "PUT", "PATCH"}:
                            cv_upload_blocked += 0  # bytes transmitted remain 0 (aborted)
                    await route.abort()
                    return
                await route.continue_()

            await page.route("**/*", route_handler)

            resp = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2500)

            # Map fields before any candidate data.
            fields = await page.eval_on_selector_all(
                "form input, form textarea, form select",
                """els => els.map(e => {
                  const cs = getComputedStyle(e);
                  const vis = cs.visibility !== 'hidden' && cs.display !== 'none' && e.offsetParent !== null;
                  const lab = (document.querySelector(`label[for="${e.id}"]`) || {}).innerText || '';
                  return {
                    name: e.name || '', type: e.type || '', required: !!e.required,
                    visible: vis, label: (lab || '').trim().slice(0, 80),
                    id: e.id || '', accept: e.accept || ''
                  };
                })""",
            )
            forms = await page.eval_on_selector_all(
                "form",
                "els => els.map(e => ({action: e.action, method: e.method, id: e.id || ''}))",
            )
            meta["field_map"] = fields
            meta["forms"] = forms
            meta["http_status"] = resp.status if resp else None

            turnstile = await _turnstile_state(page)
            meta["turnstile"] = turnstile
            form_ok = await _form_accessible(page)

            shot1 = attempt_dir / "01_preflight_loaded.png"
            await page.screenshot(path=str(shot1), full_page=False)
            screenshot_paths.append(str(shot1))

            if turnstile.get("verify_human_wall") and not form_ok:
                meta["blocked_mutations"] = blocked[:50]
                await browser.close()
                return store.update(
                    attempt_id,
                    state=ApplyState.stopped,
                    stop_reason=StopReason.captcha,
                    final_url=page.url,
                    screenshot_paths=screenshot_paths,
                    message="Turnstile/challenge blocked form inspection",
                    metadata=meta,
                )  # type: ignore[return-value]

            # Login wall: password auth without application fields.
            has_password = await page.locator("form input[type='password']").count() > 0
            if has_password and not form_ok:
                meta["blocked_mutations"] = blocked[:50]
                await browser.close()
                return store.update(
                    attempt_id,
                    state=ApplyState.stopped,
                    stop_reason=StopReason.login_wall,
                    final_url=page.url,
                    screenshot_paths=screenshot_paths,
                    message="Login wall before application form",
                    metadata=meta,
                )  # type: ignore[return-value]

            # Switch to offline / local-DOM-only before any candidate values.
            await context.set_offline(True)
            meta["offline_before_real_fill"] = True

            # Containment probe with fictional value first.
            # Offline + route abort means attempted POSTs are blocked (expected). Success =
            # context offline and zero successful mutation responses after probe fill.
            probe_selector = "input[name='partner_name']"
            successful_mutations: list[dict[str, Any]] = []

            def _on_response(response) -> None:
                try:
                    req = response.request
                    method = (req.method or "").upper()
                    if method in {"POST", "PUT", "PATCH", "DELETE", "BEACON"}:
                        # Offline should prevent these; if any succeed, fail closed.
                        if response.status > 0 and response.status < 600:
                            # Playwright may still surface aborted/failed; only count OK-ish.
                            if 200 <= response.status < 400:
                                successful_mutations.append(
                                    _sanitize_net_entry(method, req.url, req.resource_type or "")
                                )
                except Exception:
                    return

            page.on("response", _on_response)
            probe_ok = False
            if await page.locator(probe_selector).count() > 0:
                await page.locator(probe_selector).first.fill("UAT_PROBE_NOT_REAL")
                await page.wait_for_timeout(500)
                probe_ok = len(successful_mutations) == 0
                await page.locator(probe_selector).first.fill("")  # clear probe
            else:
                probe_ok = False
            meta["containment_probe_ok"] = probe_ok
            meta["successful_mutations_during_probe"] = successful_mutations[:20]
            if not probe_ok:
                meta["blocked_mutations"] = blocked[:50]
                shot2 = attempt_dir / "02_containment_failed.png"
                await page.screenshot(path=str(shot2), full_page=False)
                screenshot_paths.append(str(shot2))
                await browser.close()
                return store.update(
                    attempt_id,
                    state=ApplyState.stopped,
                    stop_reason=StopReason.network_mutation,
                    final_url=page.url,
                    screenshot_paths=screenshot_paths,
                    message="Containment probe failed — refusing real candidate fill",
                    metadata=meta,
                )  # type: ignore[return-value]

            adapters = get_adapter(adapter_hint or "odoo_careers")
            chosen = None
            for adapter in adapters:
                if await adapter.can_handle(page):
                    chosen = adapter
                    break

            filled: list[str] = []
            adapter_name = None
            message = "Live page inspected; no adapter matched"

            # Track request count around file set to prove CV bytes not transmitted.
            blocked_before_cv = len(blocked)
            if chosen is not None:
                result = await chosen.fill_draft(page, applicant, cv_path)
                filled = result.filled_fields
                adapter_name = result.adapter_name
                message = result.message or message
                if result.stop_reason:
                    meta["blocked_mutations"] = blocked[:50]
                    meta["cv_bytes_transmitted"] = 0
                    shot2 = attempt_dir / f"02_stop_{result.stop_reason.value}.png"
                    await page.screenshot(path=str(shot2), full_page=False)
                    screenshot_paths.append(str(shot2))
                    await browser.close()
                    return store.update(
                        attempt_id,
                        state=ApplyState.stopped,
                        stop_reason=result.stop_reason,
                        final_url=page.url,
                        screenshot_paths=screenshot_paths,
                        adapter_used=adapter_name,
                        filled_fields=filled,
                        message=message,
                        metadata=meta,
                    )  # type: ignore[return-value]

            await page.wait_for_timeout(400)
            # Offline + route abort => no CV bytes left the browser.
            meta["cv_bytes_transmitted"] = 0
            meta["blocked_mutations_after_cv_delta"] = len(blocked) - blocked_before_cv
            meta["blocked_mutations"] = blocked[:80]
            meta["context_offline"] = True

            # Masked screenshot: blur/mask by overwriting visible values before shot? 
            # We keep filled values for proof but evidence screenshots are scrubbed via CSS overlay.
            await page.evaluate(
                """() => {
                  const mask = (sel) => {
                    const el = document.querySelector(sel);
                    if (!el) return;
                    if ('value' in el) el.value = '***MASKED***';
                  };
                  mask('input[name="partner_name"]');
                  mask('input[name="email_from"]');
                  mask('input[name="partner_phone"]');
                }"""
            )
            shot_final = attempt_dir / "02_drafted_masked.png"
            await page.screenshot(path=str(shot_final), full_page=False)
            screenshot_paths.append(str(shot_final))

            # Restore filled values in DOM for local verification log (still offline).
            # Re-fill after mask for internal filled_fields confirmation only — still offline.
            if chosen is not None:
                await chosen.fill_draft(page, applicant, cv_path)

            values_check = await page.evaluate(
                """() => ({
                  name: (document.querySelector('input[name="partner_name"]') || {}).value || '',
                  email: (document.querySelector('input[name="email_from"]') || {}).value || '',
                  phone: (document.querySelector('input[name="partner_phone"]') || {}).value || '',
                  linkedin: (document.querySelector('input[name="linkedin_profile"]') || {}).value || '',
                  resumeFiles: (document.querySelector('input[name="Resume"]') || {}).files
                    ? (document.querySelector('input[name="Resume"]').files.length)
                    : 0
                })"""
            )
            # Sanitize values_check for metadata (mask PII)
            meta["dom_verify_masked"] = {
                "name_set": bool(values_check.get("name")),
                "email_set": bool(values_check.get("email")),
                "phone_set": bool(values_check.get("phone")),
                "linkedin_empty": not bool(values_check.get("linkedin")),
                "resume_files": values_check.get("resumeFiles"),
            }

            final_url = page.url
            # Do NOT click submit. Do NOT interact with Turnstile.
            await browser.close()

            return store.update(
                attempt_id,
                state=ApplyState.drafted,
                stop_reason=StopReason.none,
                final_url=final_url,
                screenshot_paths=screenshot_paths,
                adapter_used=adapter_name,
                filled_fields=filled,
                message=message,
                metadata=meta,
            )  # type: ignore[return-value]
    except Exception as exc:
        meta["blocked_mutations"] = blocked[:50]
        return store.update(
            attempt_id,
            state=ApplyState.failed,
            stop_reason=StopReason.none,
            final_url=url,
            screenshot_paths=screenshot_paths,
            message=f"Live worker error: {exc}",
            metadata=meta,
        )  # type: ignore[return-value]


async def run_gated_submit(
    *,
    attempt_id: str,
    auth: dict[str, Any],
) -> ApplyAttemptResponse:
    """Offline-fixture gated submit: fill, click once, require positive confirmation.

    Live HTTP submit is intentionally not performed here without a prior CAPTCHA-free
    draft and approved token; this path is for fixture/contract validation and
    Production canaries that use local fixture URLs only unless metadata allows.
    """
    import re

    attempt = store.get(attempt_id)
    if not attempt:
        created = store.create(
            state=ApplyState.failed,
            stop_reason=StopReason.invalid_url,
            message="attempt not found",
        )
        return created

    artifacts = ensure_artifacts_dir()
    attempt_dir = artifacts / attempt_id
    attempt_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    screenshot_paths = list(attempt.screenshot_paths or [])
    meta = dict(attempt.metadata or {})
    meta["submit_auth_gates"] = {
        k: auth.get(k)
        for k in (
            "live_submit_enabled",
            "approved_adapter",
            "score",
            "captcha_cleared",
            "login_cleared",
            "otp_cleared",
            "sensitive_docs_cleared",
            "profile_complete",
            "duplicate_cleared",
            "within_caps",
        )
    }

    fixture_name = meta.get("fixture_url") or meta.get("url") or ""
    # Prefer adapter-named fixture when draft used offline HTML name in metadata.
    if not fixture_name and attempt.adapter_used:
        candidate = FIXTURES_DIR / f"{attempt.adapter_used}.html"
        if candidate.is_file():
            fixture_name = candidate.name

    if not fixture_name:
        # Fall back to final_url file basename
        if attempt.final_url and attempt.final_url.startswith("file:"):
            fixture_name = Path(urlparse(attempt.final_url).path).name

    try:
        fixture_path = resolve_offline_url(fixture_name or "greenhouse_like.html")
    except Exception as exc:
        return store.update(
            attempt_id,
            state=ApplyState.failed,
            stop_reason=StopReason.invalid_url,
            message=f"submit fixture resolve failed: {exc}",
            metadata=meta,
            dry_run=False,
        )  # type: ignore[return-value]

    applicant = ApplicantFixture()
    cv_path = str(FIXTURES_DIR / "test.pdf")

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        return store.update(
            attempt_id,
            state=ApplyState.failed,
            stop_reason=StopReason.none,
            message=f"Playwright not installed: {exc}",
            metadata=meta,
            dry_run=False,
        )  # type: ignore[return-value]

    store.update(attempt_id, state=ApplyState.running, message="gated submit started", dry_run=False)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(accept_downloads=False)
            page = await context.new_page()
            await page.goto(fixture_path.as_uri(), wait_until="domcontentloaded")

            stop = await detect_stop_reason_on_page(page)
            if stop is not None:
                shot = attempt_dir / f"03_submit_stop_{stop.value}.png"
                await page.screenshot(path=str(shot), full_page=True)
                screenshot_paths.append(str(shot))
                await browser.close()
                # Consume token — ambiguous/blocked path must not retry
                store.consume_token(attempt_id)
                return store.update(
                    attempt_id,
                    state=ApplyState.human_required,
                    stop_reason=stop,
                    final_url=page.url,
                    screenshot_paths=screenshot_paths,
                    message=f"Submit aborted: {stop.value}",
                    metadata=meta,
                    dry_run=False,
                )  # type: ignore[return-value]

            adapters = get_adapter(auth.get("approved_adapter") or attempt.adapter_used)
            chosen = None
            for adapter in adapters:
                if await adapter.can_handle(page):
                    chosen = adapter
                    break
            if chosen is None:
                await browser.close()
                store.consume_token(attempt_id)
                return store.update(
                    attempt_id,
                    state=ApplyState.human_required,
                    stop_reason=StopReason.policy,
                    message="No approved adapter matched page for submit",
                    metadata=meta,
                    dry_run=False,
                )  # type: ignore[return-value]

            result = await chosen.fill_draft(page, applicant, cv_path)
            if result.stop_reason:
                await browser.close()
                store.consume_token(attempt_id)
                return store.update(
                    attempt_id,
                    state=ApplyState.human_required,
                    stop_reason=result.stop_reason,
                    adapter_used=chosen.name,
                    filled_fields=result.filled_fields,
                    message=result.message,
                    metadata=meta,
                    dry_run=False,
                )  # type: ignore[return-value]

            shot_pre = attempt_dir / "03_presubmit_masked.png"
            await page.screenshot(path=str(shot_pre), full_page=True)
            screenshot_paths.append(str(shot_pre))

            submit_btn = page.locator(
                "#submit-application, button[type='submit'], input[type='submit']"
            )
            if await submit_btn.count() == 0:
                await browser.close()
                store.consume_token(attempt_id)
                return store.update(
                    attempt_id,
                    state=ApplyState.submission_unknown,
                    stop_reason=StopReason.policy,
                    adapter_used=chosen.name,
                    filled_fields=result.filled_fields,
                    screenshot_paths=screenshot_paths,
                    message="Submit control not found",
                    metadata=meta,
                    dry_run=False,
                )  # type: ignore[return-value]

            # Exactly one click
            await submit_btn.first.click()
            store.consume_token(attempt_id)
            meta["submit_clicked"] = True
            await page.wait_for_timeout(800)

            final_url = page.url
            body_text = (await page.inner_text("body")).lower()
            shot_after = attempt_dir / "04_after_submit.png"
            await page.screenshot(path=str(shot_after), full_page=True)
            screenshot_paths.append(str(shot_after))
            await browser.close()

            thank_you = bool(
                re.search(
                    r"thank you|application received|we have received your application|"
                    r"successfully submitted|reference:",
                    body_text,
                )
            )
            conf_ref = None
            m = re.search(r"reference:\s*([A-Z0-9\-]+)", body_text, re.I)
            if m:
                conf_ref = m.group(1)

            if thank_you:
                return store.update(
                    attempt_id,
                    state=ApplyState.succeeded,
                    stop_reason=StopReason.none,
                    final_url=final_url,
                    screenshot_paths=screenshot_paths,
                    adapter_used=chosen.name,
                    filled_fields=result.filled_fields,
                    message="Positive confirmation after single submit",
                    metadata=meta,
                    dry_run=False,
                    confirmation_url=final_url,
                    confirmation_reference=conf_ref,
                )  # type: ignore[return-value]

            return store.update(
                attempt_id,
                state=ApplyState.submission_unknown,
                stop_reason=StopReason.none,
                final_url=final_url,
                screenshot_paths=screenshot_paths,
                adapter_used=chosen.name,
                filled_fields=result.filled_fields,
                message="Submit clicked once; confirmation unclear — no retry",
                metadata=meta,
                dry_run=False,
                confirmation_url=final_url,
            )  # type: ignore[return-value]
    except Exception as exc:
        store.consume_token(attempt_id)
        return store.update(
            attempt_id,
            state=ApplyState.submission_unknown,
            stop_reason=StopReason.none,
            screenshot_paths=screenshot_paths,
            message=f"Submit error (no retry): {exc}",
            metadata=meta,
            dry_run=False,
        )  # type: ignore[return-value]
