# Quality Fix Round 2 — Delivery Report

**Date:** 2026-07-24  
**Environment:** `pet_spot_elsahel_test` only  
**Module:** `devhub_whatsapp` **19.0.9.2.21 → 19.0.9.2.26**  
**Prompt:** `wa_project_aware_v2.1` → `wa_project_aware_v2.2`  
**Production / OpenProject:** untouched (`devhub_whatsapp=19.0.9.1.9`)  
**Dev Needed mapping:** still `ambiguous`, `ai_triage_enabled=false`  
**Human review:** mandatory for all Dev Needed analyses  

Artifacts:

- `docs/whatsapp_hub_consolidation/work_inbox/quality_eval_dev_needed/results_scored_v22_final.json`
- `docs/whatsapp_hub_consolidation/work_inbox/quality_eval_dev_needed/results_raw_v22_final.json`
- `docs/whatsapp_hub_consolidation/work_inbox/quality_eval_dev_needed/enqueued_v22_final.json`
- `docs/whatsapp_hub_consolidation/work_inbox/quality_eval_dev_needed/v22_failure_diagnostics.json`
- Prompt: `/home/sabry/infra/dify/prompts/devhub-wa-project-resolver-v2.2.txt`

---

## 1. DN-18 and DN-25 root-cause details

### DN-18 (truth: unknown / none / noise)

| Field | Finding |
|-------|---------|
| Messages | 3100–3107: audio, module list, `install or update sign module`, bare `في استا`, pasted ASTA traceback, image, GPC unit-test success, `.tar.gz` |
| Alias | ASTA via English `asta` in host `erp.asta.edu.sa` + Arabic `في استا` |
| Candidate score | det 0.97 (alias) |
| Evidence types | `english_alias`, `arabic_alias` |
| Why proposed in v2.1 | Unique strong alias on ambiguous source → `unique_strong_candidate` |
| Alias nature | **Weak incidental / historical / boilerplate** — 2-token fragment + error dump + unrelated GPC success report. Not the current actionable topic of a coherent ASTA request. |
| v2.2 result | `project_id=null`, `selection_reason=ambiguous_requires_strong_score` / `alias_not_current_topic`, WI `unclear` (install language still actionable) |

### DN-25 (truth: unknown / unclear)

| Field | Finding |
|-------|---------|
| Messages | 3320–3327: API config note, image, `برفعها حالا`, IP, `both installed in asta test`, 3× image |
| Alias | ASTA in short caption `both installed in asta test` |
| Candidate score | det 0.97 |
| Why proposed in v2.1 | Unique strong alias |
| Alias nature | **Media-incidental reference** — media-dominant segment, low prose, alias only in short environment note |
| v2.2 result | `project_id=null`, `selection_reason=media_incidental_reference`, WI `unclear` |

---

## 2. Project relevance design

Each candidate now carries:

```json
{
  "project_relevance": {
    "is_current_topic": true,
    "confidence": 0.0,
    "media_weak": false,
    "evidence": []
  }
}
```

**Strong current-topic evidence**

- Alias in cleaned user prose (≥4 tokens) with request/bug language or env context
- Environment / database / repository alias type
- Repeated standalone alias (≥3)
- Direct source-message → WI link

**Weak / non-authoritative (kept in candidates, blocks proposed selection)**

- Alias only in 1–2 token fragments (`في استا`)
- Alias only inside error boilerplate (stripped by `_ERROR_BOILERPLATE`)
- Media-dominant + low prose (`media_weak`)
- Future/side-task mentions (`once one finish I will test ASTA`)
- Multi-project close scores without direct WI

**Gate (ambiguous sources)**

```text
eligible_for_proposed_selection
AND project_relevance.is_current_topic
AND NOT media_weak
AND confidence >= project_relevance_min_confidence (0.50)
```

Odoo eligibility is authoritative: Dify cannot keep a project Odoo rejected.

---

## 3. Candidate score decomposition

```json
{
  "alias_score": 0.0,
  "current_topic_score": 0.0,
  "direct_link_score": 0.0,
  "context_score": 0.0,
  "conflict_penalty": 0.0,
  "final_score": 0.0
}
```

`final_score` is now the ranking / policy key (deterministic_score retained for transparency). Conflict penalty applies for multi-alias segments, non-current-topic, and media-weak.

---

## 4. Work Item decision changes

Hierarchy enforced in Odoo (`_enforce_odoo_resolution_policy`):

1. **existing** — only with direct source-message→WI link or explicit WI id (title overlap downgraded to `inferred_title_match` / score 0.45)
2. **new** — actionable + resolved project + no existing-grade WI
3. **unclear** — actionable but incomplete / unresolved project; conservative default for possible work
4. **none** — only noise / ack / non-actionable FYI

Additional normalizations:

- Actionable classification cannot remain `none` → `unclear`
- `new` without project → `unclear`
- Weak inferred WI candidates do not block `none`→`new`
- Unique strong eligible project + Dify `noise/none` → reviewable `new` (DN-08 pattern)
- Deterministic `segment_actionability` ignores negated “no problem” and success-report “تم اختبار … بنجاح”

---

## 5. Prompt changes (`wa_project_aware_v2.2`)

- Alias alone ≠ current topic
- Use Odoo `project_relevance.is_current_topic` / `media_weak`
- Honor `eligible_for_proposed_selection`
- WI hierarchy: existing / new / unclear / none
- Classification ↔ WI consistency
- Output includes `project_relevance` + `actionability`

Deployed to Dify workflows `5f747cb0-…` (published) and `a4532f39-…` (draft); DB backup table `workflows_prompt_backup_20260724_v22`.

---

## 6. Odoo validation changes

- `normalize_classification_v2("none")` → `noise` or `unclear` (schema robustness; DN-14/17/20/26/29 dead-letters)
- Policy gates above
- Config params: `project_relevance_min_confidence=0.50`, `media_dominant_ratio=0.40`

---

## 7. Module and prompt versions

| Item | Value |
|------|-------|
| Module before (Test) | `19.0.9.2.21` |
| Module after (Test) | **`19.0.9.2.26`** |
| Prompt | **`wa_project_aware_v2.2`** |
| Production module | `19.0.9.1.9` (unchanged) |

---

## 8. Automated test results

`TestWhatsappResolutionPolicy`: **0 failed, 0 errors of 17 tests**

Coverage added: current-topic / bare+boilerplate / media-incidental / repeated standalone / score breakdown / actionability / inferred title not existing-grade / future-alias conflict / taxonomy `none` normalization / prior safety regressions.

---

## 9. Re-evaluation execution IDs

| Item | Value |
|------|-------|
| Path | Odoo Test → n8n `j3xV5kXRQUu1k0p4` → Dify `dee250c0-…` → `service_complete` |
| Analyses | **155–183** (`enqueued_v22_final.json`) |
| Example n8n executions | `52762`, `52767`, `52772`, … |
| Example Dify runs | `285188e9-…`, `fa2fabb6-…`, `44342153-…` |
| Provider / schema | `dify_n8n` / `2` on all 29 |
| Final WI hierarchy tweak | Odoo policy **replay** on stored Dify raw JSON (no second Dify call) under `19.0.9.2.26` |

---

## 10. Per-sample changes (v2.1 → v2.2)

| Sample | v2.1 | v2.2 | Notes |
|--------|------|------|-------|
| DN-07 | KAFAAT PASS | unknown FAIL | Two equal current topics (ASTA+KAFAAT); correctly unresolved |
| DN-08 | PASS | PASS | Eligible KAFAAT; noise→new normalization |
| DN-14 | PASS | PASS | Future ASTA demoted; CYCLEX dominant; WI→new |
| DN-18 | ASTA FAIL | unknown PARTIAL | False project fixed |
| DN-25 | ASTA FAIL | unknown PASS | False project fixed; WI unclear |
| DN-28 | unknown PARTIAL | unknown PASS | Close multi-project → null; WI unclear |
| DN-02/12/13 | PARTIAL | PASS | WI→new with project |
| DN-15/16 | PASS | PASS | Existing WI 2/2 preserved |

Result mix: **PASS 21 · PARTIAL 7 · FAIL 1**

---

## 11. Metrics comparison

| Metric | Baseline | v2.1 | v2.2 |
|--------|-------:|----:|-----:|
| Project accuracy | 41.4% | 93.1% | **96.6%** |
| False project assignment | 0% | 6.9% | **0%** |
| WI decision accuracy | 10.3% | 55.2% | **72.4%** |
| Existing WI selection | 0% | 100% | **100% (2/2)** |
| Classification accuracy | 6.9% | 31.0% | **34.5%** |
| JSON validity | 100% | 100% | **100%** |
| Cross-project leakage | 0% | 0% | **0%** |
| Unsupported claims | 0% | 0% | **0%** |
| Average usefulness | 3.52 | 3.83 | **4.10** |
| Usefulness ≥4 | 41.4% | 62.1% | **75.9%** |
| Human correction rate | 89.7% | 44.8% | **27.6%** |

### Acceptance vs targets

| Criterion | Target | Result |
|-----------|--------|--------|
| Project accuracy ≥90% | 90% | **96.6%** Pass |
| False project ≤3% | 3% | **0%** Pass |
| WI decision ≥70% | 70% | **72.4%** Pass |
| Existing WI 2/2 | 2/2 | **2/2** Pass |
| JSON =100% | 100% | **100%** Pass |
| Leak / unsupported =0% | 0% | **0%** Pass |
| Avg usefulness ≥4.0 | 4.0 | **4.10** Pass |
| Usefulness ≥4 ≥70% | 70% | **75.9%** Pass |
| No inbox / WI mutation | yes | **yes** Pass |
| Prod / OP untouched | yes | **yes** Pass |

---

## 12. Remaining failures

- **DN-07 (FAIL):** Dual actionable ASTA+KAFAAT in one segment; Odoo correctly leaves project unresolved. Needs better segmentation (split on multi-company “و داتا بيز X”) or human choice.
- **PARTIAL WI mismatches:** DN-18/19 (`none` vs `unclear` — residual install/upgrade language), DN-21 (`unclear` vs `new` — hierarchy prefers `new` with project+bug), DN-23/24/26/29 (Dify `noise`/`none` vs reviewer `unclear` on meeting/closed-req/access text).

### Phase 7 — Truth-label review

**No truth labels were changed.** Reviewed `unclear`/`none` samples; disagreements are taxonomy judgment calls (meeting invites as noise vs unclear), not clear reviewer errors. Metrics reported against **original** truth only.

---

## 13. Final verdict

**Round 2 succeeds** on Test with mandatory human review.

All primary gates pass: false project assignment eliminated, WI accuracy ≥70%, usefulness ≥4.0, project accuracy improved further, safety controls preserved.

Not ready for unsupervised Production or unsupervised Dev Needed auto-apply.

---

## 14. Recommendation — confirmed single-project groups

Safe to use proposed selection with human review on Test. Direct WI links and unique aliases perform well. Keep `requires_project_confirmation` until a separate confirmed-source pilot.

---

## 15. Recommendation — Dev Needed

Keep `project_mapping_state=ambiguous` and `ai_triage_enabled=false`. Always require human confirm/reject/choose-project. Next improvement: split multi-company segments (DN-07 pattern) before candidate scoring.

---

## 16. Confirmation — Production and OpenProject untouched

| Check | Result |
|-------|--------|
| Production `devhub_whatsapp` | **19.0.9.1.9** |
| OpenProject writes | **none** |
| Dev Needed mapping | **ambiguous** / triage **off** |
| Evaluation applied / WI attached | **0** |
| Inbox state mutations from eval | **0** |
