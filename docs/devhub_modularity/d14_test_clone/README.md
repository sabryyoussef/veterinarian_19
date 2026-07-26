# D14 — Test Shadow Resolution (Plan + Rehearsal Gate)

**Status:** DOCUMENTED — **live Test not switched** (clone-first gate)

## Live Test truth (read-only snapshot)

| Item | Value |
|------|--------|
| Conf (active shadow) | `pet_spot_elsahel_test_activation_staging.conf` |
| Overlay first in addons_path | `releases/addons_overlay_staging` |
| Canonical conf (target later) | `pet_spot_elsahel_test.conf` (no overlay) |
| HTTP | :8028 |
| DB module state | `dev_session_hub` **19.0.8.5.5** installed; **no** `devhub_*` |

See `live_test_module_state.txt`, `staging_conf_snip.txt`, `canonical_conf_snip.txt`.

## Safe cutover sequence (not executed on live Test)

1. Backup live Test DB + filestore
2. `CREATE DATABASE pet_spot_elsahel_test_clone_modularity WITH TEMPLATE pet_spot_elsahel_test`
3. Point a **dedicated** conf at the clone using canonical `pet_spot_elsahel_test.conf` addons_path (no overlay)
4. Install/upgrade modular path (`dev_session_hub` 19.0.9.1.0 + `devhub_*`)
5. UAT on clone only
6. Only then schedule live Test cutover

## Explicit non-actions

- No live Test conf switch
- No overlay delete
- No Production Dev Hub install
- Overlay kept as archive
