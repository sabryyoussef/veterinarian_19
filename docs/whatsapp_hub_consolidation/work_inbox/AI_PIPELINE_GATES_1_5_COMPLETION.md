# Gates 1–5 Completion Report — Native Dify v3 + Test Auto-Analysis

**Date:** 2026-07-26  
**DB:** `pet_spot_elsahel_test` only  
**Production:** **NOT upgraded**  
**Modules:** `devhub_whatsapp` `19.0.9.5.0` (path norm + prompt default v3.0)

---

## Gate 1 — Native Dify schema v3

| Item | Value |
|------|-------|
| App | Dev Hub WhatsApp Project Resolver `[CANONICAL TEST]` |
| App ID | `dee250c0-7f44-467c-9b0b-86f069bdc17e` |
| Workflow ID | `5f747cb0-4b84-4fc5-99d5-48d30e1b3c15` (+ draft twin) |
| Old prompt | `wa_project_aware_v2.3` (schema_version `"2"`, single-task shape) |
| New prompt | `wa_project_aware_v3.0` |
| Prompt file | `/home/sabry/infra/dify/prompts/devhub-wa-project-resolver-v3.0.txt` |
| Backup | `infra/dify/prompts/backups/wa_project_aware_v2.3_live_*.txt` + graph JSON |
| Workflow updated_at | `2026-07-26 04:53:32 UTC` |
| Dify run ID | `a99b5f68-03ac-45a6-a138-c7a259fa9573` |
| Raw result | `docs/.../work_inbox/dify_v3_kafaat_result.json` |

### Schema change
- From v2 single analysis block → **v3** top-level `project`, `conversation_summary`, **`items[]`**, `ignored_messages`, `missing_context`, `requires_human_review`
- Uses Odoo `technical_evidence` input
- `contains_multiple_tasks` **not** set by LLM (server `len(items)>1`)

### Native Dify test output (Kafaat)
- `schema_version`: **3**
- `project.id`: **11** Kafaat (confidence 0.97)
- **`items`: 2**
  1. bug / create_work — RPC Error بسبب ملفات مفقودة — src `[9181,9182]` — AC+tests non-empty — evidence includes `.../index.html` FileNotFoundError
  2. bug / create_work — عدم ظهور جميع البرامج في شاشة Batch Intake — src `[9184]` — AC+tests non-empty
- `ignored_messages`: `[9185]` (done voucher note)
- `requires_human_review`: true

---

## Gate 2 — Controlled auto-analysis (Test Dev Needed)

Configured on source `#9`:

| Setting | Value |
|---------|-------|
| `ai_triage_enabled` | **true** |
| `auto_analysis_enabled` | **true** |
| `analysis_review_only` | **true** |
| `analysis_debounce_minutes` | **3** |
| `openproject_create_allowed` | **false** |
| `analysis_prompt_version` | `wa_project_aware_v3.0` |

Verified:
1. New ingest message `9258` (UAT debounce ping) → Hub ok  
2. Debounce scheduled (`pending_analysis_after` set)  
3. Reset on re-schedule moves/keeps window  
4. Pending cleared after UAT to avoid flushing entire Dev Needed backlog  
5. Invalid empty-AC v3 payload → **ValidationError** (`items[0].acceptance_criteria must be a non-empty list`)  
6. `assert_create_allowed` under review_only → **UserError** (no auto WI/task/OP)  
7. WI/task delta during UAT: **0**

---

## Gate 3 — Review-mode work linkage UAT

On analysis **#390** (fingerprint-stable native v3):

| Check | Result |
|-------|--------|
| Orchestration decision | `request_review` |
| review_only | true |
| Dev Hub WI matches | 0 |
| Odoo task matches | 0 |
| OpenProject matches | 0 |
| Recommended OP parent | `project:10 parent:#87 — edafa_kafaat_parent` |
| Per-item actions | both `create_work` (review only) |
| Auto create | **blocked** |
| Explicit Test create | **not executed** — no safe auto-create target under review_only; search/recommend only |

Rollback/archive: no create occurred → nothing to roll back. Analyses `#383`/`#387` untouched. Pending jobs on `#390`/`#392` marked succeeded to prevent n8n overwrite of native v3 apply.

---

## Gate 4 — Path evaluation normalization

`dev.whatsapp.analysis.eval._paths_equivalent`:
- basename `index.html` ≡ `/opt/.../index.html` → True  
- identical paths → True  
- different module trees same basename → **False**  
- scoring `#383` vs `#390` paths component → **20/20**

---

## Gate 5 — Final Kafaat comparison

Canonical new analysis: **#390** (fingerprint `df1b9316…`; re-enqueue without force returns `#390`)  
Force variant `#392` also holds same native items (kept for audit).

| Area | #383 | #387 | #390 Native Dify v3 | Cursor reference | Status |
|------|------|------|---------------------|------------------|--------|
| Project | Kafaat 11 | Kafaat 11 | Kafaat 11 | Kafaat | Fixed |
| Native number of items | 1 (implicit) | 1 LLM / multi forced | **2 items[]** | multi | Fixed |
| Server-forced multi-task | false | true | true (`len(items)=2`) | true | Fixed |
| RPC evidence | weak | merged extract | native item 0 + FileNotFoundError paths | exact | Fixed |
| File paths | missing | extracted | `index.html` in technical_evidence; basename score 20 | index.html + html4css1 | Fixed / Partial* |
| Acceptance criteria | empty | present (server/Dify mix) | native non-empty per item | complete | Fixed |
| Test requirements | empty | partial | native non-empty per item | present | Fixed |
| Questions | empty | injected | review questions stored | targeted | Fixed |
| Source message citations | weak | yes | per-item `[9181,9182]` / `[9184]` | required | Fixed |
| Validation state | pending/valid-ish | needs_review | **needs_review** | review | Fixed |
| Safe to create | true (unsafe) | false | **false** | blocked until review | Fixed |
| Odoo linkage | none | search | search only | decision | Partial |
| Dev Hub linkage | none auto | search | search only | decision | Partial |
| OpenProject linkage | none | parent 87 rec | **parent #87 / project 10 recommended** | OP#10 / #87 | Partial (recommend) |
| Overall score | **20** | **100** | **100** | ≥85 | Met |

\* `html4css1.css` is in message `#9187` / extract; native item 0 cites `index.html` FileNotFoundError explicitly. Basename scoring treats path forms as equivalent.

### Exact native `items[]` (Dify → stored on #390)

See `dify_v3_kafaat_result.json` and `analysis_items_json` on `#390` — identical 2-item structure applied via `validate_ai_response` + `_apply_validated`.

---

## Production readiness decision

```text
NOT READY
```

### Why not READY
1. **Clean Test observation period** not completed — flags enabled today; need ≥1 quiet Test day with debounce live and no surprise WI/OP creates.  
2. **Explicit controlled create UAT** not run (intentionally blocked by review_only; no Test OP write performed).  
3. **Production Evolution URL/key audit** planned but not executed on Prod DB.  
4. Production module upgrade not performed (as required).

### READY checklist status
| Criterion | Status |
|-----------|--------|
| Native Dify v3 `items[]` works | **Yes** |
| Test auto-analysis review mode works | **Yes** (configured + debounce verified) |
| No duplicate analysis (fingerprint) | **Yes** (`#390` reused) |
| No duplicate work creation | **Yes** (blocked; delta 0) |
| Evolution Prod URL/key audit plan | **Yes** (plan below) |
| Migrations verified on Test | **Yes** |
| Backup + rollback plan | **Yes** (Test dump `pet_spot_elsahel_test_pre_ai_pipeline_20260726T043521Z.dump`; Dify prompt backups) |
| One clean Test observation period | **No** |

### Evolution Production audit plan (before any Prod upgrade)
1. Backup Prod DB.  
2. Inspect `whatsapp.instance` + ICP `integration_bridge.evolution_*` — reject `:9` stubs.  
3. Confirm instance `sabry min` (or Prod name) URL `http://127.0.0.1:8080` or correct Prod Evolution host + real API key.  
4. Dry-run `whatsapp.evolution.recovery.recover_conversation` on one Test-mirrored group first.  
5. Upgrade `whatsapp_hub` + `devhub_whatsapp` + restart Odoo for bridge webhook fan-out.  
6. Keep Prod `ai_triage_enabled=false` until Test observation passes.

### Safest next actions
1. Leave Test Dev Needed flags as configured; monitor debounce for 24h.  
2. Optionally run one **manual** approve_create_work on a Test-only WI with `wa_orchestration_force` after picking a disposable Test project.  
3. Only then reconsider Production.
