# Jooble key install + canary

**Verdict:** `JOOBLE_PRODUCTION_ENABLED`

- Key saved privately to `job_source_apis.env` / `jooble.env` (not printed)
- ICP TEST+PROD: `linkedin_connector.jooble_api_key` PRESENT
- Probe: HTTP 200 VALID
- TEST canary: imported 5, rejected 1, apps/applied unchanged, live_submit=False
- PROD canary: imported 5, rejected 1, apps/applied unchanged, live_submit=False
- PROD connector enabled with max_jobs_per_run=20
