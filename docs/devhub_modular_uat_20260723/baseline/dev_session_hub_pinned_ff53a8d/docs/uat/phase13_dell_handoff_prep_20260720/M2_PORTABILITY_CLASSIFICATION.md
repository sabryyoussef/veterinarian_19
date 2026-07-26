# Gate M2 — Portability and sanitization classification

Date: 2026-07-20T05:30Z  
Source DB: `pet_spot_elsahel_test` on master  
No secret values included.

## Classification legend

| Class | Meaning |
|---|---|
| COPY | Safe to restore unchanged |
| REBIND | Must change on Dell after restore |
| CLEAR | Exclude/clear/ignore after restore |
| PATHREF | Secret/path reference only (no secret material packaged) |
| SECRET | Actual secret — separate secure provisioning on Dell (not in handoff) |

## Records / configuration

| Item | Current master value (non-secret) | Class | Dell action |
|---|---|---|---|
| `dev.machine` id=1 master | hostname=`master`, ssh_alias=`master-ts`, production=`true`, trust_zone=`trusted_dev`, allowlist=`/home/sabry/odoo_base/.../pet_spot_elsahel`, Tailscale IP ref present, host-key pin present | REBIND | Create **new** Dell machine; do **not** flip master.production on master. Point Test env at Dell machine. |
| `dev.environment` PetSpot Test | type=`test`, db=`pet_spot_elsahel_test`, port=`8028`, config_ref=master test conf, service=`pet_spot_elsahel_test.service`, sensitivity=`internal_test`, is_production=`false`, machine_id→master | REBIND | Update machine_id→Dell; config/service/url/paths to Dell; keep type/test/sensitivity/is_production |
| `dev.environment` GateD Fake Prod Env | fake production fixture | CLEAR | Leave historical or archive; do not use for Dell Test launch |
| `dev.repository` PetSpot Odoo 19 | workdir+canonical=`.../projects/pet_spot_elsahel` (dirty), default_branch=`unresolved`, origin_locked=`true`, github=`sabryyoussef/veterinarian_19` | REBIND | workdir+canonical=`/home/sabry3/devhub/veterinarian_19`; default_branch=`staging`; refresh git caches from `ff53a8d`; keep origin_locked |
| `dev.session` (4 rows) | workdir snapshots under master dirty path | COPY (historical) | Do **not** rewrite historical snapshots; create fresh session after restore |
| `dev.execution.workspace` | count=0 | COPY | N/A |
| `dev.policy` PetSpot Test MVP | production_access_policy=`denied`, deploy_permission=`true`, development/launch/test allowed | REBIND | Set deploy_permission=`False` on Dell per handoff policy; keep production_access_policy=`denied` |
| GitHub allowlist path refs | `/srv/devhub/credentials/github/...` | PATHREF | Recreate empty path layout or Dell-local credential root; provision secrets separately |
| Deploy targets runner refs | `/srv/devhub/runners/staging` (+ backup) | PATHREF / REBIND | Install Dell Test runner paths later under approval; not required for Start & Launch UAT |
| Deploy target “Bad staging” | fake / polluted | CLEAR | Ignore |
| Odoo conf `admin_passwd` / `db_password` | SET on master | SECRET | Dell generates its own; never copy plaintext into handoff |
| `/srv/devhub/credentials` files | **0 files** on master | PATHREF | Dell provisions separately |
| Activation overlay paths | master-only | REBIND | Dell uses clean repo root as addons entry (no master overlay) |
| Filestore root shared with Prod | shared `data_dir` parent | — | Package **only** `filestore/pet_spot_elsahel_test` |

## Explicit packaging exclusions

- Private keys, GitHub App PEM contents, tokens, passwords, cookies, `.env`
- Production DB `pet_spot_elsahel` dump
- Production filestore `filestore/pet_spot_elsahel`
- Dirty project tree / Class C / 367 unrelated paths
- Evidence git dirs / UAT phase docs (optional; not required for Dell runtime)
- `/srv/devhub` credential file contents (none present; still excluded)
