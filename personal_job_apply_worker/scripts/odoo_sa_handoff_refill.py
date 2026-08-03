#!/usr/bin/env python3
"""Refill Odoo S.A. apply form in existing headed handoff. No Submit. No Turnstile solve."""

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
    """Copy CV into session-only path with restrictive perms. Never into the repo."""
    SESSION_CV.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(SESSION_CV.parent, 0o700)
    if SESSION_CV.exists():
        SESSION_CV.unlink()
    shutil.copy2(src, SESSION_CV)
    os.chmod(SESSION_CV, 0o400)
    digest = hashlib.sha256(SESSION_CV.read_bytes()).hexdigest()
    if digest != EXPECTED_CV_SHA:
        raise RuntimeError(f"cv_sha_mismatch got={digest}")
    return SESSION_CV


async def snapshot(page) -> dict:
    return await page.evaluate(
        """() => {
          const val = (sel) => {
            const el = document.querySelector(sel);
            return el ? (el.value || '') : null;
          };
          const btn = document.querySelector('#apply-btn');
          const notEu = document.querySelector('input[name="not_eu_citizen"]');
          const resume = document.querySelector('input[name="Resume"]');
          const ts = document.querySelector(
            'iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"], .cf-turnstile, [data-sitekey]'
          );
          return {
            url: location.href,
            title: document.title,
            partner_name: val('input[name="partner_name"]'),
            email_from: val('input[name="email_from"]'),
            partner_phone: val('input[name="partner_phone"]'),
            linkedin: val('input[name="linkedin_profile"]'),
            short_introduction: val('textarea[name="short_introduction"]'),
            passport_number: val('input[name="passport_number"]'),
            not_eu_citizen_checked: !!(notEu && notEu.checked),
            resume_files: resume && resume.files ? resume.files.length : 0,
            resume_filename: resume && resume.files && resume.files[0] ? resume.files[0].name : null,
            apply_btn: btn ? {
              text: (btn.innerText || btn.value || '').trim(),
              disabled: !!(btn.disabled || btn.classList.contains('disabled') || btn.classList.contains('cf_form_disabled')),
              classes: btn.className,
            } : null,
            has_turnstile_widget: !!ts,
          };
        }"""
    )


async def refill(page, fill: dict, intro: str, cv_path: Path) -> None:
    await page.goto(URL, wait_until="domcontentloaded", timeout=120000)
    await page.wait_for_selector('input[name="partner_name"]', timeout=60000)

    # Clear LinkedIn explicitly
    linkedin = page.locator('input[name="linkedin_profile"]')
    if await linkedin.count():
        await linkedin.first.fill("")

    await page.fill('input[name="partner_name"]', fill["full_name"])
    await page.fill('input[name="email_from"]', fill["email"])
    await page.fill('input[name="partner_phone"]', fill["phone"])
    await page.fill('textarea[name="short_introduction"]', intro)

    not_eu = page.locator('input[name="not_eu_citizen"]')
    if await not_eu.count() and await not_eu.first.is_checked():
        await not_eu.first.uncheck()
    await page.evaluate(
        """() => {
          const p = document.querySelector('input[name="passport_number"]');
          if (p) p.value = '';
        }"""
    )

    resume = page.locator('input[name="Resume"]')
    if not await resume.count():
        raise RuntimeError("resume_input_missing")
    await resume.first.set_input_files(str(cv_path))

    # Position near Turnstile / apply control for human
    apply = page.locator("#apply-btn")
    if await apply.count():
        await apply.first.scroll_into_view_if_needed()
    else:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

    # Bring Chromium forward on the VNC desktop when possible
    await page.bring_to_front()


async def main() -> int:
    fill = json.loads(FILL_PATH.read_text())
    src = Path(fill.get("cv_path") or "/cv/Sabry_Youssef_CV.pdf")
    if not src.exists():
        src = Path("/cv/Sabry_Youssef_CV.pdf")
    cv_path = stage_cv(src)
    intro = INTRO_PATH.read_text().strip()
    if "visa/work-permit sponsorship" not in intro:
        raise RuntimeError("intro_missing_sponsorship_disclosure")

    EVID.mkdir(parents=True, exist_ok=True)
    (EVID / "screenshots").mkdir(exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--window-size=1280,900",
                "--window-position=20,20",
                "--start-maximized",
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
        await refill(page, fill, intro, cv_path)
        # Re-assert values once (DOM can reset file inputs on some navigations)
        await page.wait_for_timeout(800)
        snap = await snapshot(page)
        if snap.get("resume_files", 0) < 1:
            await page.locator('input[name="Resume"]').first.set_input_files(str(cv_path))
            await page.wait_for_timeout(500)
            snap = await snapshot(page)
        if not snap.get("short_introduction"):
            await page.fill('textarea[name="short_introduction"]', intro)
            snap = await snapshot(page)

        shot = EVID / "screenshots" / "ready_for_human_turnstile.png"
        await page.screenshot(path=str(shot), full_page=True)

        ready = {
            "status": "READY_FOR_HUMAN_TURNSTILE",
            "ready_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "session_url": "https://100.76.217.35:5801/",
            "session_url_master": "https://127.0.0.1:5801/",
            "records": {"job_id": 40, "application_id": 32, "attempt_id": 5},
            "external_submissions": 0,
            "submit_clicked_by_automation": False,
            "cv": {
                "filename": "Sabry_Youssef_CV.pdf",
                "sha256": EXPECTED_CV_SHA,
                "bytes": cv_path.stat().st_size,
                "attached_to": "Resume",
                "session_path_only": True,
            },
            "values_masked": {
                "name": fill["full_name"],
                "email": mask_email(fill["email"]),
                "phone": mask_phone(fill["phone"]),
                "linkedin": "",
                "not_eu_citizen": False,
                "salary_included": False,
            },
            "short_introduction": intro,
            "form_snapshot": {
                **snap,
                "email_from": mask_email(snap["email_from"]) if snap.get("email_from") else None,
                "partner_phone": mask_phone(snap["partner_phone"]) if snap.get("partner_phone") else None,
            },
            "screenshot": str(shot.name),
        }
        if snap.get("resume_files", 0) < 1:
            raise RuntimeError("cv_not_attached_after_refill")
        if snap.get("partner_name") != fill["full_name"]:
            raise RuntimeError("name_not_filled")
        if snap.get("linkedin"):
            raise RuntimeError("linkedin_not_empty")
        if snap.get("not_eu_citizen_checked"):
            raise RuntimeError("not_eu_checked")
        if intro not in (snap.get("short_introduction") or ""):
            raise RuntimeError("intro_mismatch")

        (EVID / "READY_FOR_HUMAN_TURNSTILE.json").write_text(json.dumps(ready, indent=2))
        (EVID / "HANDOFF_READY.json").write_text(json.dumps(ready, indent=2))
        print("READY_FOR_HUMAN_TURNSTILE", flush=True)

        # Keep session alive for human; observe submit without clicking
        network_posts = []

        def on_response(resp):
            try:
                u = resp.url
                if "odoo.com" in u and ("/website/form" in u or "jobs" in u):
                    network_posts.append(
                        {"url": u.split("?")[0], "status": resp.status, "method": resp.request.method, "ts": time.time()}
                    )
            except Exception:
                pass

        page.on("response", on_response)
        baseline = len(network_posts)
        baseline_url = page.url
        deadline = time.time() + 2 * 3600
        while time.time() < deadline:
            await page.wait_for_timeout(2000)
            text = await page.evaluate(
                "() => (document.body && document.body.innerText || '').slice(0, 400).toLowerCase()"
            )
            if len(network_posts) > baseline or re.search(
                r"thank you|application (has been )?sent|received your application", text
            ):
                (EVID / "HUMAN_ACTIVITY.json").write_text(
                    json.dumps(
                        {
                            "noticed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "url": page.url,
                            "network_posts": network_posts[-10:],
                            "text_head": text[:400],
                        },
                        indent=2,
                    )
                )
                break
            if page.url != baseline_url and "/jobs/apply/" not in page.url:
                (EVID / "HUMAN_ACTIVITY.json").write_text(
                    json.dumps(
                        {
                            "noticed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "url": page.url,
                            "left_apply_form": True,
                        },
                        indent=2,
                    )
                )
                break

        await page.wait_for_timeout(3000)
        await browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
