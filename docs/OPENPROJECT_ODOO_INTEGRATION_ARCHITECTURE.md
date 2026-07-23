# OpenProject ↔ Odoo Integration Architecture

**Status:** adopted (P0-B) — 2026-07-13  
**Scope:** documentation only; no install of `openproject_sync` on Production.

---

## 1. Roles of each Odoo database

| Role | Database | HTTP port | Service |
|------|----------|-----------|---------|
| **Production Clinic Operations** | `pet_spot_elsahel` | **8027** | `pet_spot_elsahel.service` |
| **OpenProject / Project Integration Hub** | `pet_spot_elsahel_test` | **8028** | `pet_spot_elsahel_test.service` |

### Production `:8027` — Clinic Operations

- PetSpot El Sahel day-to-day operations (appointments, clinic, website-facing production).
- Public / proxy entry: `https://drpaws.ai` and HTTPS proxy **8172 → 8027**.
- Bridge clinic path uses `PETSPOT_ODOO_URL` → Production.
- **Does not** host OpenProject project maps, sync backends, or `project.task.op_*` fields.
- **`openproject_sync` is not installed** on this database.

### Test `:8028` — Integration Hub

- OpenProject work-package ↔ Odoo task mirror and ops UI.
- Holds `openproject_sync` (**currently `19.0.1.5.0`**), backends, maps, linked tasks (`op_work_package_id`, …).
- Target of bridge `ODOO_URL` / Cursor MCP Odoo when testing OP sync or Dev Needed task tooling.
- Accessible as `https://test.drpaws.ai` (Cloudflare → 8028).

---

## 2. Data paths

### A) Project / WhatsApp → OpenProject → Odoo Test (integration)

```text
WhatsApp
  → Evolution API
  → Chatwoot
  → n8n (triage / WP create)
  → OpenProject (work packages)
  → Odoo Test (:8028) via openproject_sync pull/push
```

- n8n creates/updates work packages in OpenProject (`OPENPROJECT_*` env on n8n).
- Odoo module `openproject_sync` on **Test** pulls WPs into mapped Odoo projects/tasks.

### B) Bridge → Odoo Test (direct project tasks, when enabled)

```text
Chatwoot / Evolution bridge
  → ENABLE_ODOO_TASKS (+ ODOO_URL / ODOO_DATABASE)
  → http://127.0.0.1:8028  ·  DB pet_spot_elsahel_test
```

- Bridge `ENABLE_OPENPROJECT_TASKS` must stay **false** so n8n owns OP WP creation (avoid duplicates).

### C) PetSpot clinic → Odoo Production

```text
Clinic / FAQ bots (bridge PETSPOT_* )
  → PETSPOT_ODOO_URL (e.g. http://192.168.100.66:8027)
  → Production DB pet_spot_elsahel
```

This path is **clinic operations**, not OpenProject project sync.

---

## 3. OpenProject endpoints

| Purpose | URL |
|---------|-----|
| API (Docker / local) | `http://127.0.0.1:8081` |
| Public / browser / Tailscale | `https://master.tailcf9988.ts.net:10081` |

`openproject_sync` backend on Test is configured against the local API (`127.0.0.1:8081`) with the public URL for task links.

---

## 4. Source of Truth

| System | Role |
|--------|------|
| **OpenProject** | Source of truth for **project work packages** (hierarchy, ownership, status in OP). |
| **Odoo Test (`pet_spot_elsahel_test`)** | Mirror / **integration hub** for OP tasks (`openproject_sync`). |
| **Odoo Production (`pet_spot_elsahel`)** | **Clinic operations only** — not the OP task mirror. |
| **Chatwoot / n8n** | Ingestion and routing from WhatsApp into triage and OpenProject. |

---

## 5. Services and ports (quick map)

| Service | Port | Notes |
|---------|------|--------|
| Production Odoo | **8027** | `pet_spot_elsahel` |
| Test Odoo (integration hub) | **8028** | `pet_spot_elsahel_test` |
| OpenProject container API | **8081** | localhost |
| OpenProject public | **10081** | Tailscale / public host |
| PetSpot HTTPS proxy | **8172 → 8027** | production front |

Both PetSpot Odoo services share the same addons tree (including the `openproject_sync` **code**), but only the **Test database** has the module **installed**.

---

## 6. Facts verified (P0-A / P0-B)

- `openproject_sync` on Production: **uninstalled**; no `openproject_*` tables; no `project_task.op_*` columns.
- `openproject_sync` on Test: **installed** at **19.0.1.5.0**; backends, maps, linked tasks present.
- Production must **not** be assumed to contain Test Odoo project IDs (e.g. Project **#19** iZone map on Test ≠ Production clinic projects).

---

## 7. Warnings (mandatory)

1. **Do not** run `-i openproject_sync` (or silent “promote”) on Production without a **separate migration / publish plan**.
2. **Do not** assume Odoo Project **#19**, Maps **#16/#3/#19**, or linked WP counts from Test exist on Production.
3. Any future Promote to Production needs an independent **migration design** (install + maps + inventory + cutover), not a simple module upgrade assumption.
4. Do not confuse clinic Production traffic (`PETSPOT_ODOO_URL` → 8027) with OP sync (8028).

---

## 8. Operational note — Cron #72 (Test)

| Item | Value |
|------|--------|
| Cron | `#72` — `OpenProject: Pull Work Packages` |
| Database | Test only |
| State at P0-B | **`active = False` (disabled)** |
| Action in this step | **Do not re-enable** |

**Effect of leaving it disabled:**

- Periodic automatic pull from OpenProject into Odoo Test does **not** run on the 15-minute schedule.
- Sync still happens when an operator runs **Sync Now / Full Sync** from the backend UI (or an explicit shell/command).
- n8n → OpenProject WP creation continues regardless; only the Odoo Test **mirror refresh** is non-automatic until cron is deliberately re-enabled under a separate ops change.

---

## 9. Diagnostic runbook (before any Odoo command)

### How to confirm OpenProject Sync is the intended system

```bash
# Which Odoo processes?
systemctl --user status pet_spot_elsahel pet_spot_elsahel_test --no-pager

# Port ↔ DB
# 8027 = Production clinic
# 8028 = Integration hub
ss -tlnp | grep -E '8027|8028|8081|10081'
```

### How to know the current destination

| Check | Expectation if hub = Test |
|-------|---------------------------|
| Bridge `ODOO_URL` / `ODOO_DATABASE` | `…:8028` / `pet_spot_elsahel_test` |
| Cursor MCP Odoo | `8028` / `pet_spot_elsahel_test` |
| Bridge `PETSPOT_ODOO_URL` | Production clinic (`8027`) — **not** OP sync |
| `ENABLE_OPENPROJECT_TASKS` (bridge) | `false` (n8n owns OP creates) |

### How to verify backend / maps (Test only)

```bash
# Example: shell MUST use test config + test DB
odoo-bin -c .../pet_spot_elsahel_test.conf -d pet_spot_elsahel_test --http-port=18028
# Then in shell / UI: OpenProject Backend, Project Maps, last_pull_at
```

SQL smoke (Test DB):

```sql
SELECT name, state, latest_version FROM ir_module_module WHERE name = 'openproject_sync';
SELECT count(*) FROM openproject_backend;
SELECT count(*) FILTER (WHERE active) FROM openproject_project_map;
SELECT count(*) FROM project_task WHERE op_work_package_id IS NOT NULL;
```

### How to prevent sync against the wrong database

1. Always pass **both** `-c` and `-d` explicitly.
2. Match triples:

| Intent | Config file | `-d` | Port |
|--------|-------------|------|------|
| Clinic / Production | `pet_spot_elsahel.conf` | `pet_spot_elsahel` | 8027 |
| OP integration / sync | `pet_spot_elsahel_test.conf` | `pet_spot_elsahel_test` | 8028 |

3. Refuse to run `-u openproject_sync` / `-i openproject_sync` unless the config `dbfilter` and `-d` are **Test**, unless a written Prod publish plan exists.
4. Never infer environment from browser cookies alone — confirm `test.drpaws.ai` vs `drpaws.ai`.

### Distinguishing Production vs Test in one minute

| Signal | Production | Test / Integration Hub |
|--------|------------|-------------------------|
| URL | `drpaws.ai` / `:8027` | `test.drpaws.ai` / `:8028` |
| DB name | `pet_spot_elsahel` | `pet_spot_elsahel_test` |
| `openproject_sync` | uninstalled | installed |
| OP task mirror | no | yes |

---

## 10. Related references (do not treat as install-on-prod instructions)

- Module code: `openproject_sync/` (shared addons path; install state is **per database**).
- Platform bridge / n8n env under `/home/sabry/infra/` (see “misleading docs” list maintained in P0-B report — update in a later docs pass only).

---

*Document created for P0-B. No environment variables, services, or crons were changed as part of this documentation step.*
