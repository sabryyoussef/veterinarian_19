# Job Orchestrator P1–P3 UAT Foundation — Evidence Report

**Verdict:** `JOB_ORCHESTRATOR_P1_P3_UAT_READY_FOR_DRAFT_CANARY`  
**Branch:** `feature/personal-job-application-orchestrator`  
**Scope DB:** `pet_spot_elsahel_test` (:8028) only  
**Production:** untouched (`linkedin_connector` remains **19.0.2.9.1**, jobs=12, apps=0, cron 112/113 active)

## What was delivered

### P1 — Odoo TEST foundation (`linkedin_connector` **19.0.2.10.0**)
- Models: `linkedin.candidate.profile`, `linkedin.apply.policy`, `linkedin.apply.attempt`
- Platform classification on `linkedin.job.apply_platform`
- Application pack / exception / n8n+Dify correlation fields
- Signed HTTP API under `/linkedin/orchestrator/v1/*` (HMAC; no PostgreSQL for n8n)
- Account isolation: personal only; company id=1 rejected
- Policy defaults: kill_switch=True; all submit flags False; caps 2/day, 20/month, 14-day cooldown
- Unit tests: **0 failed, 0 error(s) of 8** (`TestJobOrchestratorP1`)

### P2 — Dify + n8n (draft / inactive)
- Dify draft artifact: `/home/sabry/infra/dify/apps/job-application-pack-generator/` (UNPUBLISHED JSON + fixtures + fail-closed validator)
- Fixture validator: 3/3 PASS (including invented-facts fail-closed)
- n8n export: `Personal Job Application Orchestrator — UAT` with **`active: false`**
- n8n contract test: PASS
- Live Dify Studio app / live n8n import: **not auto-published**; import manually for next draft canary. MCP cannot create/publish Dify apps or import n8n workflows.

### P3 — Browser worker (offline dry-run)
- Service: `personal_job_apply_worker` (uvicorn :8095 for UAT)
- `/v1/apply/submit` → **403** always
- LinkedIn URLs → `linkedin_blocked`
- Offline fixtures: BeBee, Greenhouse, unknown question, CAPTCHA, OTP
- Artifacts dir: `/home/sabry/private/job_apply_worker/artifacts/` (0700), outside Git
- Pytest: **18 passed**

## E2E TEST chain (manual UAT simulation)

Odoo TEST → (fixture pack simulating Dify) → worker dry-run → Odoo attempt

| Step | Result |
| --- | --- |
| Bad HMAC | 401 `bad_signature` |
| GET application 30 (account 2) | 200; sensitive fields omitted |
| POST pack | 200 → `pack_ready` |
| invented_facts | 422 |
| Worker bebee/greenhouse | `drafted` |
| unknown/captcha/otp | stopped with correct stop_reason |
| LinkedIn URL | `linkedin_blocked` |
| Submit | 403 |
| Attempt write + idempotent replay | 200 / `idempotent:true` |
| Live `submitted` state | 403 `live_submit_disabled` |

Confirmed on TEST: `apps_account1=0`, attempt dry_run=true.

## Production safety checks (after TEST upgrade)

| Check | Result |
| --- | --- |
| Module version | 19.0.2.9.1 (not upgraded) |
| Jobs / applications | 12 / 0 |
| Cron 112 Daily Digest | active=true |
| Cron 113 Daily JSearch | active=true |
| Orchestrator tables on Production | absent |
| Outbound email/WhatsApp in this phase | none |
| External CV upload / live form submit | none |

## Explicit non-actions (honored)

- Dify workflow not published
- n8n workflow not activated
- `browser_submit_enabled` / `email_submit_enabled` remain False
- No LinkedIn browser automation
- Vivandi/BeBee **live** draft not run
- Production data/crons unchanged

## Gaps for next draft canary (not blockers for this verdict)

1. Import Dify draft into Studio as unpublished app; store scoped API key in n8n credentials vault only.
2. Import n8n workflow as **inactive**; wire TEST secret + worker URL; run one controlled manual execution.
3. Optional: dockerize worker via `personal_job_apply_worker/docker-compose.yml` instead of uvicorn.

## Artifact index

Directory: `linkedin_connector/docs/uat_evidence/job_orchestrator_p1_p3_uat_20260803T044436Z/`

See `ARTIFACTS.md`, `SECURITY.md`, `ROLLBACK.md`, `ARCHITECTURE.md`, `TEST_RESULTS.txt`, `E2E_ORCHESTRATOR.json`, `openapi.yaml`, `worker_openapi.json`, `screenshots/` (fictional BeBee-like fixture only).
