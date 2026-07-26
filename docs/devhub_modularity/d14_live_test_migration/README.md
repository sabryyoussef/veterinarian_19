# D14 Live Test Migration — Evidence Pack Index

Primary report: [`../D14_TEST_CANONICAL_MIGRATION_REPORT.md`](../D14_TEST_CANONICAL_MIGRATION_REPORT.md)

## Layout

| Path | Contents |
|------|----------|
| `baseline/` | Live Test freeze: runtime, git, modules, counts, OP links, XML IDs, sample IDs |
| `clone/` | Clone details, dump/restore log, shadow resolution |
| `upgrade/` | Phase plan, logs A–H, pre-remap, after module state |
| `reconcile/` | After counts, reconciliation, ID stability, FK orphans, OP links |
| `validation/` | Functional shell, model ownership, work depends, menu health |
| `uat/` | Server PID/log, login HTTP, XML-RPC smoke, registry scan |
| `compare/` | Module version diff vs `devhub_modular_fresh` |

## Clone runtime (rehearsal)

- DB: `pet_spot_elsahel_test_modular_mig`
- Port: `8041` (127.0.0.1)
- Conf: `config/projects/pet_spot_elsahel_test_modular_mig.conf`
- Live Test `:8028` untouched
