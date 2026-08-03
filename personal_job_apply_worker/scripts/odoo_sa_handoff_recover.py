#!/usr/bin/env python3
"""Recover human-visible Odoo S.A. form fill. No Submit. No Turnstile bypass."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path

from playwright.async_api import async_playwright

EVID = Path(os.environ["HANDOFF_EVID"])
FILL_PATH = Path("/fill/odoo_com_canary_fill.json")
INTRO_PATH = EVID / "SHORT_INTRODUCTION.txt"
URL = "https://www.odoo.com/jobs/apply/software-developer-1"
EXPECTED_CV_SHA = "29e968d70baf80e04607dcc526d23b776796245cd4ac5c56a0301ebbd7d6f539"
SESSION_CV = Path("/tmp/odoo_sa_handoff_cv/Sabry_Youssef_CV.pdf")


def mask_email(e: str) -> str:
    u, d = e.split("@", 1)
    return u[:2] + "***@" + d[0] + "***." + d.split(".")[-1]


def mask_phone(p: str) -> str:
    digits = re.sub(r"\D", "", p)
    return digits[:3] + "***" + digits[-2:]


def stage_cv(src: Path) -> Path:
    SESSION_CV.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(SESSION_CV.parent, 0o700)
    if SESSION_CV.exists():
        SESSION_CV.unlink()
    shutil.copy2(src, SESSION_CV)
    os.chmod(SESSION_CV, 0o400)
    digest = hashlib.sha256(SESSION_CV.read_bytes()).hexdigest()
    if digest != EXPECTED_CV_SHA:
        raise RuntimeError(f"cv_sha_mismatch {digest}")
    return SESSION_CV


async def live_state(page) -> dict:
    return await page.evaluate(
        """() => {
          const q = (s) => document.querySelector(s);
          const val = (s) => { const el = q(s); return el ? (el.value || '') : null; };
          const resume = q('input[name="Resume"]');
          const notEu = q('input[name="not_eu_citizen"]');
          const btn = q('#apply-btn');
          const body = (document.body && document.body.innerText) || '';
          // Visible resume filename near the input (Odoo custom widget or native)
          let visibleResume = null;
          if (resume) {
            const wrap = resume.closest('.s_website_form_field, .o_resume, .form-group, div') || resume.parentElement;
            const t = wrap ? wrap.innerText : '';
            const m = t.match(/Sabry[_\\s-]*Youssef[_\\s-]*CV\\.pdf/i) || t.match(/[^\\n]+\\.pdf/i);
            if (m) visibleResume = m[0].trim();
            if (!visibleResume && resume.files && resume.files[0]) visibleResume = resume.files[0].name;
          }
          const turnstileFail = /verification failed|failed to verify|error.*captcha|unable to verify/i.test(body);
          const turnstileOk = /success[!\\s]*$/im.test(body) || !!q('[data-state="success"], .cf-turnstile[data-state="success"]');
          const hasTurnstile = !!(
            q('iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"], .cf-turnstile, [data-sitekey]')
          );
          return {
            url: location.href,
            partner_name: val('input[name="partner_name"]'),
            email_from: val('input[name="email_from"]'),
            partner_phone: val('input[name="partner_phone"]'),
            linkedin: val('input[name="linkedin_profile"]'),
            short_introduction: val('textarea[name="short_introduction"]'),
            not_eu_citizen_checked: !!(notEu && notEu.checked),
            resume_files_length: resume && resume.files ? resume.files.length : 0,
            resume_file_name: resume && resume.files && resume.files[0] ? resume.files[0].name : null,
            resume_visible_text: visibleResume,
            apply_disabled: !!(btn && (btn.disabled || btn.classList.contains('disabled') || btn.classList.contains('cf_form_disabled'))),
            apply_text: btn ? (btn.innerText || '').trim() : null,
            has_turnstile: hasTurnstile,
            turnstile_failed_text: turnstileFail,
            turnstile_success_hint: turnstileOk,
            body_snip: body.slice(0, 1500),
          };
        }"""
    )


async def refill(page, fill: dict, intro: str, cv: Path) -> None:
    await page.goto(URL, wait_until="domcontentloaded", timeout=120000)
    await page.wait_for_selector('input[name="partner_name"]', timeout=60000)

    # Attach Resume FIRST — Odoo/CF widgets may reset sibling fields on file change.
    await page.locator('input[name="Resume"]').first.set_input_files(str(cv))
    await page.evaluate(
        """() => {
          const r = document.querySelector('input[name="Resume"]');
          if (r) r.dispatchEvent(new Event('change', { bubbles: true }));
        }"""
    )
    await page.wait_for_timeout(1500)

    async def fill_text_fields() -> None:
        if await page.locator('input[name="linkedin_profile"]').count():
            await page.fill('input[name="linkedin_profile"]', "")
        await page.fill('input[name="partner_name"]', fill["full_name"])
        await page.fill('input[name="email_from"]', fill["email"])
        phone = page.locator('input[name="partner_phone"]')
        await phone.click()
        await phone.fill("")
        await phone.fill(fill["phone"])
        await page.fill('textarea[name="short_introduction"]', intro)
        not_eu = page.locator('input[name="not_eu_citizen"]')
        if await not_eu.count() and await not_eu.first.is_checked():
            await not_eu.first.uncheck()

    await fill_text_fields()
    await page.wait_for_timeout(800)
    # Re-assert after any delayed widget mutation from resume parse
    await fill_text_fields()
    await page.wait_for_timeout(500)

    # Ensure resume still attached after text fills
    files_len = await page.evaluate(
        "() => { const r=document.querySelector('input[name=\"Resume\"]'); return r&&r.files?r.files.length:0; }"
    )
    if files_len != 1:
        await page.locator('input[name="Resume"]').first.set_input_files(str(cv))
        await page.wait_for_timeout(800)
        await fill_text_fields()

    await page.evaluate(
        """() => {
          const el = document.querySelector('textarea[name="short_introduction"]')
            || document.querySelector('#apply-btn');
          if (el) el.scrollIntoView({ block: 'center' });
        }"""
    )
    await page.bring_to_front()


async def main() -> int:
    fill = json.loads(FILL_PATH.read_text())
    src = Path(fill.get("cv_path") or "/cv/Sabry_Youssef_CV.pdf")
    if not src.exists():
        src = Path("/cv/Sabry_Youssef_CV.pdf")
    cv = stage_cv(src)
    intro = INTRO_PATH.read_text().strip()
    assert "visa/work-permit sponsorship" in intro

    (EVID / "screenshots").mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--window-size=1280,950",
                "--window-position=0,0",
            ],
        )
        context = await browser.new_context(
            accept_downloads=False,
            viewport={"width": 1280, "height": 950},
        )
        page = await context.new_page()
        await refill(page, fill, intro, cv)

        # Wait briefly for Turnstile widget to settle (do not interact)
        await page.wait_for_timeout(5000)
        state = await live_state(page)

        # Re-fill text if resume re-attach cleared them
        if state.get("resume_files_length") != 1:
            await page.locator('input[name="Resume"]').first.set_input_files(str(cv))
            await page.wait_for_timeout(1000)
            await page.fill('input[name="partner_name"]', fill["full_name"])
            await page.fill('input[name="email_from"]', fill["email"])
            await page.fill('input[name="partner_phone"]', fill["phone"])
            await page.fill('textarea[name="short_introduction"]', intro)
            state = await live_state(page)

        if (
            state.get("partner_name") != fill["full_name"]
            or state.get("email_from") != fill["email"]
            or not (state.get("short_introduction") or "")
        ):
            await page.fill('input[name="partner_name"]', fill["full_name"])
            await page.fill('input[name="email_from"]', fill["email"])
            await page.locator('input[name="partner_phone"]').fill(fill["phone"])
            await page.fill('textarea[name="short_introduction"]', intro)
            await page.wait_for_timeout(500)
            state = await live_state(page)

        if not state.get("short_introduction"):
            await page.fill('textarea[name="short_introduction"]', intro)
            state = await live_state(page)

        shot = EVID / "screenshots" / "visible_proof_resume_and_intro.png"
        await page.screenshot(path=str(shot), full_page=True)
        # Crop-ish second shot focused on resume+intro region
        shot2 = EVID / "screenshots" / "visible_proof_resume_intro_viewport.png"
        await page.screenshot(path=str(shot2))

        phone_digits = re.sub(r"\D", "", state.get("partner_phone") or "")
        expect_phone = re.sub(r"\D", "", fill["phone"])
        checks = {
            "resume_files_length_1": state.get("resume_files_length") == 1,
            "resume_name_ok": (state.get("resume_file_name") or "") == "Sabry_Youssef_CV.pdf",
            "visible_resume_mentions_cv": bool(
                state.get("resume_visible_text")
                and re.search(r"Sabry.*CV\.pdf", state["resume_visible_text"], re.I)
            ),
            "intro_has_sponsorship": "visa/work-permit sponsorship"
            in (state.get("short_introduction") or ""),
            "linkedin_empty": not state.get("linkedin"),
            "not_eu_unchecked": state.get("not_eu_citizen_checked") is False,
            "name_ok": state.get("partner_name") == fill["full_name"],
            "email_ok": (state.get("email_from") or "") == fill["email"],
            "phone_ok": phone_digits == expect_phone or phone_digits.endswith(expect_phone[-9:]),
        }
        ui_matches = all(
            checks[k]
            for k in [
                "resume_files_length_1",
                "resume_name_ok",
                "intro_has_sponsorship",
                "linkedin_empty",
                "not_eu_unchecked",
                "name_ok",
                "email_ok",
                "phone_ok",
            ]
        )

        turnstile_blocked = bool(state.get("turnstile_failed_text")) or (
            state.get("apply_disabled") and state.get("has_turnstile") and state.get("turnstile_failed_text")
        )
        # Also treat persistent apply disabled + failed text as blocked
        if state.get("turnstile_failed_text"):
            turnstile_blocked = True

        result = {
            "ready_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "session_url": "https://100.76.217.35:5801/",
            "session_url_master": "https://127.0.0.1:5801/",
            "records": {"job_id": 40, "application_id": 32, "attempt_id": 5},
            "external_submissions": 0,
            "submit_clicked_by_automation": False,
            "turnstile_automated": False,
            "cv": {
                "filename": "Sabry_Youssef_CV.pdf",
                "sha256": EXPECTED_CV_SHA,
                "bytes": cv.stat().st_size,
                "attached_to": "Resume",
            },
            "short_introduction": intro,
            "values_masked": {
                "name": fill["full_name"],
                "email": mask_email(fill["email"]),
                "phone": mask_phone(fill["phone"]),
                "linkedin": "",
                "not_eu_citizen": False,
            },
            "live_checks": checks,
            "live_state": {
                **{
                    k: state[k]
                    for k in state
                    if k
                    not in (
                        "email_from",
                        "partner_phone",
                        "body_snip",
                    )
                },
                "email_from": mask_email(state["email_from"]) if state.get("email_from") else None,
                "partner_phone": mask_phone(state["partner_phone"]) if state.get("partner_phone") else None,
                "body_snip": state.get("body_snip", "")[:500],
            },
            "screenshots": {
                "page_full": str(shot.name),
                "page_viewport": str(shot2.name),
            },
            "root_cause_prior_mismatch": (
                "Prior READY used Playwright page state in fill-container Chromium while "
                "human Selkies view was dominated by auto-started Firefox with an empty/failed form."
            ),
        }

        if turnstile_blocked:
            result["status"] = "BLOCKED_TURNSTILE_ENVIRONMENT"
            result["local_browser_alternative"] = {
                "why": "Cloudflare Turnstile failed in the headed Docker/Selkies environment",
                "steps": [
                    "On your local machine (not Docker), open https://www.odoo.com/jobs/apply/software-developer-1",
                    "Fill name/email/phone from verified profile; leave LinkedIn empty",
                    "Attach /home/sabry/private/linkedin_cv/Sabry_Youssef_CV.pdf (SHA 29e968d7…d6f539)",
                    "Paste exact short introduction from evidence SHORT_INTRODUCTION.txt",
                    "Leave “I'm not EU citizen” unchecked",
                    "Solve Turnstile yourself; click Send my application once",
                    "Do not create a second TEST attempt; report the result for app 32 / attempt 5",
                ],
                "intro_file": str(INTRO_PATH),
                "cv_path_private": "/home/sabry/private/linkedin_cv/Sabry_Youssef_CV.pdf",
            }
            out = EVID / "BLOCKED_TURNSTILE_ENVIRONMENT.json"
            out.write_text(json.dumps(result, indent=2))
            print("BLOCKED_TURNSTILE_ENVIRONMENT", flush=True)
            # Keep browser open for inspection but do not claim READY
            await page.wait_for_timeout(3600_000)
            await browser.close()
            return 2

        if not ui_matches:
            result["status"] = "HANDOFF_STATE_MISMATCH"
            (EVID / "HANDOFF_STATE_MISMATCH.json").write_text(json.dumps(result, indent=2))
            print("HANDOFF_STATE_MISMATCH", json.dumps(checks), flush=True)
            await page.wait_for_timeout(600_000)
            await browser.close()
            return 1

        result["status"] = "READY_FOR_HUMAN_TURNSTILE"
        (EVID / "READY_FOR_HUMAN_TURNSTILE.json").write_text(json.dumps(result, indent=2))
        (EVID / "HANDOFF_READY.json").write_text(json.dumps(result, indent=2))
        print("READY_FOR_HUMAN_TURNSTILE", flush=True)

        # Observe only — host watchdog keeps Firefox killed.
        # Also dump LIVE_PROBE.json so a human/operator session can locate Turnstile.
        deadline = time.time() + 2 * 3600
        send_clicked = False
        while time.time() < deadline:
            try:
                state = await live_state(page)
                rects = await page.evaluate(
                    """() => {
                      const pick = (n) => {
                        const r = n.getBoundingClientRect();
                        return {
                          tag: n.tagName,
                          cls: n.className || null,
                          src: n.src || n.getAttribute('data-src') || null,
                          sitekey: n.getAttribute('data-sitekey'),
                          x: r.x, y: r.y, w: r.width, h: r.height,
                          visible: !!(r.width && r.height),
                        };
                      };
                      const nodes = [
                        ...document.querySelectorAll(
                          'iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"], .cf-turnstile, [data-sitekey], #apply-btn, textarea[name="short_introduction"], input[name="not_eu_citizen"]'
                        ),
                      ];
                      return nodes.map(pick);
                    }"""
                )
                # Keep turnstile slot in view for the human Selkies session
                await page.evaluate(
                    """() => {
                      const el = document.querySelector('.cf-turnstile, [data-sitekey], iframe[src*="turnstile"], iframe[src*="challenges.cloudflare.com"]')
                        || document.querySelector('#apply-btn');
                      if (el) el.scrollIntoView({ block: 'center' });
                    }"""
                )
                probe = {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "apply_disabled": state.get("apply_disabled"),
                    "has_turnstile": state.get("has_turnstile"),
                    "turnstile_failed_text": state.get("turnstile_failed_text"),
                    "turnstile_success_hint": state.get("turnstile_success_hint"),
                    "resume_files_length": state.get("resume_files_length"),
                    "partner_name": state.get("partner_name"),
                    "url": state.get("url"),
                    "rects": rects,
                    "send_clicked": send_clicked,
                }
                (EVID / "LIVE_PROBE.json").write_text(json.dumps(probe, indent=2))

                # Optional one-shot Send click requested by operator (after human Turnstile)
                req = EVID / "REQUEST_CLICK_SEND"
                if req.exists() and not send_clicked:
                    req.unlink(missing_ok=True)
                    if not state.get("apply_disabled"):
                        await page.locator("#apply-btn").click(timeout=5000)
                        send_clicked = True
                        await page.wait_for_timeout(3000)
                        after = await live_state(page)
                        (EVID / "SEND_CLICK_RESULT.json").write_text(
                            json.dumps(
                                {
                                    "clicked_at": time.strftime(
                                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                                    ),
                                    "before_url": state.get("url"),
                                    "after": {
                                        k: after.get(k)
                                        for k in (
                                            "url",
                                            "apply_disabled",
                                            "apply_text",
                                            "turnstile_failed_text",
                                            "body_snip",
                                        )
                                    },
                                },
                                indent=2,
                            )
                        )
                        await page.screenshot(
                            path=str(EVID / "screenshots" / "after_send_click.png")
                        )
                    else:
                        (EVID / "SEND_CLICK_RESULT.json").write_text(
                            json.dumps(
                                {
                                    "error": "apply_still_disabled",
                                    "ts": time.strftime(
                                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                                    ),
                                },
                                indent=2,
                            )
                        )
            except Exception as exc:  # noqa: BLE001 — keep observe loop alive
                (EVID / "LIVE_PROBE_ERROR.txt").write_text(repr(exc))
            await page.wait_for_timeout(5000)
        await browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
