# E2E Completion — Dev Hub WhatsApp Project-Aware AI (Test)

Date: 2026-07-24  
Environment: `pet_spot_elsahel_test` only. Production untouched. OpenProject untouched.

**Finalization (same day):** implementation committed; Dify duplicate labelled/disabled; legacy fixture rows labelled; `/devhub_whatsapp` **31/31** tests passed; browser DEMO vs live verified. See `PROJECT_AWARE_AI_DELIVERY.md` (current verified state) and `FINALIZATION_CERT.md`.

## Live n8n workflow

| Field | Value |
|---|---|
| Name | `devhub-wa-project-aware-analysis-test` |
| ID | `j3xV5kXRQUu1k0p4` |
| Active | **true** (controlled 1-min poll) |
| Sanitized export | `docs/whatsapp_hub_consolidation/work_inbox/n8n_devhub_wa_project_aware_analysis_test.live.json` |
| Source outline | `n8n_devhub_wa_project_aware_analysis_test.json` |
| Auth | service user `svc-dev-hub-wa-analysis-test` + `DEV_HUB_WA_ANALYSIS_ODOO_API_KEY` (n8n env) |
| Dify key env | `DIFY_API_KEY_DEVHUB_WA_RESOLVER` (present, non-empty) |
| Odoo URL | `DEV_HUB_ODOO_BASE_URL` / `ODOO_TEST_JSON2_BASE` → `https://test.drpaws.ai` |
| DB header | `X-Odoo-Database: pet_spot_elsahel_test` |

## Dify

| Field | Value |
|---|---|
| App | Dev Hub WhatsApp Project Resolver |
| App ID | `dee250c0-7f44-467c-9b0b-86f069bdc17e` |
| Successful run IDs | `460e8a5a-e518-414c-b27c-7b07bb671192` (AZone), `d177803f-ce1e-4edf-bd5f-c46942612952` (ASTA), (analysis 28 run via n8n exec `50697`) |

## Certified E2E path (Scenario A — AZone)

```
Work Inbox Analyse (source 6)
→ analysis 25 / job 20 pending
→ n8n leases (consumer n8n-devhub-wa-project-aware-analysis-test)
→ Dify schema v2
→ service_complete
→ awaiting_review, provider=dify_n8n, project AZONE (id 8)
→ n8n_execution_id=50645, is_demo_result=false
→ Approve & Attach → Work Item 3291 (applied)
```

## Scenario results

| Scenario | Result |
|---|---|
| A AZone | **PASS** — analysis 25, job 20, project AZONE, provider dify_n8n, n8n 50645, Dify `460e8a5a-…`, attach WI 3291 |
| B ASTA | **PASS** — analysis 26, job 21, project ASTA (id 7), n8n 50665, Dify `d177803f-…`, no PetSpot/AZone leak in candidates |
| C Dev Needed | **PASS** — enqueue blocked (`ambiguous` mapping) |
| D Alzaeem | **PASS** — enqueue blocked (`unmapped` mapping) |
| E attach existing | **PASS** — analysis 25 attach to WI 3291 |
| F create new | **PASS** — analysis 28 decision=`new`, ASTA; create approved (see shell UAT) |
| G malformed | **PASS** — `service_complete` with non-JSON → `invalid_schema` / retry; `is_demo_result=false`; no WI |
| H multi-topic | **PARTIAL** — segmentation code covered by unit/helpers; dedicated multi-topic live message not separately asserted in this run |

## Provider values (sanitized)

- `provider=dify_n8n`
- `provider_model=dify-gpt-4o-mini`
- `dify_app_ref=Dev Hub WhatsApp Project Resolver`
- `schema_version=2` / `prompt_version=wa_project_aware_v2`
- Fixture flag `devhub_whatsapp.allow_fixture_ai=False`

## Candidate payload excerpt (AZone job, sanitized)

```json
{
  "schema": "dev-hub-wa-project-aware-request.v2",
  "dev_project_code": "AZONE",
  "dev_project_id": 8,
  "project_candidates": [{"project_id": 8, "code": "AZONE"}]
}
```

## Automated tests

Command:

```bash
cd /home/sabry/odoo_base/base_odoo_19
./venv19/bin/python3 odoo19/odoo19/odoo-bin \
  -c config/projects/pet_spot_elsahel_test.conf -d pet_spot_elsahel_test \
  --http-port=18028 --gevent-port=18072 \
  --test-enable --stop-after-init \
  --test-tags=/devhub_whatsapp:TestWhatsappProjectAwareAi
```

Result: **11 passed, 0 failed, 0 errors**

## Module versions (Test)

- `devhub_whatsapp` **19.0.9.2.18**
- Completion fixes: service `sudo` for candidate fields; language aliases; confidence aliases (`high`→0.85); `ai_work_attached` inbox event

## Files changed during completion

- `devhub_whatsapp/models/dev_whatsapp_analysis_job.py`
- `devhub_whatsapp/models/dev_whatsapp_analysis_utils.py`
- `devhub_whatsapp/models/dev_whatsapp_inbox.py`
- `devhub_whatsapp/__manifest__.py`
- `devhub_whatsapp/tests/test_whatsapp_project_aware_ai.py`
- `docs/.../n8n_devhub_wa_project_aware_analysis_test.live.json`
- `/home/sabry/infra/n8n/workflow-devhub-wa-project-aware-analysis-test.json`
- `/home/sabry/infra/n8n/docker-compose.yml` (env wiring)
- `/home/sabry/infra/n8n/.env` (keys present; not committed)

## Operational controls

- Workflow restricted to Test Odoo URL/env
- Poll interval: 1 minute; lease limit 1
- Max attempts: 3 → dead_letter
- Auto WI creation: disabled (approval only)
- Auto-ignore: not enabled
- Fixture completion: disabled
- Production / OpenProject: not modified

## Confirmations

- Fixture completion was **not** used for live path
- Production untouched
- OpenProject untouched
- Screenshots: UI capture via browser not completed in this session; form fields verified in DB (`provider`, Dify/n8n IDs, project)

## Remaining limitations

- Historical WhatsApp groups AZone/ASTA had 0 messages in Test DB; UAT used controlled Test messages on those JIDs
- Multi-topic live scenario H not separately exercised end-to-end
- Dify occasionally returns qualitative `confidence` (`high`); Odoo now coerces aliases
- Analysis form screenshots not attached (DB-certified instead)
- Attach/create paths depend on Dify decision quality; approval remains human-gated
