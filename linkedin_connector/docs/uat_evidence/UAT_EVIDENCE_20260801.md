# UAT evidence — LinkedIn Job Hunt (19.0.2.8.0)

**Database:** `pet_spot_elsahel_test` (non-prod)  
**Date:** 2026-08-01  
**Live LinkedIn actions:** none  
**Production deploy:** not performed  

## Automated tests

Command:

```bash
odoo-bin -c config/projects/pet_spot_elsahel_test.conf -d pet_spot_elsahel_test \
  -u linkedin_connector --test-enable --stop-after-init --http-port=42363
```

Log: [`test_run_20260801d.log`](test_run_20260801d.log)

Result:

```
0 failed, 0 error(s) of 16 tests
```

Coverage includes: account isolation, scoring, dedupe, approval gate, tips personal-only, digest skip when live disabled.

## Safety gates (verified on test DB)

| Control | Value |
|--------|--------|
| `linkedin_connector.live_job_search_enabled` | `False` |
| Cron `LinkedIn: Daily Job Digest` | **inactive** |
| Module version | `19.0.2.8.0` |

## Account verification (do not assume personal is ready)

| id | name | account_type | connected | org_id | notes |
|----|------|--------------|-----------|--------|-------|
| 1 | PetSpot LinkedIn | company | NO | 129944345 | Correct company record; reconnect for company posts |
| 2 | PetSpot LinkedIn (Test) | personal | YES | (empty) | **Misnamed / needs review** — auto-classified personal because no org ID. Member URN present, but this is NOT confirmed as [sabry-youssef-56a878185](https://www.linkedin.com/in/sabry-youssef-56a878185/) |

### Required before live personal job hunt

1. Create a dedicated personal account named e.g. `Sabry Youssef (Personal)` with:
   - `account_type=personal`
   - `profile_url=https://www.linkedin.com/in/sabry-youssef-56a878185/`
   - scopes `openid profile w_member_social`
2. Connect while logged into that LinkedIn profile; use **Verify personal connection**.
3. Reclassify `PetSpot LinkedIn (Test)` as **company** (set org ID `129944345`) or archive it so it cannot receive job-branding posts.
4. Keep live job search OFF until you sign the UAT checklist in [`../JOB_HUNT_UAT.md`](../JOB_HUNT_UAT.md).

## Profile copy

Manual recommendations ready for approval: [`../PERSONAL_PROFILE_RECOMMENDATIONS.md`](../PERSONAL_PROFILE_RECOMMENDATIONS.md)

## Explicit non-actions

- No Easy Apply automation  
- No production module upgrade  
- No live job search cron enabled  
- No personal posts published to LinkedIn during UAT  
