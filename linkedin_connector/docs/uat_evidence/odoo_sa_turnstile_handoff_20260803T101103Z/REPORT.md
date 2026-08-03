# Odoo S.A. Real Application Canary — Final

**Verdict:** `ODOO_SA_REAL_APPLICATION_CANARY_SUBMITTED`

## Confirmation
- Observed UI: **Thank you for your application**
- Method: human local browser (laptop), Turnstile solved by human
- Screenshot: `screenshots/local_human_thank_you_20260803T1520.png`
- Record: `HUMAN_SUBMIT_RESULT.json` / `SUBMITTED_LOCAL_BROWSER_HUMAN.json`

## TEST records
- Job **40** · Application **32** → **`applied`**
- Attempt **5** → **`succeeded`**
- external_submissions: **1** (this canary only)

## Path taken
1. Selkies/Docker handoff → Turnstile **Verification failed** (`BLOCKED_TURNSTILE_ENVIRONMENT`)
2. Local browser → Turnstile solved → Send once → thank-you

## Controls restored / confirmed
- browser_submit_enabled=False · email_submit_enabled=False
- One-time submit token **consumed**
- n8n inactive · `:5801` closed · Production unchanged
