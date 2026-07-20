# Dell Test handoff — master preparation report

Date: 2026-07-20T05:35:39Z  
Scope: **master-side preparation and export only**  
Production: **untouched**  
Dell restore/start: **not executed**  
Transfer: **not executed**

## 1. Immutable Test vs Production separation

| Dimension | Test | Production |
|---|---|---|
| Hostname (Odoo host) | master | master |
| Database | `pet_spot_elsahel_test` | `pet_spot_elsahel` |
| dbfilter | `^pet_spot_elsahel_test$` | `^pet_spot_elsahel$` |
| Service | `pet_spot_elsahel_test.service` | `pet_spot_elsahel.service` |
| Port | **8028** | **8027** |
| Active conf (effective) | `pet_spot_elsahel_test_activation_ff53a8d.conf` | `pet_spot_elsahel.conf` |
| Base conf | `pet_spot_elsahel_test.conf` | `pet_spot_elsahel.conf` |
| Filestore DB subdir | `.../filestore/pet_spot_elsahel_test` (204M) | `.../filestore/pet_spot_elsahel` (94M) |
| Shared data_dir parent | yes (same parent path) — **subdir-separated** | yes |
| Module `dev_session_hub` | installed `19.0.8.0.0` | not present / empty |
| Release SHA (active Test) | `ff53a8d96ed1d63de38e2cd05230a3a0c432b64e` | n/a (dirty project addons) |
| Overlay | `addons_overlay_ff53a8d` | none |
| Packaged in handoff | **yes (DB+Test filestore only)** | **no** |

**Verdict:** Test distinguishable from Production. Shared `data_dir` parent is acceptable because Odoo stores by database name; handoff archives **only** Test subdir.

## 2. Exact Test facts

- Master hostname: `master`
- DB: `pet_spot_elsahel_test` — owner `odoo`, UTF8, `en_US.UTF-8`, size ~181MB
- Extensions: `plpgsql`, `pg_trgm`
- Large objects: 0
- Attachments: 1267 rows (1054 with `store_fname`)
- Service MainPID at report time: see `final_invariants.txt`
- Active addons_path: community + enterprise + `addons_overlay_ff53a8d` + dirty project (overlay wins for `dev_session_hub`)
- Dirty unrelated paths preserved: **367**

## 3. Portability classification

See `M2_PORTABILITY_CLASSIFICATION.md`.

Key REBINDs on Dell: machine hostname/allowlist, Test environment machine_id/paths, repository workdir→`/home/sabry3/devhub/veterinarian_19`, `default_branch=staging`, `deploy_permission=False`.

## 4. Backup artifacts

Root: `/home/sabry/odoo_base/base_odoo_19/backups/dell_handoff_pet_spot_elsahel_test_20260720T053201Z`

| Artifact | Size | SHA-256 |
|---|---|---|
| `pet_spot_elsahel_test.dump` | 17M | `6f1fa95114a18e1ffbc4b28ef19805c64f107906e9c67d8b5f0db00d2734354d` |
| `pet_spot_elsahel_test_filestore.tar.gz` | 54M | `51bc865ce8b7479547e57b6004f3ae32c6428514a41cf301a7622712c592d079` |
| `dell_test_odoo.conf.template` | 548B | `4ca5e7c205412301812c97d9d7afef710ff56b5dcbc27b1e8bc9e1b54bce0324` |
| `RUNTIME_MANIFEST.json` | — | `45529da9b0e8a18a31539ef71aed3447202a9856775ebf2e24dca1a97f5bc56b` |
| `RUNTIME_MANIFEST.md` | — | `153fa70f09e4831043f565d40bf9500dae9789adcdd357d2a9ee9f1be5fadc97` |
| Full list | — | `artifacts/SHA256SUMS.txt` |

## 5. Verification results

- `pg_restore -l` TOC: **26992** lines — OK
- Filestore tar readable: **1375** entries; top dir **only** `pet_spot_elsahel_test` — Production excluded
- Module at dump: `dev_session_hub|installed|19.0.8.0.0`
- Production PID unchanged through backup window: `3429925`
- Master Test restarted and listening `:8028`

## 6. Secrets-exclusion confirmation

- Conf template: `admin_passwd` / `db_password` = `REDACTED`
- No PEM/token/.env packaged
- `/srv/devhub/credentials` file count on master: **0** (path refs only in DB)
- Production dump/filestore: **not packaged**
- Dirty/Class C trees: **not packaged**

## 7. SSH / pin status to Dell

| Check | Result |
|---|---|
| Alias `sabry3-precision-5540-ts` | Present (multi-name Host block) |
| Expected FP | `SHA256:Uq8IW8zlSdAPxWkd7MF+eJwuvjQmUSyvJQBw6oNrtyU` |
| Keyscan ED25519 | **MATCH** |
| Permanent `known_hosts` pin | **Absent** — required before transfer |
| Connectivity probe | OK via **temporary** known_hosts (did not mutate `~/.ssh/known_hosts`) |
| Dell hostname | `sabry3-Precision-5540` |
| Dell repo SHA | `ff53a8d…` porcelain=0 |
| Dell free space | ~38G on `/` |
| Dell port 8028 | free (8027 in use) |

Proposed pin script: `m4_proposed_known_hosts_pin_NOT_RUN.sh`  
Proposed transfer: `m4_transfer_command_NOT_RUN.sh` → `/home/sabry3/devhub/handoff/pet_spot_elsahel_test_20260720T053201Z/`

## 8. Transfer command — **NOT RUN**

See `m4_transfer_command_NOT_RUN.sh`. Blocked until permanent host-key pin + human transfer approval.

## 9. Dell restore/config/rebind plan

See `M5_DELL_POST_RESTORE_PLAN.md` (**not executed**).

## 10. Rollback plan

- **Master:** no rebind performed; Test continues on `ff53a8d` activation; Production untouched.
- **Dell (after future restore):** stop unit; drop Test DB; remove Dell Test data_dir; leave 914-path and master intact.

## 11. Remaining human approvals (required next)

1. **Transfer** verified handoff to Dell (after permanent known_hosts pin).
2. **Restore + configure** Dell Test (DB/filestore/conf/service/rebind).
3. **Dell-local Start & Launch UAT** (explicit fallback first; no master rebind).

## Hard constraints compliance

- Test only; Production untouched
- No Production dump/filestore
- No master rebind / no master.production change
- No secrets in artifacts/reports
- 367 dirty + Class C preserved
- Dell 914-path not touched
- Master Test instance retained
