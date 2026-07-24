# Finalization Certificate — Project-Aware WhatsApp AI (Test)

**Date:** 2026-07-24  
**Branch:** `feature/wa-work-inbox`  
**DB:** `pet_spot_elsahel_test`  
**Production / OpenProject:** untouched

## Git

| Item | Value |
|------|--------|
| Commit (Odoo modules) | `51e400f` — `feat(devhub): add project-aware WhatsApp AI analysis` |
| Modules added | `devhub_work`, `devhub_whatsapp`, `devhub_analysis` |
| Docs commit | (see follow-up commit on same branch) |

## Modules (Test)

- `devhub_whatsapp` = **19.0.9.2.18**
- `devhub_work` = **19.0.9.1.4**

## Dify

- Canonical: `dee250c0-7f44-467c-9b0b-86f069bdc17e` (`enable_api=true`)
- Duplicate: `8dfa0b80-…` obsolete label, `enable_api=false`
- n8n uses canonical key only

## n8n

- ID `j3xV5kXRQUu1k0p4`, **active=true**, 1-min schedule
- Test Odoo via env; Dify via `DIFY_API_KEY_DEVHUB_WA_RESOLVER`
- No OpenProject; no Production URL hardcodes; no PostgreSQL nodes

## Fixture cleanup (Test)

| Before | After |
|--------|-------|
| 3 rows `provider=dify_n8n` + `provider_model=fixture`, `is_demo_result` null | Same 3 rows: `provider=fixture`, `provider_model=fixture`, `is_demo_result=true` |
| Live E2E rows 25/26/28 unchanged | Confirmed untouched |

Row 21 remains linked to WI 3341 (retained, labelled).

## Tests

- Tags: `/devhub_whatsapp`
- **31 passed / 0 failed / 0 errors** (~16s)
- Log: `finalization_tests_devhub_whatsapp.log`

## Browser UAT

Screenshots (blurred message bodies): `uat_screenshots_finalization/`

| Check | Result |
|-------|--------|
| Analysis 25 live | No DEMO badge; `provider=dify_n8n`; Dify/n8n IDs visible |
| Analysis 24 fixture | **DEMO / FIXTURE RESULT** banner; `provider=fixture`; `is_demo_result` checked |
| Sources 4 / 9 | unmapped / ambiguous visible |
| Work Item 3344 | `whatsapp_ai`, analysis 28, ASTA |

## Rollback

1. Deactivate n8n `j3xV5kXRQUu1k0p4`  
2. Disable `ai_triage_enabled` on sources  
3. Revert Git commit(s) if needed  
4. Never apply these steps to Production without a separate change request  
