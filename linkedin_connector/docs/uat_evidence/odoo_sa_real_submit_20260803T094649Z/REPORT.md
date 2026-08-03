# Odoo S.A. Real Application Canary

**Stamp:** `20260803T094649Z`  
**Verdict:** `ODOO_SA_REAL_APPLICATION_WAITING_FOR_TURNSTILE`

## Why paused

The live apply control `#apply-btn` ("Send my application") resolved but remained **disabled** with Cloudflare classes `disabled cf_form_disabled`. Automated click could not proceed without solving Turnstile. **No Apply/Submit was completed.** No confirmation of an external application receipt.

Per authorization: do **not** bypass Turnstile; pause for Sabry human solve.

## Pre-submit gates (completed)

| Gate | Result |
|------|--------|
| Listing active/unchanged | Yes — Software Developer apply URL HTTP 200 |
| Prior successful submit for job 40 | **0** |
| Profile visa facts | `visa_sponsorship=required`, EU/Belgium auth=false |
| Dify | run `d5f721fe-14af-4528-8277-5951e5276f4f` → **shortlist**, no invented facts |
| Salary on form | Not present — not included |
| LinkedIn field | Left empty (Resume path) |
| Optional marketing consents | None present / none checked |
| Optional `I'm not EU citizen` | Left **unchecked** (avoids passport number/copy requirement with no authorized passport docs). Sponsorship disclosed in short introduction instead |

## Exact short introduction (as prepared for submit)

```
Senior Odoo developer with 8+ years of experience (Python, PostgreSQL, Odoo). Available for on-site work in Belgium after a 1-month notice period and ready to relocate. I do not currently hold EU/Belgium work authorization and require visa/work-permit sponsorship.
```

## External side effects so far

1. Loaded `https://www.odoo.com/jobs/apply/software-developer-1`
2. Filled local browser form fields (name/email/phone/CV/intro) in automation context
3. **Did not** successfully click Send my application (button Cloudflare-disabled)
4. **No** confirmed application POST acceptance / reference ID

## TEST state

| Record | State |
|--------|--------|
| Application 32 | `pack_ready` + `exception_reason=waiting_for_turnstile_human` |
| Attempt 5 | `stopped` / `captcha` |
| Policy | `kill_switch=True`, `browser_submit_enabled=False`, `email_submit_enabled=False` |
| n8n WF `cITBnJ6mNZn2srQY` | **inactive** |
| One-time token | Re-armed for **human Turnstile resume only** (no prior successful external submission) |

## Production

Unchanged: `19.0.2.9.1`, jobs=12, apps=0, crons 112/113 identical before/after.

## Human resume (required)

1. Headed Chromium/noVNC on master (no CAPTCHA-solving services).
2. Open the apply URL; solve Turnstile manually until `#apply-btn` enables.
3. Confirm approved values (Resume path, intro above, LinkedIn empty, no salary).
4. Click **Send my application** once.
5. Capture success/unknown evidence; restore kill switch / submit flags; consume token.

Artifacts: `SUBMIT_RESULT.json`, `DIFY_PACK.json`, `SHORT_INTRODUCTION.txt`, `POLICY_RESTORED.json`, screenshots under `screenshots/`.
