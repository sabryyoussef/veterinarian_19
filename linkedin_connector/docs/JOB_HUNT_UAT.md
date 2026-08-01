# LinkedIn Job Hunt — UAT checklist

**Module version:** 19.0.2.8.0  
**Gate:** No production deploy and no live LinkedIn publish/search until this UAT evidence is approved.

Defaults that protect you:

| Control | Default |
|--------|---------|
| `linkedin_connector.live_job_search_enabled` | `False` |
| Cron `LinkedIn: Daily Job Digest` | **inactive** |
| Easy Apply automation | **not implemented** |
| Open apply URL | only when application state = `approved` |

---

## UAT scenarios

### 1. Account isolation

1. Create/upgrade module; confirm PetSpot account has `account_type=company` (org ID set).  
2. Create personal account (`account_type=personal`, profile URL set, no org ID).  
3. Attempt to set Company page ID on personal → **ValidationError**.  
4. Attempt tips schedule on company account → **UserError**.  
5. Attempt `content_purpose=job_branding` post on company → **ValidationError**.  
6. Attempt `content_purpose=company_marketing` on personal → **ValidationError**.

**Evidence:** screenshot or test log `test_account_isolation`.

### 2. Personal OAuth status

1. Open personal account → **Verify personal connection**.  
2. Record result: connected YES/NO + member URN.  
3. If NO: document Connect steps (scopes `openid profile w_member_social` only).

**Evidence:** notification text / screenshot. Do **not** assume connected.

### 3. Job scoring + dedupe (offline)

1. Keep live search **OFF**.  
2. Create sample `linkedin.job` records via unit tests / shell (no LinkedIn HTTP).  
3. Confirm senior Odoo roles score ≥ 50; junior/unrelated score low.  
4. Confirm duplicate fingerprint marks secondary as `is_duplicate`.  
5. Confirm applications created only above threshold in `discovered`.

**Evidence:** `test_job_scoring_dedupe` output.

### 4. Application approval gate

1. Application in `discovered` → Prepare pack → `pack_ready`.  
2. **Open application** before approve → **UserError**.  
3. Approve (Job Hunt Manager) → `approved`.  
4. Open application → browser URL action allowed (manual submit only).  
5. Mark applied → `applied`.

**Evidence:** `test_application_approval_gate` + optional UI screenshots.

### 5. Personal posts scheduled without live publish

1. Disable publish cron **or** leave personal account disconnected.  
2. Schedule ≤ 3 personal posts (`job_branding`) as `scheduled`.  
3. Confirm no posts reach LinkedIn during UAT.  
4. Confirm company opening content cannot be scheduled on personal account.

**Evidence:** list of scheduled post IDs + cron inactive / disconnected state.

### 6. Profile recommendations

1. Review [`PERSONAL_PROFILE_RECOMMENDATIONS.md`](PERSONAL_PROFILE_RECOMMENDATIONS.md).  
2. Approve copy before editing LinkedIn manually.  
3. Confirm Odoo did not change LinkedIn profile fields.

### 7. Digest safety

1. Run `_cron_daily_job_digest()` with live flag False → logs skip, no HTTP.  
2. Confirm digest cron remains inactive until post-UAT approval.

---

## Automated tests to run

```bash
# From Odoo addons path / project venv — adjust conf/db for a NON-PROD database
./odoo-bin -c <conf> -d <uat_db> -i linkedin_connector --stop-after-init
./odoo-bin -c <conf> -d <uat_db> -u linkedin_connector --stop-after-init
./odoo-bin -c <conf> -d <uat_db> --test-enable --stop-after-init -u linkedin_connector \
  --test-tags /linkedin_connector
```

---

## Sign-off

| Item | Status | Notes |
|------|--------|-------|
| Isolation tests pass | | |
| Personal connect verified | | |
| Scoring/dedupe tests pass | | |
| Approval gate tests pass | | |
| No live LinkedIn actions during UAT | | |
| Profile copy reviewed | | |
| Live search left OFF | | |

**Approver:** _________________ **Date:** _________________

Only after sign-off: enable digest cron + `live_job_search_enabled`, connect personal account for publishing, and schedule real posts.
