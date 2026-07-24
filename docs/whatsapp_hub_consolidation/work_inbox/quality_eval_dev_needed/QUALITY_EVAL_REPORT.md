# Quality Evaluation — Dev Needed Historical WhatsApp Messages (Test)

**Date:** 2026-07-24  
**Environment:** `pet_spot_elsahel_test` only  
**Source:** Dev Needed (id=9) — mapping left `ambiguous`, `ai_triage_enabled=false`  
**Mode:** `historical_quality_evaluation`  
**Pipeline:** Odoo → n8n `j3xV5kXRQUu1k0p4` → Dify `dee250c0-…` → `service_complete`  
**Production / OpenProject:** untouched  

Artifacts: `docs/whatsapp_hub_consolidation/work_inbox/quality_eval_dev_needed/`

---

## 1. Dataset summary

### Phase 1 inventory (sanitized)

| Metric | Value |
|--------|------:|
| Date range | 2026-03-30 → 2026-07-23 |
| Total messages | 3428 |
| Senders | 11 |
| Media messages | 790 |
| Reply-linked | 0 |
| Linked to Work Items | 3 msgs (WI 3331/3332, PETSPOT) |
| Actioned / ignored | 3 / 2 |
| Untriaged | 3224 |
| Long gaps ≥6h | many (weekly volume varies) |

**Alias hit distribution (message body):** ASTA 116, KAFAAT 88, ALSHMOUKH 9, CYCLEX 8, AZONE/PETSPOT/TOURZ **0**.

### Selected samples

| | |
|--|--:|
| Selected samples | **29** (target 20–30) |
| Languages | mostly Arabic / mixed (see scored JSON) |
| Expected projects | ASTA, KAFAAT, CYCLEX, PETSPOT (WI-linked), unknown |
| Excluded | bulk consecutive dumps; tokenized URLs/phones sanitized in excerpts |

Category mix included: ASTA/KAFAAT/CYCLEX alias segments, WI-linked follow-ups, noise, questions, media-only, no-project, boundary/gap, one mixed-alias window.

---

## 2. Per-sample result table (summary)

Full table: `results_scored.json` → `rows`.

| Sample | Expected project | AI project | Expected WI | AI WI | Class (coarse) | Evidence | Usefulness | Result |
|--------|------------------|------------|-------------|-------|----------------|----------|------------|--------|
| DN-01…05 | ASTA | unknown | new | none | mostly mismatch* | ok | 2–3 | FAIL |
| DN-06…10 | KAFAAT | unknown | new | none | * | ok | 2–3 | FAIL |
| DN-11…14 | CYCLEX | unknown | new | none | * | ok | 2–3 | FAIL |
| DN-15…16 | PETSPOT (WI) | unknown | existing | none | * | ok | 2 | FAIL |
| DN-17…20,23… | unknown | unknown | none/unclear | none/existing | mixed | ok | **4–5** | PASS/PARTIAL |
| DN-21 | ASTA | unknown | unclear | none | * | ok | 2–3 | FAIL |

\*Classification truth used coarse labels (`bug`/`feature`); AI returned schema-v2 labels (`bug_report`, `context_addition`, …). Structural JSON was valid; label taxonomy mismatch inflated class error.

**Headline counts:** PASS **3** · PARTIAL **9** · FAIL **17**

---

## 3. Execution evidence

All 29 samples completed with:

```text
provider = dify_n8n
schema_version = 2
is_evaluation_result = true
is_demo_result = false
```

Examples:

| Sample | Analysis | Job | n8n | Dify run |
|--------|----------|-----|-----|----------|
| DN-01 | 37 | 32 | 50956 | `90cb1ebf-…` |
| DN-02 | 38 | 33 | 51031 | `6c6452fc-…` |
| DN-03 | 39 | 34 | 51141 | `41b2067d-…` |
| DN-17 | (see JSON) | … | … | … |
| DN-29 | 65 | … | … | … |

Average provider latency ≈ **6.1s**. Full IDs in `results_scored.json`.

---

## 4. Metrics dashboard

| Metric | Num | Den | Rate |
|--------|----:|----:|-----:|
| Project detection accuracy (committed `resolved_project_id`) | 12 | 29 | **41.4%** |
| Top-candidate match (retrieval) | 27 | 29 | **93.1%** |
| Candidate alignment (expected ∈ candidates / unknown handled) | 29 | 29 | **100%** |
| False project assignment | 0 | 29 | **0%** |
| Ambiguous-project precision (unknown + confirmation) | 12 | 12 | **100%** |
| Work Item decision accuracy | 3 | 29 | **10.3%** |
| Existing WI selection accuracy | 0 | 2 | **0%** |
| Classification accuracy (coarse taxonomy) | 2 | 29 | **6.9%** |
| Multi-task detection accuracy | 28 | 29 | **96.6%** |
| Structured JSON validity | 29 | 29 | **100%** |
| Unsupported-claim rate (fabricated project id) | 0 | 29 | **0%** |
| Cross-project leakage rate | 0 | 29 | **0%** |
| Evidence coverage | 29 | 29 | **100%** |
| Avg usefulness (1–5) | — | — | **3.52** |
| Usefulness ≥4 | 12 | 29 | **41.4%** |
| Human correction rate (not PASS) | 26 | 29 | **89.7%** |

### By language / category

See `results_scored.json` → `by_language`, `by_category`.

---

## 5. Best results (sanitized)

1. **DN-17 / DN-18 / DN-20 (unknown)** — AI correctly withheld project (`unknown`), schema v2 valid, no fabricated IDs, usefulness 5. Good conservative behaviour when evidence is media/ack-only.
2. Samples where AI kept `requires_project_confirmation` and did not invent AZONE/PETSPOT despite Dev Needed’s PetSpot FK baseline.

**Why they worked:** empty/weak alias evidence + confirmation gate → no false project.

---

## 6. Weak results (confirmed root cause)

| Samples | Observed | Confirmed root cause |
|---------|----------|----------------------|
| DN-01…14 (ASTA/KAFAAT/CYCLEX) | Expected project in **candidates** (often sole candidate) but AI `resolved_project_id` null; WI decision often `none` vs expected `new` | **Prompt/policy + ambiguous-source gate:** Odoo forces `requires_project_confirmation=True` for ambiguous sources; model returns null project rather than selecting the only high-score candidate |
| DN-15…16 | WI-linked PETSPOT messages; AI did not select existing WI | **Missing WI candidate utilisation / decision conservatism** + confirmation gate |
| Class metrics | Low | **Taxonomy mismatch** (truth coarse vs v2 labels) — not primarily model failure |

No fabricated foreign project IDs. No inbox mutations. No Work Items created.

---

## 7. Improvement backlog

### Critical
1. **Ambiguous-source single-candidate selection**  
   - Failed: DN-01…14  
   - Problem: confirmation forced → null project despite sole ASTA/KAFAAT/CYCLEX candidate  
   - Change: allow selecting the unique candidate with score ≥0.7 while keeping `requires_project_confirmation=true` for human approval  
   - Expected: project accuracy → ~90%+ on alias-clear segments without raising false assignment  
   - Effort: S · Regression: medium (must keep multi-candidate null behaviour) · Priority: **Critical**

### High
2. **Work Item decision calibration for multi-project groups**  
   - Failed: most `new`→`none`  
   - Change: when project candidate unique + work language present, prefer `new`/`unclear` over `none`  
   - Effort: M · Priority: **High**

3. **Existing WI follow-up signals**  
   - Failed: DN-15…16  
   - Change: boost `work_item_ids` on messages into WI candidates even when source is ambiguous  
   - Effort: S · Priority: **High**

### Medium
4. **Classification mapping in eval + prompt** — align coarse↔v2 labels for ops dashboards  
5. **Topic segmentation for Dev Needed** — time-gap + alias switches (mixed windows)  
6. **Aliases** — add frequent Dev Needed spellings if any missed (ALSHMOUKH already present)

### Low
7. n8n Split Jobs currently `slice(0,1)` — keep lease limit 1 operationally (already restored)

---

## 8. Final verdict

### **Ready only with mandatory human review**

**Not** ready for Production. **Not** ready for broader unsupervised Test use on multi-project groups.

### Evidence

| Production threshold | Required | Observed | Pass? |
|----------------------|----------|----------|------|
| Project detection ≥90% | 90% | **41.4%** committed | No |
| False project ≤3% | 3% | **0%** | Yes |
| WI decision ≥85% | 85% | **10.3%** | No |
| JSON validity =100% | 100% | **100%** | Yes |
| Cross-project leak =0% | 0% | **0%** | Yes |
| Unsupported claims ≤10% | 10% | **0%** | Yes |
| Avg usefulness ≥4.0 | 4.0 | **3.52** | No |
| ≥80% rated 4–5 | 80% | **41.4%** | No |

**Safety posture is strong** (0 false projects, 0 leakage, 0 fabricated IDs, mapping untouched, inbox unchanged, no WI writes). **Operational usefulness on Dev Needed is blocked** by over-conservative project commitment on ambiguous sources despite excellent candidate retrieval (93% top-candidate / 100% alignment).

### Safety confirmation

- Source 9 still `ambiguous` / AI off  
- 182 sample messages: **0** inbox state changes  
- Evaluation analyses: all `awaiting_review`, **0** applied, **0** work_item_id  
- Provider always `dify_n8n`, schema `2`, not fixture  

### Code added for this evaluation

- `action_enqueue_historical_quality_evaluation` + `is_evaluation_result` / `evaluation_sample_id`  
- Blocks create/attach/ignore for evaluation rows  
- Module Test version **19.0.9.2.19** (commit `849a82f`)
