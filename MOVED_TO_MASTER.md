# PetSpot El Sahel — moved to master

**Date:** 2026-07-04  
**Primary host:** `master` (HP Z620, `192.168.100.66`)  
**This copy:** laptop standby — do not run services here until you decide to sync, archive, or remove.

---

## Master paths

| Item | Path / value |
|------|----------------|
| Base | `/home/sabry/odoo_base/base_odoo_19/` |
| Project | `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/` |
| Config | `/home/sabry/odoo_base/base_odoo_19/config/projects/pet_spot_elsahel.conf` |
| Filestore | `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/.filestore` |
| Evolution API dir | `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/evolution-api/` |
| Venv | `/home/sabry/odoo_base/base_odoo_19/venv19/` |
| Odoo bin | `/home/sabry/odoo_base/base_odoo_19/odoo19/odoo19/odoo-bin` |
| User unit sources | `/home/sabry/odoo_base/base_odoo_19/systemd-user/` |
| User units (live) | `~/.config/systemd/user/pet_spot_elsahel.service`, `petspot_evolution_api.service` |
| System install scripts | `/home/sabry/odoo_base/base_odoo_19/scripts/system/` |
| Database | `pet_spot_elsahel` (PostgreSQL role `odoo`, `db_host=localhost`) |
| Odoo port | `8027` |
| Evolution API | `8199` (bound to `127.0.0.1`; `8099` is taken by sabry-mobile-hub) |

---

## Services on master (user systemd — current setup)

User units are the active setup. Enable linger once so they survive logout:

```bash
ssh sabry@192.168.100.66
loginctl enable-linger sabry   # once
systemctl --user daemon-reload
systemctl --user enable --now pet_spot_elsahel petspot_evolution_api
systemctl --user status pet_spot_elsahel petspot_evolution_api
journalctl --user -u pet_spot_elsahel -f
```

Canonical unit files (copy into `~/.config/systemd/user/` if needed):

- `/home/sabry/odoo_base/base_odoo_19/systemd-user/pet_spot_elsahel.service`
- `/home/sabry/odoo_base/base_odoo_19/systemd-user/petspot_evolution_api.service`

---

## Optional system-wide units (sudo)

Use **either** user units **or** system units — not both.

```bash
sudo /home/sabry/odoo_base/base_odoo_19/scripts/system/install_pet_spot_elsahel_service.sh
sudo /home/sabry/odoo_base/base_odoo_19/scripts/system/install_petspot_evolution_service.sh
```

System units install to `/etc/systemd/system/` and run as `User=sabry`. Logs:

```bash
journalctl -u pet_spot_elsahel -f
journalctl -u petspot_evolution_api -f
```

---

## Access from this laptop

UFW on master may block inbound `8027`. Prefer an SSH tunnel:

```bash
# Odoo UI
ssh -L 8027:127.0.0.1:8027 sabry@192.168.100.66
# then open http://127.0.0.1:8027

# Evolution API (loopback-only on master)
ssh -L 8199:127.0.0.1:8199 sabry@192.168.100.66
# then http://127.0.0.1:8199
```

To allow direct LAN access to Odoo (run on master with sudo):

```bash
sudo ufw allow 8027/tcp comment 'PetSpot El Sahel Odoo'
sudo ufw reload
# then http://192.168.100.66:8027
```

Evolution is bound to `127.0.0.1:8199` by design — no LAN UFW rule is required; use the tunnel above.

---

## Verify on master

```bash
systemctl --user is-active pet_spot_elsahel petspot_evolution_api
curl -sI http://127.0.0.1:8027/web/login | head -1
curl -sI http://127.0.0.1:8199 | head -1
docker ps --filter name=petspot_evolution
```

Expect Odoo login HTTP response, Evolution container(s) up, and both user units `active`.

---

## Known follow-ups

- **Ownership:** project tree may be `root:root`. If user units fail writing filestore/logs:

  ```bash
  sudo chown -R sabry:sabry \
    /home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel \
    /home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/.filestore
  ```

- **Evolution URL:** compose comment may still mention `8099`; live bind is **`http://127.0.0.1:8199`**. Confirm Odoo `integration_bridge` / Evolution settings use `8199` on master.

- **PostgreSQL:** Odoo needs local Postgres up (`db_host=localhost`, role `odoo`, database `pet_spot_elsahel`).

---

## Later decision (laptop)

Pick one when master is stable:

### Sync (keep laptop as standby mirror)

```bash
# From laptop — pull code only; do not start local Odoo/Evolution while master is primary
rsync -avz --delete sabry@192.168.100.66:/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/ \
  /path/to/local/pet_spot_elsahel/
# or: git pull from the same remote master uses
```

### Archive

```bash
# On laptop
mkdir -p archives
mv /path/to/local/pet_spot_elsahel "archives/pet_spot_elsahel-$(date +%Y%m%d)"
```

### Remove

```bash
# On laptop — stop any local services first
systemctl --user stop pet_spot_elsahel petspot_evolution_api 2>/dev/null || true
dropdb -U odoo pet_spot_elsahel   # or: sudo -u postgres dropdb pet_spot_elsahel
rm -rf /path/to/local/pet_spot_elsahel
```
