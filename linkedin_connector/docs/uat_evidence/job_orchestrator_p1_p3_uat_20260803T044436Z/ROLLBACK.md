# Rollback — Job Orchestrator UAT foundation

## Immediate stop
1. Leave n8n workflow **inactive** (or delete import if present).
2. Do not publish Dify app; delete draft in Studio if needed.
3. Stop worker: `kill $(cat .../worker.pid)` or `docker compose down` in `personal_job_apply_worker/`.
4. On TEST only: set ICP `linkedin_connector.orchestrator_webhook_secret` to empty; keep policy kill_switch True.

## Code / module rollback (TEST)
```bash
systemctl --user stop pet_spot_elsahel_test.service
# restore TEST DB dump taken before upgrade, OR
# checkout previous linkedin_connector version and -u linkedin_connector on TEST only
systemctl --user start pet_spot_elsahel_test.service
```

## Production
No Production upgrade was performed for 19.0.2.10.0. No Production rollback required for this phase.

## Do not
- Force-push / destroy unrelated WIP on `feature/personal-job-application-orchestrator`
- Clear Production LinkedIn crons 112/113 as part of this rollback
