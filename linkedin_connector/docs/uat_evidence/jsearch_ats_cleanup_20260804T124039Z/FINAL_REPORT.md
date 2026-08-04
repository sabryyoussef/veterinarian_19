# JSearch enable + ATS cleanup

**Verdict:** `JSEARCH_ENABLED_ATS_BOARDS_STILL_BLOCKED`

## Backup
`/home/sabry/private/job_orchestrator/backups/pet_spot_elsahel_pre_jsearch_ats_20260804T123809Z.dump`

## JSearch
- Root cause of prior failures: adapter HTTP timeout 25s; RapidAPI often slower
- Code fix: `safe_get(..., timeout=60)` in jsearch adapter
- PROD canary: HTTP 200, apps/applied delta 0, live_submit=False
- Connector **enabled** (max 5/run, daily_request_limit 4, countries ae,sa,eg,de,be,nl,gb)
- User systemd service restarted; process env key PRESENT

## Greenhouse / Ashby
- Broad token probe + career-page harvest: **0** verified live Odoo-relevant boards
- Connectors left **disabled** with notes; stale board tokens remain disabled
- Lever `iCodde` remains the verified public ATS board

## Safety
- live_submit=False
- No LinkedIn/Indeed automation
