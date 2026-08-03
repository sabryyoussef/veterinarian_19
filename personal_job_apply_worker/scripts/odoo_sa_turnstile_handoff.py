#!/usr/bin/env python3
"""Secure headed handoff: refill approved Odoo S.A. apply form, stop before Submit.

Does NOT click Apply/Send. Does NOT solve Turnstile.
Leaves Chromium open for human Turnstile + single submit click.
Observes outcome after human interaction; never retries submit.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path

from playwright.async_api import async_playwright

EVID = Path(os.environ.get("HANDOFF_EVID") or open("/tmp/odoo_sa_handoff_evid.txt").read().strip())
FILL_PATH = Path("/fill/odoo_com_canary_fill.json")
INTRO_PATH = EVID / "SHORT_INTRODUCTION.txt"
TOKEN_PATH = Path("/token/odoo_sa_submit_token.json")
READY_PATH = EVID / "HANDOFF_READY.json"
RESULT_PATH = EVID / "HUMAN_SUBMIT_RESULT.json"
URL = "https://www.odoo.com/jobs/apply/software-developer-1"
READY_FLAG = Path("/tmp/handoff_ready.flag")
DONE_FLAG = Path("/tmp/handoff_done.flag")


def mask_email(e: str) -> str:
    u, d = e.split("@", 1)
    return u[:2] + "***@" + d[0] + "***." + d.split(".")[-1]


def mask_phone(p: str) -> str:
    digits = re.sub(r"\D", "", p)
    return digits[:3] + "***" + digits[-2:]


def consume_token(meta: dict) -> dict:
    data = json.loads(TOKEN_PATH.read_text())
    if data.get("consumed") or int(data.get("uses", 0)) >= int(data.get("max_uses", 1)):
        raise RuntimeError("submit_token_already_consumed")
    if time.time() > float(data.get("expires_at", 0)):
        raise RuntimeError("submit_token_expired")
    if int(data.get("application_id")) != 32:
        raise RuntimeError("submit_token_app_mismatch")
    if data.get("url") != URL:
        raise RuntimeError("submit_token_url_mismatch")
    data["uses"] = int(data.get("uses", 0)) + 1
    data["consumed"] = True
    data["consumed_at"] = time.time()
    data["consume_meta"] = meta
    TOKEN_PATH.write_text(json.dumps(data, indent=2))
    return data


async def snapshot_form(page) -> dict:
    return await page.evaluate(
        """() => {
          const val = (sel) => {
            const el = document.querySelector(sel);
            return el ? (el.value || '') : null;
          };
          const btn = document.querySelector('#apply-btn');
          const notEu = document.querySelector('input[name="not_eu_citizen"]');
          return {
            url: location.href,
            title: document.title,
            partner_name: val('input[name="partner_name"]'),
            email_from: val('input[name="email_from"], input[name="partner_email"]'),
            partner_phone: val('input[name="partner_phone"], input[type="tel"]'),
            linkedin: val('input[name="linkedin_profile"]'),
            short_introduction: (() => {
              const t = document.querySelector('textarea[name="short_introduction"]');
              return t ? t.value : null;
            })(),
            resume_files: (() => {
              const r = document.querySelector('input[name="Resume"]');
              return r && r.files ? r.files.length : 0;
            })(),
            passport_number: val('input[name="passport_number"]'),
            not_eu_citizen_checked: !!(notEu && notEu.checked),
            apply_btn: btn ? {
              text: (btn.innerText || btn.value || '').trim(),
              disabled: !!(btn.disabled || btn.classList.contains('disabled') || btn.classList.contains('cf_form_disabled')),
              classes: btn.className,
            } : null,
            has_turnstile: !!(
              document.querySelector('iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"], .cf-turnstile')
            ),
          };
        }"""
    )


async def fill_form(page, fill: dict, intro: str) -> None:
    await page.goto(URL, wait_until="domcontentloaded", timeout=120000)
    await page.wait_for_selector("#hr_recruitment_form, form", timeout=60000)

    # Prefer Resume path: LinkedIn must stay empty.
    linkedin = page.locator('input[name="linkedin_profile"]')
    if await linkedin.count():
        await linkedin.first.fill("")

    await page.wait_for_selector('input[name="partner_name"]', timeout=30000)
    await page.fill('input[name="partner_name"]', fill["full_name"])
    await page.fill('input[name="email_from"]', fill["email"])
    await page.fill('input[name="partner_phone"]', fill["phone"])
    await page.fill('textarea[name="short_introduction"]', intro)

    # Optional “I'm not EU citizen”: leave unchecked — no passport number/copy.
    not_eu = page.locator('input[name="not_eu_citizen"]')
    if await not_eu.count() and await not_eu.first.is_checked():
        await not_eu.first.uncheck()
    # passport_number is hidden when unchecked; clear via DOM only if present
    await page.evaluate(
        """() => {
          const p = document.querySelector('input[name="passport_number"]');
          if (p) p.value = '';
          const f = document.querySelector('input[name="Passport copy"]');
          if (f) { try { f.value = ''; } catch (e) {} }
        }"""
    )

    resume = page.locator('input[name="Resume"]')
    if not await resume.count():
        raise RuntimeError("resume_file_input_not_found")
    await resume.first.set_input_files(fill["cv_path"])


async def classify_outcome(page, network_posts: list) -> dict:
    url = page.url
    text = await page.evaluate("() => document.body ? document.body.innerText.slice(0, 8000) : ''")
    lower = text.lower()
    positive = bool(
        re.search(
            r"application (has been )?sent|thank you for (your )?appl|we have received your application|successfully submitted|application received",
            lower,
        )
    )
    errorish = bool(re.search(r"error|failed|forbidden|not allowed|captcha|try again", lower))
    ref = None
    m = re.search(r"(application|reference|ref)[#:\s]+([A-Za-z0-9_-]{4,})", text, re.I)
    if m:
        ref = m.group(0)
    form_post_ok = any(
        r.get("url", "").endswith("/website/form/") and r.get("status") in (200, 201)
        for r in network_posts
    )
    if positive or form_post_ok:
        verdict = "ODOO_SA_REAL_APPLICATION_CANARY_SUBMITTED"
        state = "applied"
    elif errorish and not form_post_ok:
        verdict = "ODOO_SA_REAL_APPLICATION_HUMAN_STEP_FAILED"
        state = "human_step_failed"
    else:
        verdict = "ODOO_SA_REAL_APPLICATION_SUBMISSION_UNKNOWN"
        state = "submission_unknown"
    return {
        "verdict": verdict,
        "odoo_state": state,
        "final_url": url,
        "positive_text": positive,
        "form_post_ok": form_post_ok,
        "reference_guess": ref,
        "page_text_excerpt": text[:1200],
    }


async def main() -> int:
    fill = json.loads(FILL_PATH.read_text())
    # Inside container path for CV
    if not Path(fill["cv_path"]).exists():
        alt = Path("/cv/Sabry_Youssef_CV.pdf")
        if alt.exists():
            fill["cv_path"] = str(alt)
    intro = INTRO_PATH.read_text().strip()
    EVID.mkdir(parents=True, exist_ok=True)
    (EVID / "screenshots").mkdir(exist_ok=True)
    (EVID / "network").mkdir(exist_ok=True)

    network_posts: list[dict] = []
    result_base = {
        "application_id": 32,
        "attempt_id": 5,
        "job_id": 40,
        "url": URL,
        "short_introduction": intro,
        "values_masked": {
            "name": fill["full_name"],
            "email": mask_email(fill["email"]),
            "phone": mask_phone(fill["phone"]),
            "linkedin": "",
            "resume": "Sabry_Youssef_CV.pdf",
            "not_eu_citizen": False,
            "salary_included": False,
        },
        "submit_clicked_by_automation": False,
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--window-size=1280,900",
                "--window-position=40,40",
            ],
        )
        context = await browser.new_context(
            accept_downloads=False,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        def on_response(resp):
            try:
                u = resp.url
                if "odoo.com" in u and ("/website/form" in u or "jobs" in u):
                    network_posts.append(
                        {
                            "url": u.split("?")[0],
                            "status": resp.status,
                            "method": resp.request.method,
                            "ts": time.time(),
                        }
                    )
            except Exception:
                pass

        page.on("response", on_response)

        await fill_form(page, fill, intro)
        snap = await snapshot_form(page)
        shot = EVID / "screenshots" / "handoff_before_human.png"
        await page.screenshot(path=str(shot), full_page=True)

        ready = {
            **result_base,
            "status": "ODOO_SA_TURNSTILE_HANDOFF_READY",
            "ready_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "form_snapshot": {
                **snap,
                "email_from": mask_email(snap["email_from"]) if snap.get("email_from") else None,
                "partner_phone": mask_phone(snap["partner_phone"]) if snap.get("partner_phone") else None,
            },
            "screenshot": str(shot),
            "instructions": [
                "Open the secure Selkies/Firefox handoff URL on master or Tailscale only",
                "Solve Cloudflare Turnstile manually if presented",
                "Review filled values",
                "Click Send my application exactly once",
                "Do not refresh/retry",
            ],
        }
        READY_PATH.write_text(json.dumps(ready, indent=2))
        READY_FLAG.write_text("ready\n")
        print("HANDOFF_READY", READY_PATH, flush=True)

        # Observe until human submit signal: URL/text change, form POST, or DONE_FLAG, max 2h
        deadline = time.time() + 2 * 3600
        baseline_url = page.url
        baseline_posts = len(network_posts)
        outcome = None
        while time.time() < deadline:
            if DONE_FLAG.exists():
                break
            await page.wait_for_timeout(2000)
            cur = page.url
            text_head = await page.evaluate(
                "() => (document.body && document.body.innerText || '').slice(0, 500).toLowerCase()"
            )
            new_posts = len(network_posts) > baseline_posts
            successish = bool(
                re.search(r"thank you|application (has been )?sent|received your application", text_head)
            )
            left_form = ("/jobs/apply/" not in cur) and (cur != baseline_url)
            if new_posts or successish or left_form:
                # Give the page a moment to settle; do not click anything
                await page.wait_for_timeout(2500)
                outcome = await classify_outcome(page, network_posts)
                break

        if outcome is None:
            outcome = {
                "verdict": "ODOO_SA_REAL_APPLICATION_HUMAN_STEP_FAILED",
                "odoo_state": "human_step_failed",
                "final_url": page.url,
                "reason": "handoff_timeout_or_no_human_submit_observed",
                "page_text_excerpt": await page.evaluate(
                    "() => document.body ? document.body.innerText.slice(0, 800) : ''"
                ),
            }

        final_shot = EVID / "screenshots" / "after_human.png"
        try:
            await page.screenshot(path=str(final_shot), full_page=True)
        except Exception as e:
            final_shot = f"screenshot_failed:{e}"

        token_fp = None
        try:
            tok = consume_token({"verdict": outcome.get("verdict"), "at": time.time()})
            token_fp = hashlib.sha256(tok["token"].encode()).hexdigest()[:16]
        except Exception as e:
            token_fp = f"consume_error:{e}"

        final = {
            **result_base,
            **outcome,
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "screenshot_after": str(final_shot),
            "network_posts_sanitized": network_posts[-20:],
            "token_fingerprint": token_fp,
        }
        RESULT_PATH.write_text(json.dumps(final, indent=2))
        (EVID / "network" / "posts.json").write_text(json.dumps(network_posts, indent=2))
        print("HUMAN_RESULT", outcome.get("verdict"), flush=True)

        # Keep browser briefly for visual confirm, then close
        await page.wait_for_timeout(5000)
        await browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
