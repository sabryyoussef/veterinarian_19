# Delivery Report — AI WhatsApp Analysis → Dev Hub Work Items (Test)

**Date:** 2026-07-24  
**Database:** `pet_spot_elsahel_test` only  
**Production:** untouched

## 1. Baseline (before)

| Module | Test | Prod |
|--------|------|------|
| devhub_whatsapp | 19.0.9.2.8 | 19.0.9.1.9 |
| devhub_work | 19.0.9.1.2 | 19.0.9.1.1 |
| devhub_generation | 19.0.9.1.1 | (unchanged) |

## 2. Architecture implemented

```text
whatsapp.message (eligible new/pending)
  → batch builder (per source)
  → dev.whatsapp.analysis + pending job
  → n8n leases (service APIs) → Dify (JSON only)
  → Odoo validates (untrusted IDs)
  → awaiting_review
  → manager Approve Ignore / Approve & Create Work Item
  → dev.work.item (source_type=whatsapp_ai) on Dev Project Work Items tab
  → later deep analysis via analysis_source_mode work_item|either
```

OpenProject is never written by this path.

## 3. Files changed (primary)

- `devhub_work/models/dev_work_origin.py`, `views/dev_work_origin_views.xml`, `__manifest__.py`
- `devhub_whatsapp/models/dev_whatsapp_analysis*.py`, `dev_whatsapp_work_item.py`, source/inbox updates
- `devhub_whatsapp/views/dev_whatsapp_analysis_views.xml`, menus, security
- `devhub_generation/models/dev_generation_service.py` (`analysis_source_mode`)
- Docs: `DIFY_DEVHUB_WA_TRIAGE.md`, `n8n_devhub_wa_analysis_test.json`

## 4. Versions after (Test)

| Module | Version |
|--------|---------|
| devhub_whatsapp | **19.0.9.2.9** |
| devhub_work | **19.0.9.1.3** |
| devhub_generation | **19.0.9.1.2** |

## 5. Migration

ORM upgrade created tables/fields for `dev.whatsapp.analysis`, `dev.whatsapp.analysis.job`, work origin fields, source AI flags, project `analysis_source_mode` / `work_item_ids`. No raw SQL migration scripts.

## 6. Tests

`TestWhatsappAiAnalysis`: **7/7 passed** (0 failed, 0 errors).

## 7–8. n8n / Dify

| Artifact | Status |
|----------|--------|
| Dify **Dev Hub WhatsApp Triage** | Spec in docs — create in Studio with dedicated Test key |
| n8n **devhub-wa-analysis-test** | Sanitized inactive outline in docs — **do not activate** until controlled UAT |

Odoo lease APIs are live; fixture path used for UAT without live Dify.

## 9–10. UAT evidence (Test)

- Analysis id **21**, Work Item id **3341** (`UAT WA AI Work Item`)
- `source_type=whatsapp_ai`, `origin_ai_whatsapp=True`, `whatsapp_analysis_id=21`
- `op_work_package_id=0` (none)
- Duplicate approve blocked (`UserError`)
- Pet Spot project `work_item_count` includes new item; `analysis_source_mode=either`

## 11. No OpenProject records created by this flow

Confirmed WI has no OP package id.

## 12. Production untouched

Prod still on `devhub_whatsapp` 19.0.9.1.9 / `devhub_work` 19.0.9.1.1.

## 13. Known limitations

- Live Dify/n8n not wired in Studio yet (docs + inactive workflow only).
- Auto-ignore disabled by default; enable per source after review.
- Work Item creation always requires manager **Approve & Create Work Item**.
- Work Inbox OWL does not yet embed analysis panel (form/menus available).
- Deep analysis still needs repo + env + HEAD snapshot.

## 14. Rollback

1. Set `ai_triage_enabled=False` on all sources.
2. Leave n8n workflow inactive.
3. Optional: reject pending analyses; restore any AI-ignored messages via Restore.

## 15. Enablement recommendation

Enable `ai_triage_enabled` **source-by-source** (start Testopenclow), keep `auto_ignore_enabled=False` until noise quality is proven, then activate n8n Test poller against Odoo Test only.
