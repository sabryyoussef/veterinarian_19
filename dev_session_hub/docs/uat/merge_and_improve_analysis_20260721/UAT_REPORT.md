# UAT — Merge & Improve Analysis (guarded async semantic merge)

Date: 2026-07-21 · Environment: Test only (DB `pet_spot_elsahel_test`, port 8028)
Module: `dev_session_hub` 19.0.8.7.0 → **19.0.8.8.0** (Production untouched)

## Feature

New button **"Merge & Improve Analysis"** on an analysis revision. It queues a
guarded `dev.work.generation` request of the new `kind = 'merge_analysis'` that
consolidates the machine analysis with the human "My Analysis" notes via the
existing external worker (n8n → Dify), then imports the result as a new
`origin = 'mixed'` analysis revision. Human input is authoritative; the base
revision and history are preserved.

No outbound LLM call was added to Odoo — the LLM stays in the external worker.

## Step 0 — canonical source & worker discovery

- Active Test source (verified from the running listener + installed version):
  port 8028 owner PID 1339550 runs `pet_spot_elsahel_test_activation_ff53a8d.conf`
  → overlay `releases/addons_overlay_ff53a8d` → `releases/veterinarian_19_ff53a8d/dev_session_hub`;
  DB had `dev_session_hub 19.0.8.7.0` installed. Git: detached HEAD `ff53a8d`.
- Worker: n8n workflow **"Dev Hub - Analysis and Plan Generation"**
  (`TCixu48xS9D4dTGZ`, inactive) at
  `/home/sabry/infra/n8n/workflow-dev-hub-analysis-plan.json`; leases via RPC
  (`service_lease` → `service_mark_processing` → `service_complete`), routes by
  `kind`, calls Dify `/workflows/run`. Kinds supported before: `analysis`, `plan`.
  Confirmed **safely extendable** with `merge_analysis` (additive Switch rule +
  Dify node + parse branch). Option A (reuse guarded pipeline) used.

## Automated tests (Test DB)

`odoo-bin -u dev_session_hub --test-enable --test-tags
/dev_session_hub:TestDevWorkLifecycle.test_merge_*` →
`0 failed, 0 error(s) of 6 tests`:

- test_merge_and_improve_creates_mixed_revision
- test_merge_button_action_returns_notification
- test_merge_requires_human_notes
- test_merge_rejects_superseded_base
- test_merge_dead_letters_on_stale_base
- test_merge_rejects_unsupported_output_fields

## Live end-to-end (real Dify semantic merge)

Work item **3091** ("UAT: Merge & Improve Analysis (warranty auto-apply)").

1. Base analysis rev 1 (id 2523, origin generated) created via the guarded
   pipeline; human authoritative "My Analysis" notes added.
2. `Merge & Improve` queued `dev.work.generation` id **2367**, `kind=merge_analysis`.
3. Worker path executed exactly as n8n does: `service_lease` →
   `service_mark_processing(provider='dify:merge_analysis')` → **real Dify
   Developer-Assistant produced the semantic merge** → `service_complete`.
4. Callback imported the consolidated revision.

Resulting DB state:

```
dev_work_generation 2367 | merge_analysis | succeeded | dify:merge_analysis | run uat-merge-2367 | artifact dev.work.analysis 2524
dev_work_analysis (work_item 3091):
  rev 1  id 2523  status generated  origin generated  (base; preserved)  hash 802d597b9bc7
  rev 2  id 2524  status generated  origin mixed  base_analysis_id=2523  parent_revision_id=2523
         merged_by set  merged_at set  human_input_snapshot set  model_reference managed-dify-workflow  hash 4ca66b26360a
```

- Merged rev 2 became `current_analysis_id` (shown in the Analysis tab).
- Base rev 1 unchanged (different content hash) → history/traceability preserved.
- Merged content correctly folded in the authoritative human input: root cause
  relocated to `sale.order.line` + `product.template`, `torz_warranty` noted,
  `affected_components` corrected from "fleet vehicle model configuration" to
  "product.template, sale.order.line, fleet vehicle service flow".

## Guard coverage proven

- Scope: `merge_analysis` lease/complete require `group_dev_hub_generation`.
- Staleness: base-hash change after queue → `stale_generation_context` dead-letter.
- Schema: unexpected output field → `invalid_generation_output` dead-letter.
- Preconditions: requires existing analysis + non-empty human notes + Analyzing
  phase + non-production trusted target/policy.

## Deploying the worker for automatic processing

Odoo side is live. To auto-process merge requests, import
`infra/n8n/workflow-dev-hub-analysis-plan-merge.json` and create/point the Dify
merge app (`DIFY_API_KEY_DEV_HUB_MERGE`, prompt
`infra/dify/prompts/dev-hub-merge-analysis-v1.txt`). See
`infra/dify/DEV_HUB_MERGE_DEPLOYMENT.md`.

---

# Part 2 — Fully-automatic deployment & UAT (2026-07-21)

## Worker deployment (Test only)

- **Dify merge app** deployed by cloning the live "Dev Hub Analysis" app DSL,
  swapping name/description/system-prompt for the merge task; API key stored as
  `DIFY_API_KEY_DEV_HUB_MERGE` and injected into the n8n container env (recreated
  with live `OPENPROJECT_API_TOKEN`/`OPENPROJECT_BASIC_AUTH` pinned so no other
  integration regressed).
- **n8n workflow** `TCixu48xS9D4dTGZ` ("Dev Hub - Analysis and Plan Generation")
  updated with an additive `merge_analysis` Switch branch → Dify merge HTTP node →
  parse branch, then **activated**. `analysis` and `plan` branches unchanged.
- Verified active workflows include `TCixu48xS9D4dTGZ` (no other DevHub workflow
  disabled).

## Fully-automatic UAT evidence (live worker + live Dify, no simulation)

All requests below were leased/processed automatically by the activated n8n
worker calling Dify; Odoo only queued via the server methods behind the UI
buttons.

| item | gen id | kind | state | create → write |
|------|--------|------|-------|----------------|
| **3092** (fresh AUTO UAT) | 2368 | analysis | succeeded | 09:51:22 → 09:51:51 |
| 3092 | 2369 | merge_analysis | succeeded | 09:53:03 → 09:58:52 |
| 3092 | 2370 | plan | succeeded | 10:01:34 → 10:02:00 |
| **3093** (stale-base test) | 2371 | analysis | succeeded | 10:06:03 → 10:06:53 |
| 3093 | 2372 | merge_analysis | **dead_letter** (stale base) | 10:07:42 → 10:08:13 |
| **3091** (historical, kept) | 2366 | analysis | succeeded | — |
| 3091 | 2367 | merge_analysis | succeeded | — |

Analysis revisions:

```
id    wi    rev  status     origin     base   merged_at            hash16
2523  3091  1    generated  generated  -      -                    802d597b9bc70cb2
2524  3091  2    generated  mixed      2523   2026-07-21 09:01:33  4ca66b26360a01f8
2525  3092  1    generated  generated  -      -                    ae329db6e054c8fe
2526  3092  2    accepted   mixed      2525   2026-07-21 09:58:52  f8fcc8507c214705   <- current after merge, then accepted
2527  3093  1    generated  generated  -      -                    22db0ce001ff84e4   (no rev2: merge dead-lettered)
```

### 9 conditions — all confirmed

1. Button queues `merge_analysis` — gen 2369 (3092) created by the merge action.
2. Worker automatically leases it — n8n lease/processing/complete round-trip
   (create 09:53:03 → write 09:58:52; ~6 min real Dify latency).
3. Dify performs the semantic merge — provider `dify:merge_analysis`.
4. Callback succeeds — gen 2369 `succeeded`; imported rev 2526.
5. New `origin='mixed'` revision becomes current — 2526 (base 2525) became
   `current_analysis_id`.
6. Previous analysis preserved — 2525 unchanged (distinct hash), still present.
7. Human analysis included & corrective — authoritative "My Analysis" folded into
   2526 (base findings kept/refined, human corrections applied).
8. Stale-base protection works — 3093 gen 2372 **dead_letter** with
   `stale_generation_context`; **no** rev 2 created for 3093.
9. Normal analysis & plan still work — gen 2368 (analysis) and 2370 (plan) both
   `succeeded`; plan route un-regressed.

## Regression suite (full module) + root cause

`odoo-bin -u dev_session_hub --test-enable --test-tags /dev_session_hub` on the
Test DB reported **187 tests: 1 failed, 7 error(s)** before an unrelated
preflight-simulation test hung the run (killed; service restarted). Every
failure was root-caused and is **not** a merge-feature regression except one,
which was fixed:

- **1 failed** — `TestDevSessionHubInstall.test_dev_session_hub_module_installed`:
  hard-pinned expected version `19.0.8.2.0` vs manifest `19.0.8.8.0`. This is the
  intentional "bump the pin when you bump the manifest" guard. **Fixed**: pin
  updated to `19.0.8.8.0`.
- **1 error** — `TestDevWorkLifecycle.test_merge_accepts_notes_with_guard_patterns`:
  genuine merge-feature bug. `write()`/`create()` ran the strict `_clean_text`
  guard on the human `user_analysis_notes`, rejecting notes that quote
  diffs/`transcript:`/`messages:`/env lines — even though the design neutralizes
  those later via `_neutralize_forbidden`/`_context_text` when building the merge
  context. **Fixed**: added `_clean_note_text` (length + `SECRET_PATTERN` only) and
  routed `user_analysis_notes` through it in both `create()` and `write()`.
  Credentials are still blocked; forbidden content is neutralized at context build.
- **6 errors** — production-guard tests
  (`test_*production*`, `test_generation_rejects_invalid_schema_and_production`,
  `test_execution_workspace_denies_production_environment_and_target`,
  `test_staging_target_rejects_production_env`): all fail inside
  `dev_odoo_runtime.py::_check_dedicated_not_petspot` ("Dedicated Test
  environments require a shared Odoo runtime"). `dev_odoo_runtime.py` is a **new,
  untracked pre-existing WIP model** — **not** part of the merge feature. These
  errors exist independently of this work.

### Focused re-test after fixes (redeployed via `-u`)

`--test-tags` = the 6 merge tests + the guard-pattern test + the install pin test:

```
0 failed, 0 error(s) of 8 tests   (regression_full_suite / focused_retest logs saved alongside this report)
```

## Change isolation (feature vs pre-existing WIP)

Checkout is **detached at `ff53a8d`** with extensive pre-existing uncommitted WIP.
No pre-session WIP baseline exists in git, and feature + WIP edits interleave
inside several shared files, so a byte-exact split is not derivable from git
alone. Classification (uncommitted vs HEAD `ff53a8d`):

**Feature-owned (must be committed):**
- `dev_session_hub/__manifest__.py` — version 8.7.0 → 8.8.0 (1 hunk).
- `dev_session_hub/models/dev_integration.py` — merge kind/context/actions,
  `service_complete` merge+plan sudo staleness reads (10 of 13 hunks).
- `dev_session_hub/models/dev_work.py` — merge provenance fields,
  `import_merged_analysis_draft`, `_clean_note_text` + note routing (5 of 10 hunks).
- `dev_session_hub/views/dev_work_views.xml` — Merge button, provenance group,
  mixed-origin list cue (4 of 7 hunks).
- `dev_session_hub/tests/test_dev_work_lifecycle.py` — merge test methods
  (feature test block).
- `dev_session_hub/tests/test_dev_session_hub_install.py` — version-pin update
  (this file is otherwise pre-existing WIP; only the pin line is feature-owned).
- `dev_session_hub/docs/uat/merge_and_improve_analysis_20260721/` — this report,
  logs, and `isolated_feature.patch`.

Best-effort hunk-level feature patch: `isolated_feature.patch` (feature-marked
hunks only). It is a guide, **not** a clean apply, because some hunks mix feature
and WIP lines.

**Pure pre-existing WIP (do NOT commit as part of this feature):**
- Models: `dev_odoo_runtime.py`, `dev_machine_verification.py`,
  `dev_project_op_links.py`, `dev_work_code_analysis.py` (all untracked) and the
  `models/__init__.py` / `tests/__init__.py` registrations for them.
- `dev_registry.py`, `security/*`, `data/dev_session_hub_seed.xml`,
  `views/dev_registry_views.xml`, `views/dev_dashboard_views.xml`,
  `views/dev_session_hub_menus.xml`, `views/dev_session_views.xml`.
- Tests: `test_completion_roadmap.py`, `test_dev_session_hub.py` modifications,
  and untracked `tests/common.py`, `test_code_database_analysis.py`,
  `test_dev_project_op_tabs.py`, `test_verify_tailscale_destination.py`.
- `migrations/19.0.8.2.0/`, other `docs/uat/*` dirs (phase13-16, code_db_analysis).

## Recommended safe Git strategy (from detached `ff53a8d` + WIP)

1. Do **not** `git add -A` / commit whole files — they carry unrelated WIP.
2. Create a feature branch off the release base:
   `git switch -c feature/dev-hub-merge-and-improve-analysis ff53a8d`.
3. Stage feature changes hunk-by-hunk with `git add -p` on the six feature-owned
   files, accepting only the merge hunks (use `isolated_feature.patch` + the
   symbol list — `merge_analysis`, `base_analysis_id`, `human_input_snapshot`,
   `merged_by_id`, `merged_at`, `import_merged_analysis_draft`,
   `request_analysis_merge`, `action_merge_and_improve`, `_clean_note_text`,
   `_neutralize_forbidden`/`_context_text`, "Merge & Improve" — as the guide);
   split/edit hunks (`s`/`e`) where feature and WIP share a hunk.
4. `git add` the whole `docs/uat/merge_and_improve_analysis_20260721/` dir.
5. Verify the staged set is feature-only: `git diff --cached` should contain no
   `dev_odoo_runtime`/registry/menu/security WIP; then re-run the 8 focused tests.
6. Commit; leave all remaining WIP unstaged for its own separate track.

