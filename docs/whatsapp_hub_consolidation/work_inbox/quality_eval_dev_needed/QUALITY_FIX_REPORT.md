# Quality Fix Delivery — Dev Needed Project/WI Resolution (Test)

**Date:** 2026-07-24  
**Environment:** `pet_spot_elsahel_test` only  
**Module:** `devhub_whatsapp` **19.0.9.2.19 → 19.0.9.2.21**  
**Prompt:** `wa_project_aware_v2` → `wa_project_aware_v2.1` (Dify workflow `5f747cb0-…`, marked `wa_project_aware_v2.1`)  
**Production / OpenProject:** untouched (`devhub_whatsapp=19.0.9.1.9`)  
**Dev Needed mapping:** still `ambiguous`, AI triage off  

Artifacts: `docs/whatsapp_hub_consolidation/work_inbox/quality_eval_dev_needed/results_scored_after.json`

---

## 1. Root-cause confirmation

Two layers caused the baseline gap:

1. **Dify prompt** forced `project_id=null` whenever `requires_project_confirmation=true` (always true for ambiguous sources).
2. **Odoo** always set `requires_project_confirmation=True` for ambiguous sources and never applied an authoritative proposed selection after Dify returned null.

Candidate retrieval was already strong (~93% top match); commitment was over-conservative.

---

## 2. Exact code and prompt changes

| Area | Change |
|------|--------|
| `dev_whatsapp_analysis_candidates.py` | Configurable thresholds; `selection_policy` with `eligible_for_proposed_selection`; strong vs weak evidence; direct WI link project boost; WI candidate ranking + `recommended_work_item_decision` |
| `dev_whatsapp_analysis.py` | Payload carries `selection_policy` + WI recommendations; `_enforce_odoo_resolution_policy` fills proposed project / existing WI; confirm/reject/choose project actions; eval uses `DEFAULT_PROMPT_VERSION` |
| `dev_whatsapp_analysis_segment.py` | Alias-switch segment boundaries |
| `dev_whatsapp_analysis_utils.py` | `normalize_classification_v2`; noise empty-summary default; prompt version `wa_project_aware_v2.1` |
| `ir_config_parameter_ai.xml` | `unique_candidate_min_score=0.70`, `strong_candidate_min_score=0.85`, `candidate_score_margin=0.20` |
| UI | Proposed-project banner + Confirm / Choose Different / Reject Resolution |
| Dify | Prompt updated in DB (published + draft); removed “confirmation ⇒ null project” rule |
| Tests | `test_whatsapp_resolution_policy.py` |

Human review and evaluation mutation blocks remain.

---

## 3–5. Versions and tests

| Item | Value |
|------|-------|
| Module before | `19.0.9.2.19` |
| Module after (Test) | `19.0.9.2.21` |
| Dify prompt | `wa_project_aware_v2.1` |
| Automated tests | **0 failed, 0 errors** (`/devhub_whatsapp`, 40 counted / 50 methods) |

---

## 6–8. Re-evaluation and metrics

Re-ran DN-01…DN-29 through Odoo → n8n `j3xV5kXRQUu1k0p4` → Dify `dee250c0-…` → `service_complete`  
(`provider=dify_n8n`, `schema_version=2`). Focus re-runs applied for DN-15/16/18/25/19/02 after WI-link ranking fix.

| Metric | Before | After | Delta |
|--------|-------:|------:|------:|
| Project resolution accuracy | 41.4% | **93.1%** | +51.7 |
| Top candidate match | 93.1% | 93.1% | 0 |
| False project assignment | 0% | **6.9%** | +6.9 |
| WI decision accuracy | 10.3% | **55.2%** | +44.9 |
| Existing WI selection | 0% | **100% (2/2)** | +100 |
| Normalized classification accuracy | — | 31.0% | — |
| JSON validity | 100% | **100%** | 0 |
| Cross-project leakage | 0% | **0%** | 0 |
| Unsupported claims | 0% | **0%** | 0 |
| Average usefulness | 3.52 | **3.83** | +0.31 |
| Usefulness ≥4 | 41.4% | **62.1%** | +20.7 |
| Human correction rate | 89.7% | **44.8%** | −44.9 |

Result mix: **PASS 16 · PARTIAL 11 · FAIL 2**

### Acceptance vs targets

| Criterion | Target | Result |
|-----------|--------|--------|
| Project accuracy ≥85% | 85% | **93.1%** Pass |
| False project ≤3% | 3% | **6.9%** Fail (DN-18, DN-25) |
| Cross-project leak =0% | 0% | **0%** Pass |
| JSON =100% | 100% | **100%** Pass |
| WI decision ≥70% | 70% | **55.2%** Fail |
| Existing WI both correct | 2/2 | **2/2** Pass |
| Avg usefulness ≥4.0 | 4.0 | **3.83** Fail |
| No inbox/WI mutation | yes | **yes** Pass |
| Prod/OP untouched | yes | **yes** Pass |

---

## 9. Remaining failures

- **DN-18 / DN-25:** truth `unknown` + `none`/`unclear`, but AI/Odoo proposed ASTA from alias while classifying as non-noise (`unclear`/`new`). Counts as false project assignment.
- **WI decision still ~55%:** many truth `unclear` vs AI `none`/`existing` mismatches on weak segments; actionable `new` improved but not enough for 70%.
- **Classification 31%:** taxonomy normalized, but Dify class choices still diverge from reviewer labels on mixed segments.

---

## 10. Final verdict

**Ready only with mandatory human review**

Project commitment is fixed for clear alias / WI-linked segments (93% project accuracy; both existing-WI samples correct). Not ready for broader unsupervised Test use or Production: false-project rate, WI decision accuracy, and usefulness still miss gates.

Broader Test use on **confirmed single-project** sources remains appropriate; multi-project Dev Needed still needs human confirmation on every analysis.

---

## 11–12. Safety confirmation

- Dev Needed: `ambiguous`, `ai_triage_enabled=false`
- Evaluation applied / WI attached: **0**
- Production module version unchanged: **19.0.9.1.9**
- OpenProject: not written
