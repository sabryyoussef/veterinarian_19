# Delivery Report — Project-Aware WhatsApp AI Analysis (Test)

**Last verified:** 2026-07-24 (finalization)  
**Database:** `pet_spot_elsahel_test`  
**Production / OpenProject:** untouched

This document distinguishes **current verified state** from **historical baseline**. Earlier drafts that said “n8n not live” or module `19.0.9.2.14` / `6/6` tests are **obsolete**.

---

## Current verified state (2026-07-24)

| Area | Status |
|------|--------|
| Odoo modules | `devhub_work` **19.0.9.1.4**, `devhub_whatsapp` **19.0.9.2.18** (manifest = `ir.module.module.latest_version`) |
| Git | Implementation committed on `feature/wa-work-inbox` (`feat(devhub): add project-aware WhatsApp AI analysis`) |
| Source mappings | Corrected P0 table below (live Test DB) |
| Aliases | `dev.project.alias` — **29** rows, unique `normalized_name` |
| Schema | v1 + **v2** validator; candidate-only project/WI IDs; foreign-ID rejection |
| Fixture gate | ICP `devhub_whatsapp.allow_fixture_ai=False`; DEMO UI badge when `is_demo_result` |
| Dify | **Live** canonical app `dee250c0-7f44-467c-9b0b-86f069bdc17e` (labelled `[CANONICAL TEST]`) |
| n8n | **Live active** workflow `devhub-wa-project-aware-analysis-test` id **`j3xV5kXRQUu1k0p4`** |
| E2E | Real runs with `provider=dify_n8n` (analyses 25 / 26 / 28) |
| Tests | Full `/devhub_whatsapp` suite: **31 passed, 0 failed, 0 errors** (~16s) |

### Canonical runtime IDs

| Component | ID |
|-----------|-----|
| Dify app (canonical) | `dee250c0-7f44-467c-9b0b-86f069bdc17e` |
| Dify workflow | `5f747cb0-4b84-4fc5-99d5-48d30e1b3c15` |
| n8n workflow | `j3xV5kXRQUu1k0p4` (active, 1-min poll) |
| Smoke Dify run | `c6dd524c-b476-44b7-8424-87ee2e72e3f6` |

### Example E2E correlation (sanitized)

```text
analysis 28 → job 23 → correlation 21ee7668-0b4b-4cc1-909a-d1d26e7564f6
→ n8n 50697 → Dify ed79bdb0-ee9d-43ec-bb64-b80f46897ee1
→ provider=dify_n8n → schema 2 → project ASTA → applied (WI 3344)
```

Also certified: analysis **25** / job **20** / n8n **50645** / Dify `460e8a5a-…` → AZONE attach WI **3291**.

---

## Historical baseline (before project-aware work)

- All 14 WA sources mapped to PetSpot
- Analyses completed via fixture/demo (`provider_model=fixture`)
- Dify “Dev Hub WhatsApp Triage” was docs-only
- n8n WA analysis workflow **not** live (pre-2026-07-24 E2E completion)
- Schema v1 triage-only

---

## Corrected WhatsApp source mappings (P0) — still current

| ID | Group | Project code | Mapping state | Conf |
|----|-------|--------------|---------------|------|
| 1 | Testopenclow | PETSPOT | confirmed | 1.0 |
| 2–3 | Clinic UAT | PETSPOT | confirmed | 1.0 |
| 4 | Alzaeem | PETSPOT | **unmapped** (AI blocked) | 0 |
| 5 | Asta development | **ASTA** | confirmed | 1.0 |
| 6 | AZone - WorldPosta | **AZONE** | confirmed | 1.0 |
| 7 | Bright&I zone | **AZONE** | confirmed | 0.95 |
| 8 | Cycle X | **CYCLEX** | confirmed | 1.0 |
| 9 | Dev Needed | PETSPOT | **ambiguous** (AI blocked) | 0.35 |
| 10 | Izone Internal | **AZONE** | confirmed | 1.0 |
| 11,14 | PetSpot Sahel | PETSPOT | confirmed | 1.0 |
| 12 | Torz Trading | **TOURZ** | confirmed | 0.95 |
| 13 | انهاء مشروع ASTA | **ASTA** | confirmed | 1.0 |

AI enabled for UAT on confirmed: Testopenclow, AZone, Asta development.

---

## Odoo implementation (committed)

Primary modules: `devhub_work`, `devhub_whatsapp` (+ dependency `devhub_analysis`).

- `devhub_work/models/dev_project_alias.py`, views, seed, security  
- `devhub_whatsapp/models/dev_whatsapp_source.py` (mapping + AI gate)  
- `devhub_whatsapp/models/dev_whatsapp_analysis_utils.py` (schema v1+v2)  
- `devhub_whatsapp/models/dev_whatsapp_analysis.py` / `_job.py` / `_segment.py` / `_candidates.py` / `_context.py`  
- data: `dev_whatsapp_p0_mapping.xml`, `ir_config_parameter_ai.xml`

---

## Dify & n8n

| Artifact | Detail |
|----------|--------|
| Dify app | **Dev Hub WhatsApp Project Resolver [CANONICAL TEST]** |
| App ID | `dee250c0-7f44-467c-9b0b-86f069bdc17e` |
| Duplicate | `8dfa0b80-…` labelled obsolete; `enable_api=false` (retained for audit; not used by n8n) |
| Model | `openai` / `gpt-4o-mini` (Start → LLM → End) |
| Env key | `DIFY_API_KEY_DEVHUB_WA_RESOLVER` (n8n env; not committed) |
| n8n | **Active** `j3xV5kXRQUu1k0p4` — lease → Dify → `service_complete` / `service_fail` |
| Outline only | `n8n_devhub_wa_project_aware_analysis_test.json` (sanitized outline; not the live definition) |
| Live sanitized export | `n8n_devhub_wa_project_aware_analysis_test.live.json` |

---

## Fixture / demo

- ICP `devhub_whatsapp.allow_fixture_ai=False` on Test  
- Fixture/demo actions blocked unless ICP enabled  
- Legacy rows (21, 23, 24) labelled `provider=fixture`, `provider_model=fixture`, `is_demo_result=true`  
- Browser: DEMO banner visible on analysis 24; **absent** on live analysis 25  

---

## Automated tests (finalization)

Command:

```bash
cd /home/sabry/odoo_base/base_odoo_19
./venv19/bin/python3 odoo19/odoo19/odoo-bin \
  -c config/projects/pet_spot_elsahel_test.conf -d pet_spot_elsahel_test \
  --http-port=18028 --gevent-port=18072 \
  --test-enable --stop-after-init --without-demo=all \
  --test-tags=/devhub_whatsapp
```

**Result:** `0 failed, 0 error(s) of 31 tests` (~16s wall).  
Classes: `TestWhatsappProjectAwareAi` (11), `TestWhatsappAiAnalysis` (7), `TestDevhubWhatsappIntake` (4), `TestWhatsappWorkInbox` (9).  
Log: `docs/.../work_inbox/finalization_tests_devhub_whatsapp.log`

Stale claim `6/6` referred to an earlier subset of `TestWhatsappProjectAwareAi` only.

---

## Known limitations

- Production does **not** have this stack installed (`devhub_whatsapp` still 19.0.9.1.9 there)  
- Dev Needed remains ambiguous by design; Alzaeem unmapped until a Dev Hub project exists  
- Multi-topic (scenario H) only partially covered  
- Playwright Chromium unsupported on this host OS; browser UAT used Firefox + session cookie  
- Other untracked Dev Hub modules (`devhub_core`, etc.) remain outside this commit scope  

## Optional future improvements

- Promote to Production only after explicit approval  
- Remove obsolete Dify duplicate after retention window  
- Expand automated coverage for dead-letter / multi-segment edge cases  

## Rollback (Test)

1. Set `ai_triage_enabled=False` on sources  
2. Deactivate n8n workflow `j3xV5kXRQUu1k0p4`  
3. Optional: revert Git commit / disable module features  
4. Do **not** touch Production or OpenProject  

## Confirmation

- Production Odoo: not upgraded for this feature; PID unchanged during Test test-run  
- OpenProject: no nodes / no writes from this path  
- Work Package = `dev.work.item` only  
