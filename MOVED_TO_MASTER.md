# PetSpot El Sahel — moved to master

**Date:** 2026-07-04  
**Primary host:** `master` (HP Z620, `192.168.100.66`)  
**This copy:** laptop standby — do not run services here until you decide to sync, archive, or remove.

## Master paths

| Item | Path / value |
|------|----------------|
| Base | `/home/sabry/odoo_base/base_odoo_19/` |
| Project | `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/` |
| Config | `/home/sabry/odoo_base/base_odoo_19/config/projects/pet_spot_elsahel.conf` |
| Database | `pet_spot_elsahel` (PostgreSQL role `odoo`) |
| Odoo port | `8027` |
| Evolution API | `8199` (8099 taken by sabry-mobile-hub) |

## Services on master (user systemd)

```bash
ssh sabry@192.168.100.66
systemctl --user status pet_spot_elsahel petspot_evolution_api
journalctl --user -u pet_spot_elsahel -f
```

System unit install scripts are under `scripts/system/` (need `sudo` once password is available).

## Access from this laptop

UFW on master currently blocks inbound `8027`. Use an SSH tunnel:

```bash
ssh -L 8027:127.0.0.1:8027 sabry@192.168.100.66
# then open http://127.0.0.1:8027
```

To allow direct LAN access (run on master with sudo):

```bash
sudo ufw allow 8027/tcp comment 'PetSpot El Sahel Odoo'
sudo ufw reload
# then http://192.168.100.66:8027
```

## Later decision

- Sync both machines, or
- Archive this laptop copy under `archives/`, or
- Remove laptop project + drop local DB `pet_spot_elsahel`
