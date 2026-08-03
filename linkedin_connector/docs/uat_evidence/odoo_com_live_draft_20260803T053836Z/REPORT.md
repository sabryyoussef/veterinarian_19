# Odoo.com Live Draft-Only Canary

**Stamp:** `20260803T053836Z`  
**Verdict:** `ODOO_COM_LIVE_DRAFT_READY_FOR_SUBMIT_APPROVAL`

## Correlation

| Layer | ID |
| --- | --- |
| Idempotency / correlation | `uat-odoo-com-live-draft-20260803` |
| Odoo TEST job | `40` |
| Odoo TEST application | `32` (`pack_ready`, notes `live_draft_state=draft_ready`) |
| Odoo TEST attempt | `5` (`drafted`, dry_run=true) |
| Dify workflow run (direct validation) | `9b89b007-a5ed-42e3-aed7-ce5f20685346` |
| Dify run (via n8n) | `0c1b512b-5979-4cc2-98c3-aaa48066e5e8` |
| n8n workflow | `cITBnJ6mNZn2srQY` (**inactive**) |
| n8n execution | `125827` |
| Live browser worker attempt | `979f0291-6de6-40a1-b502-fca5d5339e2d` |
| n8n fixture worker attempt (side dry-run) | `baf737ac-e8bf-4c6e-85cb-b1ac81c6442e` |

## Candidate

- Odoo S.A. — Software Developer (Belgium)
- URL: `https://www.odoo.com/jobs/apply/software-developer-1`
- Platform: `company_ats`
- Score: 65
- Resume path used (LinkedIn left empty)

## Dify validation

- `match_decision`: **shortlist**
- `visa_sponsorship` present in `missing_facts` (not inferred)
- `recommended_channel`: `browser_dry_run`
- No invented candidate facts

## Live draft preflight / containment

- Job active and unchanged (title Software Developer on odoo.com apply URL)
- Form action: `https://www.odoo.com/website/form/` POST `#hr_recruitment_form`
- Turnstile present; **no verify-human wall** before form access; **not solved / not interacted**
- Mutations blocked (POST/PUT/PATCH/DELETE/websocket aborted)
- Switched **offline** before real candidate values
- Fictional probe `UAT_PROBE_NOT_REAL` confirmed no successful mutation responses
- CV selected locally from verified TEST CV path; **`cv_bytes_transmitted=0`**
- Submit/Apply **not clicked**
- Worker submit endpoint still **403** on :8095 and :8096

## Field map (sanitized)

Required visible: `partner_name`, `email_from`, `partner_phone`  
Optional: `linkedin_profile` (left empty), `Resume` (file set locally), `short_introduction`  
Filled: name, email, phone, Resume, short_introduction; LinkedIn empty

## Final TEST controls

| Control | Value |
| --- | --- |
| application notes | `live_draft_state=draft_ready` |
| applications submitted | **0** |
| browser_submit_enabled | False |
| email_submit_enabled | False |
| kill_switch | True |
| n8n active | False |
| company account apps | 0 |

## Production before/after

Unchanged: module `19.0.2.9.1`, jobs=12, apps=0, crons 112/113 lastcall unchanged.

## Artifacts

- `WORKER_LIVE_DRAFT.json`, `FIELD_MAP.json`, `network/SANITIZED_NETWORK.json`
- `DIFY_PACK.json`, `n8n_execute_SANITIZED.json`, `TEST_FINAL_STATE.json`
- Screenshots: `screenshots/01_preflight_loaded.png`, `screenshots/worker_01_preflight_loaded.png`, `screenshots/worker_02_drafted_masked.png`

## Explicit non-actions

No login, no account creation, no CAPTCHA solve, no external CV upload, no email/WhatsApp/LinkedIn automation, no Production writes.
