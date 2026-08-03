#!/usr/bin/env python3
"""One-shot gated real submit canary for Odoo S.A. Software Developer apply form.

Safety:
- Requires allowlisted one-time token scoped to application 32 + exact URL
- Submits at most once
- Does not solve Turnstile; pauses if interactive challenge
- Does not invent passport data; blocks if passport required without docs
- Restores caller-provided cleanup via exit codes / result JSON
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

EVID = Path(open("/tmp/odoo_sa_submit_evid.txt").read().strip())
TOKEN_PATH = Path("/home/sabry/private/job_orchestrator/odoo_sa_submit_token.json")
FILL_PATH = Path("/home/sabry/private/job_orchestrator/odoo_com_canary_fill.json")
INTRO_PATH = EVID / "SHORT_INTRODUCTION.txt"
RESULT_PATH = EVID / "SUBMIT_RESULT.json"
URL = "https://www.odoo.com/jobs/apply/software-developer-1"
ALLOWED_APP_ID = 32


def consume_token() -> dict:
    data = json.loads(TOKEN_PATH.read_text())
    if data.get("consumed") or data.get("uses", 0) >= data.get("max_uses", 1):
        raise RuntimeError("submit_token_already_consumed")
    if time.time() > float(data.get("expires_at", 0)):
        raise RuntimeError("submit_token_expired")
    if int(data.get("application_id")) != ALLOWED_APP_ID:
        raise RuntimeError("submit_token_app_mismatch")
    if data.get("url") != URL:
        raise RuntimeError("submit_token_url_mismatch")
    data["uses"] = int(data.get("uses", 0)) + 1
    data["consumed"] = True
    data["consumed_at"] = time.time()
    TOKEN_PATH.write_text(json.dumps(data, indent=2))
    return data


def mask_email(e: str) -> str:
    u, d = e.split("@", 1)
    return u[:2] + "***@" + d[0] + "***." + d.split(".")[-1]


def mask_phone(p: str) -> str:
    digits = re.sub(r"\D", "", p)
    return digits[:3] + "***" + digits[-2:]


async def turnstile_interactive(page) -> bool:
    state = await page.evaluate(
        """() => {
          const text = document.body ? document.body.innerText : '';
          const verify = /verify you are human|attention required|just a moment|complete the security check/i.test(text);
          const challengeIframe = !!document.querySelector(
            'iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"]'
          );
          const name = document.querySelector('input[name="partner_name"]');
          let blocked = false;
          if (name) {
            const r = name.getBoundingClientRect();
            const mid = document.elementFromPoint(r.left + 10, r.top + 8);
            blocked = !!(mid && mid !== name && !name.contains(mid) && (mid.tagName === 'IFRAME' || /challenge|turnstile/i.test(mid.className||'')));
          }
          return {verify, challengeIframe, blocked};
        }"""
    )
    return bool(state.get("verify") or state.get("blocked"))


async def main() -> int:
    fill = json.loads(FILL_PATH.read_text())
    intro = INTRO_PATH.read_text().strip()
    token = consume_token()
    result = {
        "verdict": None,
        "token_fingerprint": hashlib.sha256(token["token"].encode()).hexdigest()[:16],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "url": URL,
        "application_id": 32,
        "attempt_id": 5,
        "submit_clicked": False,
        "external_side_effects": [],
        "short_introduction": intro,
        "values_masked": {
            "name": fill["full_name"],
            "email": mask_email(fill["email"]),
            "phone": mask_phone(fill["phone"]),
            "linkedin": "",
            "resume": "Sabry_Youssef_CV.pdf",
        },
    }

    network_log = []
    upload_bytes = {"cv": 0, "other": 0}

    async with async_playwright() as p:
        # Prefer headless; if Turnstile interactive → pause verdict for human session.
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            accept_downloads=False,
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        def on_request(req):
            try:
                parsed = urlparse(req.url)
                entry = {
                    "method": req.method,
                    "host": parsed.hostname,
                    "path": (parsed.path or "")[:160],
                    "resource_type": req.resource_type,
                }
                network_log.append(entry)
                if req.method.upper() in {"POST", "PUT", "PATCH"} and req.post_data:
                    # Approximate body size only (no content logged)
                    entry["body_bytes"] = len(req.post_data.encode("utf-8", errors="ignore"))
                    if "Resume" in (req.post_data[:200] if req.post_data else "") or "filename=" in (
                        req.post_data[:500] if req.post_data else ""
                    ):
                        upload_bytes["cv"] += entry["body_bytes"]
            except Exception:
                pass

        page.on("request", on_request)

        resp = await page.goto(URL, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(2500)
        result["load_status"] = resp.status if resp else None
        result["final_url_before"] = page.url
        await page.screenshot(path=str(EVID / "screenshots" / "02_before_fill.png"))

        if await turnstile_interactive(page):
            result["verdict"] = "ODOO_SA_REAL_APPLICATION_WAITING_FOR_TURNSTILE"
            result["message"] = "Interactive Turnstile/challenge before fill; human session required"
            await page.screenshot(path=str(EVID / "screenshots" / "02_turnstile_pause.png"))
            RESULT_PATH.write_text(json.dumps(result, indent=2))
            (EVID / "network" / "PERMITTED_NETWORK.json").write_text(
                json.dumps({"requests": network_log[-80:], "upload_bytes": upload_bytes}, indent=2)
            )
            await browser.close()
            return 2

        # Fill core fields
        await page.locator("input[name='partner_name']").fill(fill["full_name"])
        await page.locator("input[name='email_from']").fill(fill["email"])
        await page.locator("input[name='partner_phone']").fill(fill["phone"])
        # LinkedIn empty (resume path)
        if await page.locator("input[name='linkedin_profile']").count():
            await page.locator("input[name='linkedin_profile']").fill("")
        await page.locator("input[type='file'][name='Resume']").set_input_files(fill["cv_path"])
        await page.locator("textarea[name='short_introduction']").fill(intro)

        # Optional "I'm not EU citizen" checkbox unlocks passport number/copy uploads.
        # No authorized passport number/scan is available for this canary, so we leave the
        # optional checkbox unchecked (unchecked does NOT claim EU authorization).
        # Sponsorship need is stated truthfully in short_introduction instead.
        not_eu = await page.evaluate(
            """() => {
              const el = document.querySelector('input[name="not_eu_citizen"]');
              if (!el) return {present:false};
              const cs = getComputedStyle(el);
              const vis = cs.visibility !== 'hidden' && cs.display !== 'none' && !!(el.offsetParent || el.getClientRects().length);
              return {present:true, visible:vis, checked:!!el.checked, required:!!el.required};
            }"""
        )
        result["not_eu_citizen"] = not_eu
        result["not_eu_citizen_checked"] = False
        result["passport_handling"] = (
            "left_optional_not_eu_unchecked_no_passport_docs; "
            "sponsorship_disclosed_in_short_introduction"
        )

        passport_state = await page.evaluate(
            """() => {
              const num = document.querySelector('input[name="passport_number"]');
              const copy = document.querySelector('input[name="Passport copy"]');
              const vis = (e) => {
                if (!e) return false;
                const cs = getComputedStyle(e);
                return cs.visibility !== 'hidden' && cs.display !== 'none' && !!(e.offsetParent || e.getClientRects().length);
              };
              return {
                number_required: !!(num && num.required),
                number_visible: vis(num),
                copy_required: !!(copy && copy.required),
                copy_visible: vis(copy),
              };
            }"""
        )
        result["passport_state"] = passport_state
        if passport_state.get("number_visible") or passport_state.get("copy_visible"):
            result["verdict"] = "ODOO_SA_REAL_APPLICATION_BLOCKED_WITHOUT_SUBMISSION"
            result["message"] = (
                "Passport fields visible/required without authorized passport docs; "
                "submit not clicked."
            )
            await page.screenshot(path=str(EVID / "screenshots" / "03_blocked_passport.png"))
            RESULT_PATH.write_text(json.dumps(result, indent=2))
            (EVID / "network" / "PERMITTED_NETWORK.json").write_text(
                json.dumps({"requests": network_log[-80:], "upload_bytes": upload_bytes}, indent=2)
            )
            await browser.close()
            return 3

        # Consent: no optional marketing checkboxes observed; privacy link only.
        result["consents"] = {
            "required_privacy_processing": "implicit_website_form_no_checkbox",
            "optional_marketing_checked": False,
            "optional_marketing_present": False,
        }

        # Re-check Turnstile before submit
        if await turnstile_interactive(page):
            result["verdict"] = "ODOO_SA_REAL_APPLICATION_WAITING_FOR_TURNSTILE"
            result["message"] = "Interactive Turnstile before submit; human session required"
            await page.screenshot(path=str(EVID / "screenshots" / "03_turnstile_before_submit.png"))
            RESULT_PATH.write_text(json.dumps(result, indent=2))
            (EVID / "network" / "PERMITTED_NETWORK.json").write_text(
                json.dumps({"requests": network_log[-80:], "upload_bytes": upload_bytes}, indent=2)
            )
            await browser.close()
            return 2

        await page.screenshot(path=str(EVID / "screenshots" / "03_filled_before_submit.png"))

        # Click Apply/Submit exactly once
        btn = page.locator("#apply-btn")
        if await btn.count() == 0:
            btn = page.locator("a.s_website_form_send")
        if await btn.count() == 0:
            btn = page.get_by_role("link", name=re.compile(r"Send my application", re.I))
        if await btn.count() == 0:
            result["verdict"] = "ODOO_SA_REAL_APPLICATION_BLOCKED_WITHOUT_SUBMISSION"
            result["message"] = "Submit control not found"
            RESULT_PATH.write_text(json.dumps(result, indent=2))
            await browser.close()
            return 3

        result["submit_clicked"] = True
        result["submit_clicked_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        await btn.first.click(timeout=10000)
        result["external_side_effects"].append("clicked_send_my_application")

        # Wait for navigation / success / error / turnstile
        try:
            await page.wait_for_load_state("networkidle", timeout=45000)
        except Exception:
            pass
        await page.wait_for_timeout(3000)

        if await turnstile_interactive(page):
            result["verdict"] = "ODOO_SA_REAL_APPLICATION_WAITING_FOR_TURNSTILE"
            result["message"] = "Turnstile appeared after submit click; human completion required"
            result["final_url"] = page.url
            await page.screenshot(path=str(EVID / "screenshots" / "04_turnstile_after_click.png"))
            RESULT_PATH.write_text(json.dumps(result, indent=2))
            (EVID / "network" / "PERMITTED_NETWORK.json").write_text(
                json.dumps({"requests": network_log[-100:], "upload_bytes": upload_bytes}, indent=2)
            )
            await browser.close()
            return 2

        body = re.sub(r"\s+", " ", await page.inner_text("body"))
        final_url = page.url
        result["final_url"] = final_url
        result["body_excerpt"] = body[:1200]
        success = bool(
            re.search(
                r"thank you|application (has been )?sent|successfully submitted|we (have )?received your application|application received",
                body,
                re.I,
            )
        )
        error = bool(re.search(r"invalid|error|required field|please correct|failed", body, re.I))
        # Reference id heuristics
        ref = None
        m = re.search(r"(application|reference|ticket|request)\s*(id|#|number)?\s*[:#]?\s*([A-Za-z0-9\-]{5,})", body, re.I)
        if m:
            ref = m.group(0)[:120]
        result["application_reference"] = ref
        result["success_heuristic"] = success
        result["error_heuristic"] = error

        # Mask screenshot values before capture for evidence
        await page.evaluate(
            """() => {
              for (const sel of ['input[name="partner_name"]','input[name="email_from"]','input[name="partner_phone"]','textarea[name="short_introduction"]','input[name="passport_number"]']) {
                const el=document.querySelector(sel); if(el && 'value' in el) el.value='***MASKED***';
              }
            }"""
        )
        await page.screenshot(path=str(EVID / "screenshots" / "04_after_submit_masked.png"))

        posts = [n for n in network_log if n.get("method") in {"POST", "PUT", "PATCH"}]
        result["post_requests_sanitized"] = posts[-20:]
        result["upload_bytes"] = upload_bytes

        if success and not error:
            result["verdict"] = "ODOO_SA_REAL_APPLICATION_CANARY_SUBMITTED"
            result["message"] = "Positive confirmation text detected after single submit"
            result["external_side_effects"].append("application_form_post_likely_accepted")
            code = 0
        elif posts and not success and not error:
            result["verdict"] = "ODOO_SA_REAL_APPLICATION_SUBMISSION_UNKNOWN"
            result["message"] = "Submit clicked and network activity observed; no clear success/failure text"
            result["external_side_effects"].append("application_form_post_attempted_unclear_result")
            code = 4
        elif error and not success:
            result["verdict"] = "ODOO_SA_REAL_APPLICATION_SUBMISSION_UNKNOWN"
            result["message"] = "Submit clicked; error-like text present without clear acceptance"
            code = 4
        else:
            result["verdict"] = "ODOO_SA_REAL_APPLICATION_SUBMISSION_UNKNOWN"
            result["message"] = "Submit clicked; outcome unclear"
            code = 4

        RESULT_PATH.write_text(json.dumps(result, indent=2))
        (EVID / "network" / "PERMITTED_NETWORK.json").write_text(
            json.dumps({"requests": network_log[-120:], "upload_bytes": upload_bytes, "posts": posts[-20:]}, indent=2)
        )
        await browser.close()
        return code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
