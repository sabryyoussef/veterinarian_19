# Rollback

1. SQL or UI: set all prod `linkedin.job.source.connector.enabled=false`
2. Deactivate cron ids 123 (scheduler) and 124 (cleanup)
3. Verify `linkedin_connector.live_submit_enabled=False`
4. Verify application/applied counts unchanged
5. Optional restore: `/home/sabry/private/job_orchestrator/backups/pet_spot_elsahel_pre_job_source_activation_20260804T042544Z.dump`
