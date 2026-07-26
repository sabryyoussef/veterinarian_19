# Gate M5 — Dell post-restore plan (NOT EXECUTED from master)

Destination host: `sabry3-Precision-5540` (`sabry3` @ `100.110.211.53`)  
Clean repo: `/home/sabry3/devhub/veterinarian_19` @ `ff53a8d96ed1d63de38e2cd05230a3a0c432b64e`  
Handoff source (on master): `.../backups/dell_handoff_pet_spot_elsahel_test_20260720T053201Z/`

## Preconditions (Dell)

1. Permanent `known_hosts` pin on master for ED25519 `SHA256:Uq8IW8zlSdAPxWkd7MF+eJwuvjQmUSyvJQBw6oNrtyU` (approved separately).
2. Artifacts transferred and `sha256sum -c SHA256SUMS.txt` passed.
3. Odoo 19 community + enterprise available on Dell; Python 3.12 venv with required packages.
4. PostgreSQL role able to own `pet_spot_elsahel_test`.
5. Port **8028 free** on Dell (observed: 8027 in use; 8028 preferred for Test).
6. Do **not** touch Dell legacy 914-path checkout.
7. Keep master Test instance intact until Dell UAT passes.

## Steps

### 1) Create isolated Dell PostgreSQL Test database
```bash
# On Dell — adjust role/socket as local practice
createdb -O <odoo_role> pet_spot_elsahel_test
```

### 2) Restore Test dump
```bash
pg_restore --no-owner --role=<odoo_role> -d pet_spot_elsahel_test \
  /home/sabry3/devhub/handoff/pet_spot_elsahel_test_20260720T053201Z/artifacts/pet_spot_elsahel_test.dump
```

### 3) Restore Test filestore only
```bash
mkdir -p /home/sabry3/devhub/filestore/pet_spot_elsahel_test_data/filestore
tar -C /home/sabry3/devhub/filestore/pet_spot_elsahel_test_data/filestore \
  -xzf .../artifacts/pet_spot_elsahel_test_filestore.tar.gz
# Results in .../filestore/pet_spot_elsahel_test/
```

### 4) Create Dell Test config + user service
- Start from `dell_test_odoo.conf.template` (secrets redacted).
- Fill `{{DELL_ODOO_COMMUNITY_ADDONS}}` / `{{DELL_ODOO_ENTERPRISE_ADDONS}}`.
- Set new `admin_passwd` / `db_password` locally (never reuse packaged secrets — none were packaged).
- `http_port=8028` if free; else choose free Test-only port and record it.
- `dbfilter=^pet_spot_elsahel_test$`
- `data_dir=/home/sabry3/devhub/filestore/pet_spot_elsahel_test_data`
- `addons_path=...,/home/sabry3/devhub/veterinarian_19` (clean repo root; no master overlay; no dirty tree).
- User systemd unit analogous to `pet_spot_elsahel_test.service` binding `-d pet_spot_elsahel_test`.

### 5) Use Dell clean repository
Confirm:
```bash
git -C /home/sabry3/devhub/veterinarian_19 rev-parse HEAD
# expect ff53a8d96ed1d63de38e2cd05230a3a0c432b64e
git -C /home/sabry3/devhub/veterinarian_19 status --porcelain  # expect empty
```

### 6) Port
Prefer **8028** (currently free on Dell per probe). Do not collide with 8027.

### 7) Reconfigure restored Test records (Dell-local Odoo shell / UI)
1. Create/update **Dell** `dev.machine`:
   - `hostname=sabry3-Precision-5540` (must equal `socket.gethostname()` on Dell Odoo)
   - `production=False`
   - `trust_zone=trusted_dev`
   - `ssh_alias=sabry3-precision-5540-ts`
   - `allowed_path_prefixes=/home/sabry3/devhub/veterinarian_19`
   - Tailscale refs as appropriate; pin Dell host key separately if used
2. **Do not** mutate master’s `dev.machine` / `production=true` on the restored copy except by creating Dell machine and switching FKs — prefer new machine row, then point env at it.
3. PetSpot Test `dev.environment`:
   - `machine_id` → Dell machine
   - keep `environment_type=test`, `is_production=False`, `data_sensitivity=internal_test`
   - update `config_reference`, `service_container_reference`, `url`, `port` for Dell
   - keep `database_identifier=pet_spot_elsahel_test`
4. `dev.repository`:
   - `working_directory=/home/sabry3/devhub/veterinarian_19`
   - `canonical_remote_path=/home/sabry3/devhub/veterinarian_19`
   - `default_branch=staging`
   - refresh git caches from `ff53a8d`
   - retain `origin_locked=True` / github repo allowlist binding
5. `dev.policy` for Test:
   - `production_access_policy=denied`
   - `deploy_permission=False`
   - development/launch/test as needed for Start & Launch
6. Ignore/CLEAR fake GateD production env and “Bad staging” deploy target for launch UAT.
7. Credential path refs remain path-only; provision Dell `/srv/devhub/credentials/...` separately (no secrets in handoff).

### 8) Historical sessions
Do **not** rewrite historical `dev.session` snapshots.

### 9) Fresh development session
Create a new session after rebind for Dell Start & Launch UAT.

### 10) Hostname equality gate
On Dell Odoo process host:
```python
import socket
assert socket.gethostname() == env['dev.machine'].browse(dell_machine_id).hostname
```

### 11) Launch validation order
1. Explicit fallback launching first.
2. Helper remains deferred.

### 12) Master remains authoritative until Dell UAT passes
Do not decommission or rebind master Test.

## Rollback (Dell)
- Stop Dell Test unit.
- Drop Dell `pet_spot_elsahel_test` if needed.
- Remove Dell Test `data_dir`.
- Leave master Test untouched (still authoritative).

## Rollback (master)
- No master rebind was performed; master Test continues on activation `ff53a8d` conf.
- Production never modified.
