# Production preflight — PetSpot SEO rollout (2026-07-24)

**Status:** CLEARED to deploy (Phase 1)  
**Backup dir:** `/home/sabry/odoo_base/base_odoo_19/backups/pet_spot_elsahel_seo_prod_20260724T153032Z`

## Confirmed Production target

| Item | Value |
|------|--------|
| Database | `pet_spot_elsahel` |
| Service | `pet_spot_elsahel.service` (active) |
| HTTP | `127.0.0.1:8027` · public `https://drpaws.ai` |
| Conf | `/home/sabry/odoo_base/base_odoo_19/config/projects/pet_spot_elsahel.conf` |
| Filestore | `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/.filestore` |
| Repository | `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel` |
| Branch | `feature/wa-work-inbox` |
| Commit | `4c1fc00555a3ede2ccf7582fdb87af6082a29195` |
| Disk free | ~247G |

**Note:** Deploy is **RPC website/content** to Production DB (validated Test baseline). Unrelated uncommitted Dev Hub changes on this branch are **not** module-upgraded to Production.

## Social Marketing account #16

| Field | Value |
|-------|--------|
| id | 16 |
| Handle | `animalcarecenterpetspots` |
| Media | facebook |
| Connected | yes (`is_media_disconnected=False`) |
| Active | yes |
| Other FB accounts | **none** (no duplicate will be created) |

Target Page URL: https://www.facebook.com/animalcarecenterpetspots

## Backups (verified)

| Artifact | Path | Verify |
|----------|------|--------|
| DB custom dump | `…/pet_spot_elsahel.dump` (~18M) | `pg_restore -l` TOC ~26354 entries |
| Filestore tgz | `…/filestore.tgz` (~111M) | `tar -tzf` ~6143 members |
| Modules before | `…/modules_before.json` (346 installed) | |
| Social snapshot | `…/social_account_16.json` | |

## Rollback procedure (tested readiness)

1. Stop `pet_spot_elsahel.service` (user systemd).  
2. Restore DB: `pg_restore -h localhost -U odoo -d pet_spot_elsahel --clean --if-exists` from dump (or restore to new DB and swap `dbfilter` if preferred).  
3. Restore filestore from `filestore.tgz` into project `.filestore`.  
4. Start service; smoke-test `https://drpaws.ai/`.  

## Unpublished / multi-website review — NO STOP

| Page | Website | Published | Assessment |
|------|---------|-----------|------------|
| `/` id=4 | PetSpot El Sahel (1) | yes | Active clinic site — deploy target |
| `/` id=6 | sabry_youssef_resume (2) | no | Empty resume site — unrelated |
| `/` id=2 | (no website) | no | Empty template — unrelated |

No conflicting unpublished PetSpot marketing WIP on website 1.

## Material Test vs Production differences (pre-deploy)

| Area | Test | Production (before) |
|------|------|---------------------|
| Public host | test.drpaws.ai | drpaws.ai |
| `website_blog` | installed | **uninstalled** |
| Service pages | 6 present | **absent** |
| Company phone | +201280833332 | +201201568888 (call-center) |
| Company street | Amwaj 2 / El Alamein | Amwaj 1 gate / Sidi Abdel Rahman |
| JSON-LD VC/LB | present | absent / old |
| Placeholder 555 | cleaned | still in several views |
| Social FB #16 | n/a (push only) | connected |

## GBP screenshot

Binary PNG **not found** in chat uploads/Downloads/assets under GBP/place-card names at preflight time. Will attach if Sabry supplies path; text evidence already on Analysis #2697.
