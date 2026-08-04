# Job Source Discovery — Production Activation Report

**Stamp:** `20260804T043501Z`  
**Branch:** `feature/job-source-expansion`  
**HEAD (pre-evidence commit):** `e681765d991f`  
**Module:** `linkedin_connector` **19.0.2.20.0**

## Executive verdict

```text
JOB_SOURCE_DISCOVERY_ACTIVE_WITH_CREDENTIAL_BLOCKERS
```

Daily discovery pipeline is active for approved public feeds and verified ATS boards. Automatic job **submission remains disabled**. Jooble and Adzuna remain blocked for missing credentials. JSearch RapidAPI key is present and validated, but the connector canary timed out and was left disabled.

## Backup

| Item | Value |
|------|-------|
| Path | `/home/sabry/private/job_orchestrator/backups/pet_spot_elsahel_pre_job_source_activation_20260804T042544Z.dump` |
| SHA256 | `f06e8a4c3c56e397b3b57e2589497b483b105a3bfa5fbbdb5427bae65b5c9dde` |

## Credential status

| Source | Status | Notes |
|--------|--------|-------|
| JSearch / RapidAPI | **VALID** (env `LINKEDIN_JSEARCH_RAPIDAPI_KEY`) | ICP empty by design; HTTP 200 on `/search-v2`; connector canary read-timeout → left disabled |
| Jooble | **MISSING** / `BLOCKED_CREDENTIALS` | ICP empty; no private secret file |
| Adzuna app id/key | **MISSING** / `BLOCKED_CREDENTIALS` | ICP empty; no private secret file |

## ATS boards

- Verified live: **Lever `iCodde`** (HTTP 200, 27 postings)
- Disabled stale 404 probes: Camptocamp Lever/Greenhouse, Odoo PS Greenhouse, Ashby `odoo`, Softhealer Workable, historical Greenhouse probes (Acorel/Therp/Vauxoo/Dynapps/ERPIFY)
- Kept empty-but-reachable Workable: `openeducat`, `open-source-integrators` (HTTP 200, 0 jobs)
- No new random tech companies added

## Connectors enabled (PROD)

`arbeitnow`, `remotive`, `remoteok`, `lever`, `workable`

## Connectors disabled (and why)

| Code | Reason |
|------|--------|
| jooble, adzuna | BLOCKED_CREDENTIALS |
| jsearch | Credential VALID but canary adapter timeout |
| greenhouse, ashby, smartrecruiters | No enabled live boards with jobs / empty after stale disable |
| recruitee | Adapter HTTP 404 on board token |
| linkedin/indeed restricted | REJECTED_AUTOMATION |
| regional manuals + email_alert | Policy / untested |

## Scheduler / digest / cleanup

| Cron | State |
|------|-------|
| Job Source Connector Scheduler | **ACTIVE** every 15 minutes |
| Daily Job Digest | ACTIVE (pre-existing) |
| Raw Payload Cleanup | **ACTIVE** (activated this run) |
| Daily JSearch (legacy) | ACTIVE pre-existing; separate from disabled connector |

Cairo-oriented `next_run_at` windows set on enabled connectors (07:45–12:15 local mapping via Africa/Cairo).

## Canary results (max_jobs_per_run=5)

| Source | Result |
|--------|--------|
| arbeitnow | imported 1, dup 0, rejected 0, qualified 0 |
| remotive | imported 0 |
| lever | imported 0, **duplicates 5** (dedupe OK vs prior canary) |
| greenhouse | imported 0 |
| ashby | imported 0 |
| jsearch | adapter timeout |
| jooble/adzuna | BLOCKED_CREDENTIALS |
| workable | imported 0 |
| smartrecruiters | imported 0 |
| recruitee | adapter 404 |
| remoteok | imported 0 |

## Counts

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Jobs | 131 | 132 | 1 |
| Applications | 15 | 15 | 0 |
| Applied applications | 10 | 10 | 0 |
| live_submit_enabled | False | False | 0 |

Lifecycle after: discovered=126, needs_review=1, duplicate=5, high_priority=0, qualified=0

## Tests

TEST DB `pet_spot_elsahel_test`: **0 failed, 0 error(s) of 62 tests** (`--test-tags=/linkedin_connector`).

## Security

- No LinkedIn/Indeed scrape
- No live submit / no applications created / applied unchanged
- Secrets not written to Git or evidence (env key redacted)
- Unrelated PetSpot business data untouched
- Personal job records remain on existing personal account path

## Rollback

1. Disable all `linkedin.job.source.connector` where `environment=prod` (`enabled=False`)
2. Deactivate crons `ir_cron_job_source_scheduler` (id 123) and `ir_cron_job_raw_payload_cleanup` (id 124)
3. Preserve imported jobs for audit
4. Restore dump only if migration/data corruption: `f06e8a4c3c56e397b3b57e2589497b483b105a3bfa5fbbdb5427bae65b5c9dde`

## Remaining blockers

1. Provide Jooble API key → ICP `linkedin_connector.jooble_api_key`
2. Provide Adzuna app id/key → ICP params
3. Re-canary JSearch connector after RapidAPI latency stabilizes (key already VALID)
4. Discover additional verified Odoo-partner ATS board tokens beyond Lever `iCodde`

## Evidence path

`linkedin_connector/docs/uat_evidence/job_source_activation_20260804T043501Z/`
