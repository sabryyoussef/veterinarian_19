# Job Source Expansion — Final Report

**Stamp:** `20260804T035419Z`  
**Branch:** `feature/job-source-expansion`  
**Module:** `linkedin_connector` **19.0.2.20.0**

## Executive verdict

```text
JOB_SOURCE_EXPANSION_COMPLETE_WITH_CREDENTIAL_BLOCKERS
```

All safe phases executed: TEST backup + upgrade + tests + canaries; PROD backup + upgrade + capped canaries with connectors left disabled. Live submission remained off. Jooble / Adzuna / JSearch RapidAPI live canaries blocked by missing credentials (code + seeds present).

## What was implemented

- Unified connector model `linkedin.job.source.connector` with scheduler, quotas, backoff, advisory lock
- Adapter package `services/job_sources/` (15 adapters + SSRF/sanitize/pipeline)
- Extended `linkedin.job` schema (lifecycle, remote/visa tri-state, salary, scores, fingerprints)
- Models: raw payload, source link, rejection, score rule, filter rule
- Configurable score/filter seed rules; deterministic dedupe; retention cleanup cron
- UI menus: Job Sources, Qualified, High Priority, Rejected, Duplicates, Connector Health, Rules
- Regional + LinkedIn/Indeed as MANUAL / REJECTED_AUTOMATION only
- Plan doc: `docs/JOB_SOURCE_EXPANSION_PLAN.md`

## What was reused

- `linkedin.job`, `linkedin.ats.source`, application FSM, apply attempts/policy, CV/profile
- Existing JSearch/Arbeitnow/Remotive code paths (thin connector wrappers)
- `ats_feeds` / `ats_preflight` / platform classifier
- HMAC orchestrator + `personal_job_apply_worker` (unchanged submit gates)
- Evidence-gated `applied` only

## Connectors

| Status | Sources |
|--------|---------|
| Completed (code+seeds) | JSearch, Jooble, Adzuna, Arbeitnow, Remotive, RemoteOK, Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, Manual, EmailAlert, Restricted |
| BLOCKED_CREDENTIALS | Jooble, Adzuna, JSearch (PROD RapidAPI key not in connector ICP path for canary) |
| Manual-only | Wuzzuf, Bayt, GulfTalent, Naukrigulf, Tanqeeb, Forasna, Email alert (disabled) |
| Rejected automation | LinkedIn, Indeed |

## TEST results

- Upgrade to `19.0.2.20.0` OK
- Odoo tests: `0 failed, 0 error(s)` of tagged job-hunt tests
- Offline pipeline smoke: junior reject; EU no-sponsor reject; techno-functional allowed; unknown visa not rejected
- Canary R1: Arbeitnow/Remotive imported (noise; fixed with Odoo filter + qualify threshold 40)
- Canary R2: Arbeitnow +1 filtered; Remotive 0; ATS board tokens mostly 404 (seed probes stale)
- Apps unchanged during canaries; `live_submit_enabled=False`

## Production deployment

- Backup: `pet_spot_elsahel_pre_job_source_20260804T035419Z.dump` SHA256 `36e8f788…`
- Upgrade OK → `19.0.2.20.0`
- 22 PROD connectors created, **all disabled** after canaries (`ENABLED_PROD=0`)
- Lever canary: +5 jobs; apps/applied unchanged; `live_submit=False`
- `live_job_search_enabled` remains True (pre-existing); new connector scheduler inactive (XML `active=False`) and connectors disabled

## Safety verification

- No LinkedIn/Indeed scrape
- Restricted connector auto-disables
- No unexpected applications / applied delta
- Secrets not in Git (empty ICP placeholders)
- Personal isolation preserved

## Backups

| DB | Path | SHA256 |
|----|------|--------|
| TEST | `/home/sabry/private/job_orchestrator/backups/pet_spot_elsahel_test_pre_job_source_20260804T035419Z.dump` | `55d516f8…` |
| PROD | `/home/sabry/private/job_orchestrator/backups/pet_spot_elsahel_pre_job_source_20260804T035419Z.dump` | `36e8f788…` |

## Rollback

1. Disable all `linkedin.job.source.connector` (`enabled=False`)
2. Keep crons inactive / leave scheduler inactive
3. Module downgrade to prior version if required + restore dump
4. Do not re-enable submit

## Follow-ups (non-critical)

1. Provide Jooble + Adzuna + RapidAPI credentials via private ICP/env
2. Refresh Greenhouse/Lever/Ashby board tokens (many seed probes 404)
3. Progressive enable: Arbeitnow → Remotive → ATS → Jooble/Adzuna (max 5 first)
4. Retune score rules on larger Odoo-only sample
5. Optional email-alert IMAP when mailbox workflow exists
6. Convert `_sql_constraints` to Odoo 19 `Constraint` API (warnings only)

## Evidence path

`linkedin_connector/docs/uat_evidence/job_source_expansion_20260804T035419Z/`
