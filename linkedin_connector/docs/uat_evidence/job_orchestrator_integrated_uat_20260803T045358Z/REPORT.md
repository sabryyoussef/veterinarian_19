# Job Orchestrator Integrated UAT Canary — Evidence

**Verdict:** `JOB_ORCHESTRATOR_INTEGRATED_UAT_READY_FOR_LIVE_DRAFT_CANARY`

## Correlation (four layers)

| Layer | ID |
| --- | --- |
| Idempotency / correlation | `uat-integrated-20260803-bebee-01` |
| Odoo TEST application | `30` (state=pack_ready) |
| Odoo TEST attempt | `3` (state=drafted, dry_run=true) |
| Dify workflow run | `6e0a1926-c02e-4240-99f8-83f0a6383833` |
| Dify app | `61cb1d22-b6e9-4bde-ac3e-9190d5beeaab` (Job Application Pack Generator — UAT, published) |
| n8n workflow | `cITBnJ6mNZn2srQY` (**inactive**) |
| n8n execution | `125613` |
| Browser worker attempt | `ae1a143b-b094-4f7d-b89e-c3ee68a8f7d2` |

## Flow proven
Odoo TEST → n8n (CLI one-off execute of inactive WF) → Dify UAT Workflow API → personal-job-apply-worker dry-run → Odoo attempt

## Controls
- Idempotency replay: attempt_id=3, `idempotent=true`, idem_count=1
- Submit endpoint: 403 submit_disabled
- LinkedIn URL: linkedin_blocked
- browser_submit_enabled=false, email_submit_enabled=false, kill_switch=true
- Company account apps=0
- n8n workflow remains inactive
- Dify UAT app remains published with scoped key in n8n/.env vault only (not printed)

## Production before/after
### Before
```
ver=19.0.2.9.1
jobs=12
apps=0
c112=true|last=2026-08-03 03:55:30
c113=true|last=2026-08-03 03:52:12
```
### After
```
ver=19.0.2.9.1
jobs=12
apps=0
c112=true|last=2026-08-03 03:55:30
c113=true|last=2026-08-03 03:52:12
```
Unchanged: version 19.0.2.9.1, jobs=12, apps=0, crons 112/113 active with same lastcall.

## Artifacts
- Dify DSL: `/home/sabry/infra/dify/apps/job-application-pack-generator/job-application-pack-generator-uat.dify.yml`
- n8n export: `/home/sabry/infra/n8n/workflows/personal_job_application_orchestrator_uat.json`
- Worker container: `uat-job-worker` on n8n-net
- Secrets: `/home/sabry/private/job_orchestrator/` (0600/0700)
- Screenshots: `screenshots/` (fictional BeBee fixture)

## Notes
- Host docker→bridge TCP to :8028/:8095 is firewalled; Odoo used `https://test.drpaws.ai`; worker ran on n8n-net.
- n8n UI Execute API unavailable; controlled run used one-off `n8n execute` container sharing workflow DB (workflow left inactive).
- NODE_FUNCTION_ALLOW_BUILTIN=crypto added for HMAC Code nodes.
