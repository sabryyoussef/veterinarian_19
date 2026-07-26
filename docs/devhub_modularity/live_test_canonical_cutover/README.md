# Live Test Canonical Cutover — Evidence Pack

Primary report: [`../LIVE_TEST_CANONICAL_CUTOVER_REPORT.md`](../LIVE_TEST_CANONICAL_CUTOVER_REPORT.md)

## Layout

| Path | Contents |
|------|----------|
| `preflight/` | Service/runtime freeze, modules before, git, production Dev Hub state |
| `backup/` | Backup log + pointer to `.migration_backups/live_test_cutover_*` |
| `baseline/` | Data counts, OP/WhatsApp, sample IDs, group memberships |
| `remap/` | Group XML-ID remap SQL log + verification |
| `runtime/` | Stop/start, systemd after switch, shadow proof, overlay inactive note |
| `upgrade/` | Phases A–H logs + final module state |
| `reconcile/` | After counts, reconciliation, OP links, FK orphans, seed deltas |
| `validation/` | Versions, parity 19/19, ownership, groups, WhatsApp, production untouched |
| `uat/` | Login HTTP, XML-RPC smoke, workflow board, registry/traceback notes |

## Runtime after cutover

- DB: `pet_spot_elsahel_test`
- Port: `8028`
- Conf: `config/projects/pet_spot_elsahel_test.conf`
- Overlay: **inactive** (directory retained)
