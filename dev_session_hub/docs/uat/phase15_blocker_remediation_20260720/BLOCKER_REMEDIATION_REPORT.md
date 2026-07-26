# Blocker Remediation Report — Dell Test (Gates 1–2 follow-up)

**Date:** 2026-07-20  
**Scope:** Diagnose/remediate Blockers A & B only. **Start & Launch NOT executed.**

## Executive summary

| Blocker | Root cause | Status |
|---|---|---|
| **A — openproject_sync overlay** | Hard `dev_session_hub` dependency; module not in `veterinarian_19` @ `ff53a8d`; copied from master dirty **staged-but-uncommitted** tree | **Provenance proven + git-pinned interim**; **PR required** for durable fix |
| **B — TestCompletionRoadmap** | Tests assumed empty DB; activation UAT left GitHub installation `147639376`; deploy test polluted policy; manifest port hardcoded `8028` | **GREEN with proposed test patch** (Dell + master) |
| **B — full dev_session_hub suite** | Live handoff DB carries UAT outbox/work-item rows; outbox tests expect empty queue | **Not green on operational DB** (Dell: `1 failed, 2 error(s) of 117`; master polluted: `0 failed, 89 error(s) of 117`) |

**Gate 3 Start & Launch:** **NOT safe yet** — requires merged PR(s), Dell repin, and full-suite green on operational Test DB.

---

## Blocker A — openproject_sync provenance

### Why `dev_session_hub` requires it

| Mechanism | Evidence |
|---|---|
| **Manifest dependency** | `"depends": [..., "openproject_sync"]` in `dev_session_hub/__manifest__.py` |
| **Python / models** | `Many2one("openproject.backend")` on `dev.work.item`; OP milestone outbox channel |
| **Tests** | `TestDevWorkLifecycle.setUpClass` creates `openproject.backend` |
| **Data/XML** | OP work-package fields, `action_open_openproject`, seed task links |
| **Runtime DB** | `openproject_sync` installed `19.0.1.5.1` in handoff DB |
| **Not optional** | Without module on addons path, registry loads **without** `dev.*` models |

### Source of truth (current)

| Field | Value |
|---|---|
| **Authoritative tree** | `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/openproject_sync` |
| **Git status** | **32 files staged (`git add`) but never committed** on any branch |
| **Branch context** | `feature/resume-portability-candidates` (master dirty worktree) |
| **NOT on** | `origin/staging`, `origin/main`, Dell `ff53a8d` |
| **Module version** | `19.0.1.5.1` |
| **Tree hash (no `.pyc`)** | `9c6e94eb4052e67efbd9811f531208cf7ef5a3c22ca7624b74c14fa5fc99146c` |
| **Byte compare** | Dell overlay **identical** to master dirty tree (excluding `__pycache__`) |

### Git pins (interim, replaces anonymous overlay)

| Location | Git commit | Tree hash |
|---|---|---|
| Master pin repo | `ca9097b2e98ba03f9bdbbf88ec5f770137d0e7f4` | `9c6e94eb…` |
| Dell overlay | `c52759c20a9c3cb915713de9bf57f9b8bfc32b63` | `9c6e94eb…` |

### Secret / host scan

- No `.env`, credential files, or literal API tokens in tree
- `api_token` is a **field definition** on `openproject.backend` (values live in DB only)
- No host-specific URLs committed (test invalid domains only)

### Durable architecture recommendation

**Primary (recommended):** Allowlist-only PR to `sabryyoussef/veterinarian_19` → `staging`:

```
openproject_sync/**   (entire module, version 19.0.1.5.1)
```

Then Dell/master addons path = community + enterprise + **`veterinarian_19` @ pinned SHA** — remove `addons_overlay_deps`.

**Do not:** silently copy into clean checkout without PR; do not drop manifest dependency without refactoring `dev.work.item` OP integration.

**Handoff follow-up:** Future dumps should either include only modules present in `veterinarian_19`, or document required companion modules explicitly.

### Dell diff from `origin/staging`

- `openproject_sync`: **missing** on `ff53a8d` / `origin/staging`
- Interim runtime path: `/home/sabry3/devhub/addons_overlay_deps/openproject_sync` (git-pinned above)

---

## Blocker B — TestCompletionRoadmap

### Test location

- **File:** `dev_session_hub/tests/test_completion_roadmap.py`
- **Class:** `TestCompletionRoadmap`
- **Tags:** `@tagged("post_install", "-at_install")`
- **CLI tag:** `--test-tags=/dev_session_hub:TestCompletionRoadmap`

### Root cause classification

| Symptom | Classification |
|---|---|
| Empty log on first Dell attempts | **Infrastructure** (wrong dump path, port bind, log reuse) |
| `KeyError: dev.machine` | **Dependency failure** (missing `openproject_sync` on path) |
| `setUpClass` `UniqueViolation` on `dev_github_app_installation` | **Assertion/fixture failure** — tests assumed empty DB; activation left installation `147639376` |
| `public_update_purpose` NOT NULL on `project_task` | **Dependency failure** — `project_public_task_update` installed in DB but absent from Dell addons path |
| Full-suite lifecycle mass errors | **Test isolation failure** — `test_deploy_*` set `deploy_permission=True` without restore, breaking `_assert_dev_hub_safe` |
| `manifest["port"] == 8028` | **Environment mismatch** — Dell Test uses **18028** |

### Authoritative commands (Dell, after ephemeral test patch)

```bash
/systemd stop pet_spot_elsahel_test
$ODOO_BIN -c $CONF -d pet_spot_elsahel_test \
  --http-port=19028 --stop-after-init --test-enable \
  --test-tags=/dev_session_hub:TestCompletionRoadmap \
  --log-level=test --logfile=$LOGDIR/test_roadmap.log
```

### Results (with proposed test patch; Dell repo restored to `ff53a8d` after run)

| Suite | Return code | Totals |
|---|---|---|
| **TestCompletionRoadmap (Dell)** | `0` | **0 failed, 0 error(s) of 11 tests** (1 skipped: no `merged_reviewed` workspace) |
| **TestCompletionRoadmap (master)** | `0` | **0 failed, 0 error(s) of 11 tests** (1 skipped) |
| **Full `/dev_session_hub` (Dell live DB)** | `1` | **1 failed, 2 error(s) of 117 tests** |
| **Full `/dev_session_hub` (master live DB)** | `1` | **0 failed, 89 error(s) of 117 tests** (DB polluted by earlier runs today) |

### Proposed code fix (PR — not merged, not on Dell `ff53a8d`)

Files in release overlay (proposed PR diff):

1. `dev_session_hub/tests/test_completion_roadmap.py`
   - Idempotent `setUpClass` for GitHub installation/allowlist (reuse activation records)
   - Skip deploy test **before** mutating policy; restore policy in `finally`
   - Reuse existing staging deploy target when present

2. `dev_session_hub/tests/test_dev_session_hub.py`
   - `manifest["port"]` asserts `self.environment.port` (supports 18028)

**No assertion weakening** — fixtures made compatible with activated Test DB.

### Remaining full-suite failures (Dell live DB)

3 tests — outbox queue collisions with pre-existing UAT `dev.external.outbox` rows:

- `test_outbox_service_leasing_callbacks_and_queue_idempotency` — `AssertionError: 32 != 245`
- `test_outbox_retry_dead_letter_and_service_scope` — lease identity `AccessError`
- `test_outbox_stale_lease_is_fenced_and_uncertain_delivery_reconciles` — lease identity `AccessError`

**Root cause:** operational handoff DB retains UAT outbox state; tests expect an empty queue. Requires follow-up test isolation (filter by correlation) or disposable DB hygiene — **separate PR**.

---

## Active addons-path provenance (Dell Test)

| Path | Source | Immutable identity |
|---|---|---|
| `.../odoo19/addons` | Odoo 19 community install | vendor tree |
| `.../odoo19/enterprise` | Odoo 19 enterprise install | vendor tree |
| `/home/sabry3/devhub/addons_overlay_deps/openproject_sync` | Master dirty staged tree | git `c52759c2…`, tree `9c6e94eb…` |
| `/home/sabry3/devhub/veterinarian_19` | `git@github.com:sabryyoussef/veterinarian_19.git` | **`ff53a8d96ed1d63de38e2cd05230a3a0c432b64e`** (porcelain 0) |

`dev_session_hub` loads from **`veterinarian_19` @ `ff53a8d`** (unchanged).

---

## Files / configuration changed this turn

| Item | Change |
|---|---|
| Dell `addons_overlay_deps/openproject_sync` | Initialized **git pin** (no content change) |
| Dell `veterinarian_19` tests | **Ephemeral** patch during test runs only; **restored to `ff53a8d`** |
| Dell service/config | **Unchanged** — port **18028**, neutralization intact |
| Master Test service | Stopped briefly for test runs; **restarted active** |
| Release overlay (local) | Proposed test fixes in `releases/.../dev_session_hub/tests/` — **not merged** |

---

## Post-remediation validation (Dell Test)

| Check | Result |
|---|---|
| HTTP `/web/login` | **200** |
| `_assert_dev_hub_safe` | **PASS** |
| `dev_session_hub` version | **19.0.8.0.0** |
| Outbound integrations | OP backend inactive; mail inactive |
| Start & Launch | **NOT executed** |

---

## PR plan (approval required before merge/repin)

### PR-1: `openproject_sync` → `veterinarian_19` staging

- **Allowlist:** `openproject_sync/**` only (32 files, v `19.0.1.5.1`)
- **Source commit message:** import from tree `9c6e94eb…`
- **After merge:** Dell repin `veterinarian_19` to new SHA; remove `addons_overlay_deps/openproject_sync`

### PR-2: `dev_session_hub` test isolation @ `ff53a8d` base

- **Allowlist:**
  - `dev_session_hub/tests/test_completion_roadmap.py`
  - `dev_session_hub/tests/test_dev_session_hub.py`
- **Why:** activated Test DB compatibility (GitHub installation, policy restore, dynamic port)
- **After merge:** Dell repin; rerun full suite on operational DB

### PR-3 (follow-up): outbox test isolation

- Scope outbox tests to test-created correlation IDs or use dedicated disposable DB flag
- Target: full suite green on `pet_spot_elsahel_test` without truncating UAT history

---

## Gate 3 safety assessment

| Criterion | Ready? |
|---|---|
| Reproducible addons (no anonymous overlay) | **Partial** — git-pinned interim only |
| `openproject_sync` in `veterinarian_19` | **No** — PR-1 required |
| TestCompletionRoadmap green on Dell | **Yes** — with PR-2 merged + repin |
| Full suite green | **No** — 3 outbox failures on live DB |
| Start & Launch | **NOT executed** |

**Request:** Approve **PR-1 + PR-2** merge and Dell repin before Gate 3 Start & Launch UAT (port **18028**, explicit fallback first).

---

## Preservation confirmations

- Production / Dell **8027**: untouched  
- Master Test: **active**  
- Master **367** dirty paths: preserved  
- Dell legacy **914** tree: preserved  
- Historical sessions: not rewritten  
- Cursor / port **8028**: not reclaimed  
