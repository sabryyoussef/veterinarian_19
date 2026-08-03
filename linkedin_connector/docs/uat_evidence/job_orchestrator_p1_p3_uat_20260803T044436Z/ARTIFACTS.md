# Exact artifacts created (P1–P3 UAT)

## Git / project (`feature/personal-job-application-orchestrator`)
- `linkedin_connector/` models, controller, views, security, tests, docs/orchestrator/*
- `personal_job_apply_worker/` FastAPI+Playwright dry-run worker + fixtures + tests
- Evidence: `linkedin_connector/docs/uat_evidence/job_orchestrator_p1_p3_uat_20260803T044436Z/`

## Infra (outside module; not Production automation)
- `/home/sabry/infra/dify/apps/job-application-pack-generator/WORKFLOW_DRAFT.json`
- `/home/sabry/infra/dify/apps/job-application-pack-generator/fixture_*.json`
- `/home/sabry/infra/dify/apps/job-application-pack-generator/validate_pack.py`
- `/home/sabry/infra/n8n/workflows/personal_job_application_orchestrator_uat.json` (active=false)
- `/home/sabry/infra/n8n/tests/test_job_orchestrator_uat_contract.py`
- Symlink/target: `/home/sabry/infra/personal-job-apply-worker` → project worker

## Runtime (local UAT only)
- Odoo TEST module version **19.0.2.10.0**
- TEST ICP webhook secret configured (fingerprint only in evidence)
- UAT fictional profile/policy/job/application on account id=2
- uvicorn worker on `127.0.0.1:8095`
- Artifacts: `/home/sabry/private/job_apply_worker/artifacts/` (not in Git)

## Not created / not activated
- Published Dify app
- Active n8n workflow on the n8n instance (API key unavailable for auto-import)
- Production module upgrade
- Live Vivandi/BeBee draft
- LinkedIn browser session / real CV upload
