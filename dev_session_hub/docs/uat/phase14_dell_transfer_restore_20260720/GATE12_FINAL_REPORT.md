# Gates 1–2 Final Report — Dell Test transfer & restore

**Date:** 2026-07-20  
**Scope approved:** Gate 1 transfer + Gate 2 Dell Test restore/configure/validate  
**Not approved / not executed:** Gate 3 Start & Launch UAT

## Verdict

Gates 1 and 2 technical + safety validation completed on Dell.  
Dell Test Odoo is **active** on **http://127.0.0.1:18028** (HTTP 200), DB `pet_spot_elsahel_test` only, module `dev_session_hub` **19.0.8.0.0**, clean repo **ff53a8d**, `_assert_dev_hub_safe` **PASS**.  
**Stop here** — request separate human approval for Gate 3.

## Permanent SSH pin (Gate T1)

| Check | Result |
|---|---|
| Alias | `sabry3-precision-5540-ts` → `sabry3@100.110.211.53` |
| HostKeyAlias | `sabry3-precision-5540-ts` |
| StrictHostKeyChecking | `yes` (`true` via `ssh -G`) |
| Live ED25519 fingerprint | `SHA256:Uq8IW8zlSdAPxWkd7MF+eJwuvjQmUSyvJQBw6oNrtyU` **MATCH** |
| BatchMode SSH | **PASS** |
| Host-key verification disabled? | **No** |

## Transfer (Gate T2)

| Artifact | SHA-256 | Dest verify |
|---|---|---|
| `pet_spot_elsahel_test.dump` | `6f1fa95114a18e1ffbc4b28ef19805c64f107906e9c67d8b5f0db00d2734354d` | **OK** |
| `pet_spot_elsahel_test_filestore.tar.gz` | `51bc865ce8b7479547e57b6004f3ae32c6428514a41cf301a7622712c592d079` | **OK** |
| template / manifest / SHA256SUMS | (handoff package) | **OK** |

- Destination: `/home/sabry3/devhub/handoff/pet_spot_elsahel_test_20260720T053201Z/` (sabry3-only)
- Allowlist-only transfer; no Production DB/filestore, keys, tokens, `.env`, or dirty worktree files
- Filestore archive top-level: `pet_spot_elsahel_test` only
- Host `pg_restore -l` blocked by Dell system PG16 vs dump format; validated via Docker **PostgreSQL 18.4** (`devhub-petspot-test-pg18` on `127.0.0.1:5433`)

## Restore (Gate D3)

| Item | Value |
|---|---|
| `pg_restore_rc` | **0** |
| DB created | `pet_spot_elsahel_test` only |
| Extensions | `pg_trgm`, `plpgsql` |
| Module | `dev_session_hub\|installed\|19.0.8.0.0` |
| Attachments | 1267 |
| Filestore path | `/home/sabry3/devhub/filestore/pet_spot_elsahel_test_data/filestore/pet_spot_elsahel_test` |
| Dell port **8027** / DB `pet_spot_elsahel` | **untouched** (still listening, distinct PID) |

## Dell-local secrets (Gate D2) — redacted

| Path | Mode | Notes |
|---|---|---|
| `/home/sabry3/devhub/secrets/pet_spot_elsahel_test.env` | `600` | Dell-local only; not printed; not in Git |
| `/home/sabry3/devhub/config/pet_spot_elsahel_test.conf` | `600` | admin_passwd + db_password redacted in evidence |
| data_dir | `700` | dedicated Test filestore |

## Config / service (Gate D5)

| Item | Value |
|---|---|
| Conf | `/home/sabry3/devhub/config/pet_spot_elsahel_test.conf` |
| Unit | `~/.config/systemd/user/pet_spot_elsahel_test.service` |
| SyslogIdentifier | `pet_spot_elsahel_test` |
| DB filter | `^pet_spot_elsahel_test$` ; `list_db = False` |
| Addons | community + enterprise + **`/home/sabry3/devhub/addons_overlay_deps`** + `/home/sabry3/devhub/veterinarian_19` |
| HTTP port (actual) | **18028** (see port note) |
| PG | Docker PG18 `127.0.0.1:5433` (isolated from system PG16 / 8027) |

### Port note (intentional)

Requested **8028** was occupied by **Cursor** on Dell. **8029** and **8030** were also taken by Cursor.  
Dell Test therefore binds **18028**. Port **8027** left untouched.

### Dependency overlay note

Clean repo `ff53a8d` does **not** contain `openproject_sync`, but the restored DB has it installed and `dev_session_hub` depends on it.  
Added isolated overlay: `/home/sabry3/devhub/addons_overlay_deps/openproject_sync` (code only). Without it, registry loaded without `dev.*` models.

## Outbound neutralization (Gate D4) — before → after

| Integration | Before | After |
|---|---|---|
| `ir_mail_server` active | 0 | 0 |
| `fetchmail_server` active | 0 | 0 |
| `ir_cron` active (externalish disabled) | 67 → disabled 13 | ~50 active remaining (non-externalish) |
| `payment_provider` enabled | 0 (21 disabled) | 0 |
| `web.base.url` | `https://test.drpaws.ai` | `http://127.0.0.1:18028` |
| `dev.policy` production_access | denied | **denied** |
| `dev.policy` deploy_permission | true → | **False** |
| Fake Gate-D Production env (id 246) | active | **active=false** (history retained) |
| Bad staging deploy target (id 3) | active | **active=false** |
| `openproject_backend` active | 1 | **0** |
| OpenProject pull cron | active | **active=false** |

Historical business data retained. No secret values printed.

## Dev Hub rebind (Gate D6) — before → after (Dell Test DB only)

| Object | Before (from master dump) | After (Dell) |
|---|---|---|
| `dev.machine` Dell | (created/updated) | id **77**, hostname=`sabry3-Precision-5540`, ssh_alias=`sabry3-precision-5540-ts`, production=**False**, trust_zone=`trusted_dev`, allowed_path_prefixes=`/home/sabry3/devhub/veterinarian_19` |
| PetSpot Test env | master-oriented | machine_id=**77**, environment_type=`test`, is_production=**False**, `data_sensitivity=internal_test`, port/url=**18028** |
| PetSpot repository | master paths | working_directory + canonical_remote_path=`/home/sabry3/devhub/veterinarian_19`, default_branch=`staging`, head=`ff53a8d…` |
| Historical sessions (incl. 257) | — | **not rewritten** |
| New launch session | — | **none created** |
| Master DB records | — | **not modified** |

## Controlled start validation (Gate D7)

| Check | Result |
|---|---|
| Service active | **active** (PID on 18028) |
| HTTP `/web/login` | **200** |
| dbfilter | `^pet_spot_elsahel_test$` + `list_db=False` |
| Module version | **19.0.8.0.0** (single row) |
| Hostname | `sabry3-Precision-5540` |
| Repo SHA / porcelain | `ff53a8d…` / **0** |
| `_assert_dev_hub_safe` | **PASS** |
| Launch hostname equality | **PASS** |
| Dell smoke (`SMOKE_PASS`) | **PASS** |
| `TestCompletionRoadmap` CLI | **Not completed** (runner produced empty/unusable log on Dell; smoke used instead) |
| Start & Launch | **NOT executed** |
| Cursor helper / live runner | **NOT executed** |
| Port 8027 service | **unchanged** (python PID 3051) |

### `_assert_dev_hub_safe` condition matrix

| Condition | Result |
|---|---|
| hostname == machine.hostname | PASS |
| machine.production == False | PASS |
| trust_zone == trusted_dev | PASS |
| env_type == test | PASS |
| is_production == False | PASS |
| production_access_policy == denied | PASS |
| deploy_permission == False | PASS |
| launch_allowed == True | PASS |
| repo workdir Dell clean path | PASS |
| repo head ff53a8d | PASS |
| allowed_path_prefixes includes clean repo | PASS |
| `_assert_dev_hub_safe` | PASS |

## Preservation confirmations

| Invariant | Status |
|---|---|
| Production (master 8027 / Dell 8027) untouched | **Confirmed** |
| Master Test still available (`active`) | **Confirmed** |
| Master unrelated dirty paths | **367 preserved** |
| Dell legacy `/home/sabry3/sabry_backup` (914-path tree) | **Preserved / not modified** |
| Master handoff package retained | **Confirmed** |

## Remaining blockers for Gate 3 (Start & Launch UAT)

1. **Human approval required** for Gate 3 (explicit fallback first).
2. Dell Test listens on **18028**, not 8028 — Gate 3 plan should use this URL/port (or free 8028 from Cursor and rebind).
3. `openproject_sync` lives only in Dell overlay (not in clean `ff53a8d` tree) — decide long-term packaging before production-like promotion.
4. Full `TestCompletionRoadmap` CLI suite not green on Dell yet (smoke PASS only).
5. Do not Start & Launch until approval; keep simulate-only runner posture.

## Request

**Please approve Gate 3 separately:** Dell-local Start & Launch UAT using explicit fallback first.
