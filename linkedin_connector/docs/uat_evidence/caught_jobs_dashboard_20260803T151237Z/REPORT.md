# Live Caught Jobs Odoo Dashboard

**Verdict:** `LIVE_CAUGHT_JOBS_ODOO_DASHBOARD_DEPLOYED`

## Deploy
- Module `19.0.2.15.0` on TEST and Production
- Menu: LinkedIn → Reporting → Caught Jobs Dashboard
- OWL client action `linkedin_caught_jobs_dashboard` (authenticated ORM only; no public route)
- Read-only: open/refresh perform zero writes

## Tests
- 0 failed, 0 errors (47 reported / 57 module stats)

## Backup
- `/home/sabry/private/job_orchestrator/backups/pet_spot_elsahel_pre_caught_jobs_dash_20260803T151237Z.dump`
- size=79124740 sha256=`8ead2de54f20213520efbd7d1f5aa4206b9d934f941e29784cef877bd4501574` TOC=32449

## Production KPIs (All Time)
{
  "total_jobs": 41,
  "new_jobs": 41,
  "eligible": 6,
  "safe_canary": 0,
  "human_required": 0,
  "ineligible": 38,
  "unsupported_ats": 3,
  "applied": 1,
  "submission_unknown": 0,
  "average_score": 32.4,
  "ats_sources_checked": 9,
  "last_discovery_run": "2026-08-03 14:47:58",
  "next_discovery_run": "2026-08-03 20:47:58",
  "last_discovery_run_display": "2026-08-03 14:47 UTC",
  "next_discovery_run_display": "2026-08-03 20:47 UTC",
  "company_account_apps": 0
}

## Gates unchanged
- kill_switch=True · live_submit=False · browser/email submit off
- n8n hunter active · submit WF inactive · worker submit_enabled=false
- account id=1 apps: 0 → 0

## Screenshots
/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/linkedin_connector/docs/uat_evidence/caught_jobs_dashboard_20260803T151237Z/uat
