# D1 — Freeze Baseline & Test Shadow Resolution Plan

**Date:** 2026-07-23  
**Action:** Documentation / pin only — **no live Test switch**, **no Production changes**

---

## Code pin

| Item | Value |
|------|--------|
| Branch | `feature/devhub-modularization-whatsapp` |
| Baseline SHA | `5d627a7e4b6ec4a29928dfd3c57f3fcf000f66cc` |
| Canonical tree | `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel` |
| Plan doc | [`FUNCTIONAL_MODULARITY_PLAN.md`](./FUNCTIONAL_MODULARITY_PLAN.md) |

---

## Runtime truth

| Environment | Conf | Port | Dev Hub state |
|-------------|------|------|---------------|
| Production | `pet_spot_elsahel.conf` | 8027 | Modular Dev Hub **not** installed — **do not install** |
| Modular fresh | `devhub_modular_fresh.conf` | 8032 | Full modular 19.0.9.x — acceptance baseline |
| Test (live) | `pet_spot_elsahel_test_activation_staging.conf` | 8028 | Overlay shadow active |

---

## Test shadow evidence

| Item | Value |
|------|--------|
| Staging conf addons_path | inserts `releases/addons_overlay_staging` **before** canonical |
| Overlay `dev_session_hub` | **19.0.8.5.6** (monolith, owns models) |
| Canonical `dev_session_hub` | **19.0.9.0.0** (meta, zero models) |
| Test DB installed | `dev_session_hub` **19.0.8.5.5** |
| Test DB `devhub_*` | **all uninstalled** |
| Clean conf available | `pet_spot_elsahel_test.conf` (canonical-only) — **not live** |

---

## Resolution plan (execute in D14, not now)

1. `pg_dump` backup of `pet_spot_elsahel_test`
2. Clone DB → `pet_spot_elsahel_test_devhub_mig`
3. Start Odoo with `pet_spot_elsahel_test.conf` against clone (canonical-only)
4. Install modular stack / upgrade path on clone
5. UAT independent scenarios
6. Only after sign-off: cut live Test to clean conf
7. Keep `addons_overlay_staging` as **ARCHIVE** — do not delete

**Rollback:** restore staging conf + DB dump.

**Blocked until:** D12 fresh matrix PASS.

---

## D1 exit criteria

- [x] Baseline SHA recorded
- [x] Shadow documented with versions
- [x] Live Test **not** switched
- [x] Production untouched
