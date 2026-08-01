# Dormant Production Deployment — linkedin_connector 19.0.2.8.0

**Approval:** `APPROVED_DORMANT_PRODUCTION_DEPLOYMENT_ONLY`  
**Stamp:** `20260801T222810Z`  
**Verdict:** `DORMANT_PRODUCTION_DEPLOYMENT_READY_FOR_PERSONAL_ACCOUNT_SETUP`

## Scope held

| Action | Status |
| --- | --- |
| Publish / live LinkedIn search / open-submit applications | **Not done** |
| OAuth connect / LinkedIn CV upload | **Not done** |
| Copy TEST account/attachment IDs into Production | **Not done** |
| Production CV attach / job digest activation / personal publishing | **Deferred** (separate approvals) |

## 1) CV attachment verification (TEST only)

| Check | Result |
| --- | --- |
| Attachment | TEST `ir.attachment` **id=19203** readable PDF |
| Size | 76123 bytes |
| SHA-256 | `29e968d70baf80e04607dcc526d23b776796245cd4ac5c56a0301ebbd7d6f539` |
| Match approved file | **Yes** |
| Production CV attach | **Not performed** (0 `linkedin.cv.version` rows on Production) |

## 2) PDF removed from repository

| Item | Value |
| --- | --- |
| Former path | `docs/Sabry_Youssef_CV.pdf` (gitignored; never tracked) |
| Private path | `/home/sabry/private/linkedin_cv/Sabry_Youssef_CV.pdf` (dir `0700`, file `0600`) |
| SHA after move | matches approved hash |
| Repo path after move | **absent** |

## 3) Branch / commit / push

| Item | Value |
| --- | --- |
| Branch | `feature/petspot-vendor-sell-through` |
| Commit | `16836d4` — *Add personal LinkedIn job-hunt UAT path with CV isolation.* |
| Remote | `origin` (`github.com:sabryyoussef/veterinarian_19.git`) |
| Push | `1999e63..16836d4` → `origin/feature/petspot-vendor-sell-through` |

## 4) Verified Production backup

| Item | Value |
| --- | --- |
| Path | `/home/sabry/infra/ops/backups/postgres/pet_spot_elsahel_pre_linkedin_dormant_20260801T222810Z/pet_spot_elsahel.dump` |
| Format | `pg_dump -Fc` |
| Size | 78041515 bytes |
| SHA-256 | `a7a6d6eee2177cf19fffba72cb176126e10e0364dca25621021f28ac444f448f` |
| `pg_restore -l` TOC lines | 31876 |
| Pre-backup HTTP | `200` on `:8027/web/login` |
| Module before | `linkedin_connector\|19.0.2.7.0\|installed` |

Dump kept **outside** the git tree (contains secrets).

## 5) Upgrade

| Item | Value |
| --- | --- |
| Command | `odoo-bin -c pet_spot_elsahel.conf -d pet_spot_elsahel -u linkedin_connector --stop-after-init --http-port=42373` |
| Exit | **0** |
| Module after | `linkedin_connector\|19.0.2.8.0\|installed` |
| Migrations | pre-migrate `>19.0.2.8.0` + post-migrate `19.0.2.8.0>` ran |
| Log | `upgrade_linkedin_connector.log` (this directory) |

**Ops note:** Before deploy, systemd unit was crash-looping (`Address already in use`) while an orphan Odoo master (pid 194910) still served `:8027`. Unit was stopped, orphan stopped for upgrade, then unit restarted cleanly (`active`, HTTP 200).

## 6) Cron + live search gates

| Gate | Result |
| --- | --- |
| LinkedIn: Publish Scheduled Posts | **inactive** |
| LinkedIn: Refresh Feed | **inactive** |
| LinkedIn: Sync Messages | **inactive** |
| LinkedIn: Daily Job Digest | **inactive** (created by upgrade; never lastcall) |
| `linkedin_connector.live_job_search_enabled` | **False** |

## 7) Account migration results (Production IDs — not copied from TEST)

| Prod ID | Name | `account_type` | Org ID | Notes |
| --- | --- | --- | --- | --- |
| 1 | PetSpot LinkedIn | **company** | `129944345` | Correct PetSpot company classification; no member/token; `fallback_personal_post=false` |
| 2 | PetSpot LinkedIn (Test) | **personal** | (empty) | Classified personal because org ID empty + existing member URN/token; profile URL left empty; fallback forced false. **Not** activated for job hunt / publishing. Rename/cleanup needs separate approval. |

Isolation smoke: creating `job_branding` on company account **id=1** is blocked.

Historical posts: 10 rows, all on personal account with `content_purpose=job_branding` (pre-existing content reclassified by purpose backfill). No new posts written in the upgrade window.

## 8) Tests / smoke

| Check | Result |
| --- | --- |
| TEST suite (pre-deploy) | 17/17 (`test_run_20260802_personal_uat_b.log`) |
| Production ORM smoke | `SMOKE_OK` (`prod_orm_smoke.txt`) — module 19.0.2.8.0, live=False, company isolation blocked, digest gated |
| Production HTTP | local `:8027` **200**; `https://drpaws.ai/web/login` **200** |
| Service | `pet_spot_elsahel.service` **active** |

## 9) Side-effect proof

| Check | Result |
| --- | --- |
| Jobs created last 2h | **0** |
| Applications created last 2h | **0** |
| Post writes last 2h | **0** |
| CV versions on Production | **0** |
| Job digest `lastcall` | **null** |
| LinkedIn API publish/search/apply/OAuth/CV upload | **none** |

## 10) Rollback

1. `systemctl --user stop pet_spot_elsahel.service`
2. Restore DB from  
   `/home/sabry/infra/ops/backups/postgres/pet_spot_elsahel_pre_linkedin_dormant_20260801T222810Z/pet_spot_elsahel.dump`  
   (verify SHA-256 first).
3. Optionally check out pre-`16836d4` module code if code rollback required.
4. `systemctl --user start pet_spot_elsahel.service`
5. Confirm module version `19.0.2.7.0` and HTTP 200.

## Stop line

**`DORMANT_PRODUCTION_DEPLOYMENT_READY_FOR_PERSONAL_ACCOUNT_SETUP`**

Next steps require **separate** approvals:

- Personal OAuth setup / account rename cleanup on Production
- Production CV attachment
- Job digest activation
- Personal publishing
