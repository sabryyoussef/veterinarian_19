# Job Application Orchestrator — UAT Foundation (P1–P3)

## Scope completed in this branch

| Phase | Artifact |
| --- | --- |
| P1 | `linkedin_connector` **19.0.2.10.0** models + signed API |
| P2 | Dify draft JSON + inactive n8n workflow export |
| P3 | `personal_job_apply_worker` dry-run Docker/FastAPI service |

## Signed Odoo API (TEST :8028)

Secret ICP: `linkedin_connector.orchestrator_webhook_secret`  
Header: `X-Orchestrator-Timestamp` (unix) + `X-Orchestrator-Signature` = `sha256=HMAC(secret, "{ts}."+body)`

| Method | Path |
| --- | --- |
| GET | `/linkedin/orchestrator/v1/health` |
| GET | `/linkedin/orchestrator/v1/applications/{id}` |
| POST | `/linkedin/orchestrator/v1/applications/{id}/pack` |
| POST | `/linkedin/orchestrator/v1/applications/{id}/attempts` |

Company account / id=1 → 403. Live submit states → 403 while dry_run.

## Dify

- `/home/sabry/infra/dify/apps/job-application-pack-generator/WORKFLOW_DRAFT.json`
- Status: **DRAFT / DO NOT PUBLISH**
- Import manually into Studio; store app key only in n8n credentials vault.

## n8n

- `/home/sabry/infra/n8n/workflows/personal_job_application_orchestrator_uat.json`
- **active: false** — import as inactive; no WA/email nodes.

## Browser worker

- Project: `personal_job_apply_worker/`
- Infra: `/home/sabry/infra/personal-job-apply-worker`
- Artifacts: `/home/sabry/private/job_apply_worker/artifacts/` (0700)
- `/v1/apply/submit` always 403
- LinkedIn URLs rejected

## Production safety

Do **not** upgrade Production with orchestrator features until approved.  
UAT upgrade target: `pet_spot_elsahel_test` only.  
Production LinkedIn crons / jobs / applications must remain unchanged.

## Rollback

1. Keep n8n workflow inactive / delete import.
2. Leave Dify unpublished / delete draft app.
3. `docker compose down` worker.
4. On TEST: uninstall/upgrade back or restore TEST dump.
5. Never set `browser_submit_enabled` or clear kill_switch on Production without approval.
