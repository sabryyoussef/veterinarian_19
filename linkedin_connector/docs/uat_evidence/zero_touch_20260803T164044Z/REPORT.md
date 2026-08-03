# Zero-Touch Job Applications — Deploy Report

**Verdict:** `ZERO_TOUCH_READY_FOR_HUMAN_CHALLENGE`

**UTC stamp:** 2026-08-03T16:45:00Z (approx)

## Versions

| Component | Version |
|-----------|---------|
| `linkedin_connector` | **19.0.2.17.0** |
| `personal_job_apply-worker` | **0.3.0** |

## Branch / commits

- Branch: `feature/personal-job-application-orchestrator`
- Scoped commit: (see git log after push)

## Tests

| Suite | Result |
|-------|--------|
| Worker pytest | **38 passed**, 0 failed |
| Odoo `linkedin_connector` on TEST | **55 tests, 0 failed, 0 errors** |

## Backup

- Path: `/home/sabry/private/job_orchestrator/backups/pet_spot_elsahel_pre_zero_touch_20260803-164143.dump`
- SHA256: `349c78e19f2ccfdbb2c88ac576c9342db7620c8f96e5a4fc3ee013d3b0de448d`
- Restore validation: `pg_restore -l` TOC readable (32445 entries)

## Generic adapter supported controls

- text / email / tel / number / date
- textarea
- select / multi-select
- radio groups / checkboxes
- file (verified CV)
- multi-step fixtures (`generic_multistep.html`)
- unknown mandatory → `missing_fact` (fail closed)
- CAPTCHA fixture: fill then pause → `human_required` (no bypass)

## Production job reclassification (account id=2)

| Class | Count |
|-------|------:|
| human_required (CAPTCHA/Turnstile) | 12 |
| unsupported_ats (Indeed/BeBee/etc.) | 12 |
| ineligible | 17 |
| safe_canary_candidate | **0** |

- Browser-ready (CAPTCHA-free safe canary): **0**
- Human-challenge ready: **12** (handoff prepared for Softhealer Odoo Functional Consultant UK, app id=2 / job id=38)
- Email-eligible (explicit official apply email detected): **0** in current inventory
- Remaining unsupported: **12**

## Canary

- No CAPTCHA-free browser form or official apply-email listing available.
- Kill switch **ON**; `browser_submit_enabled=false`; `email_submit_enabled=false`; `min_score=0`.
- First human-challenge handoff prepared for application **id=2** (job 38 Softhealer).
- User action: **Open Human Challenge** → solve CAPTCHA/OTP only → worker auto-resumes submit once when token + evidence gates pass.
- `applied` will be set only after verified thank-you/receipt evidence (never on fill/click alone).

## Preserved applied

- Odoo S.A. application (id=1) — preserved, not resubmitted
- Softhealer prior applied (id=4) — preserved historical; new transitions require evidence

## Isolation

- Company account id=1 applications: **0**
- Answer library / applications scoped to account id=2 only

## Security / rollback

- Kill switch remains enabled during/after deploy
- No CAPTCHA-solving services
- Challenge tokens: 0600 files under private token dir; tokens redacted from evidence
- Rollback: restore dump above; module downgrade not required if kill switch stays on

## Evidence path (redacted)

`linkedin_connector/docs/uat_evidence/zero_touch_20260803T164044Z/`
