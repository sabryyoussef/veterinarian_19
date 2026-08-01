# Identity + Personal LinkedIn UAT Evidence — 2026-08-02

**DB:** `pet_spot_elsahel_test` only  
**Production:** not upgraded, not deployed, not used  
**Live LinkedIn:** no publish / search / apply / submit / profile edit / LinkedIn CV upload  
**Verdict:** `PERSONAL_LINKEDIN_UAT_READY_FOR_APPROVAL`

## Phase A — CV discovery (docs only)

| Field | Value |
| --- | --- |
| Path | `docs/Sabry_Youssef_CV.pdf` |
| Size (bytes) | `76123` |
| Pages | `2` |
| SHA-256 | `29e968d70baf80e04607dcc526d23b776796245cd4ac5c56a0301ebbd7d6f539` |
| Marker check | Sabry / Odoo / experience markers present (counts only; full text not logged) |
| Git | Added to `.gitignore` as `docs/Sabry_Youssef_CV.pdf` — must not be committed |

## Phase B — Private staging

- Staged under `/home/sabry/private/linkedin_cv/` (mode `0700`) for attach only.
- Staging PDF removed after Odoo attach; source remains in `docs/` (gitignored).

## Phase C — Attach default CV (test DB)

| Record | ID / value |
| --- | --- |
| Personal account | `linkedin.account` **id=2** — `Sabry Youssef — Personal` |
| Profile URL | `https://www.linkedin.com/in/sabry-youssef-56a878185/` |
| Account type | `personal` |
| Attachment | `ir.attachment` **id=19203** — `Sabry_Youssef_CV.pdf` |
| CV version | `linkedin.cv.version` **id=3** — `Sabry Youssef — Senior Odoo CV` (default on account 2) |
| PetSpot account | **id=1** company (`org_id=129944345`), disconnected — unused for personal UAT |

## Phase D — Offline UAT fixtures (no live LinkedIn)

| Item | Result |
| --- | --- |
| UAT jobs | ids **11**, **12** (fixtures) |
| Application | **id=9** → shortlisted → pack_ready → approved (audit set) |
| Pre-approve open | blocked |
| Post-approve open | returned `act_url` only — URL not followed |
| UAT posts | ids **19–21** scheduled, unpublished; purpose `job_branding` on personal account |
| Isolation | create/write cross-purpose (personal↔company / job_branding↔company_marketing) **blocked** |
| Code fix | `linkedin.post` `_assert_account_content_isolation` on create **and** write (purpose-only write was previously able to break isolation) |
| Crons | LinkedIn job/publish crons forced inactive |
| Live gate | `live_job_search_enabled=False` |

## Phase E — Tests + evidence

| Check | Result |
| --- | --- |
| Tests | **0 failed, 0 error(s) of 17 tests** |
| Log | `linkedin_connector/docs/uat_evidence/test_run_20260802_personal_uat_b.log` |
| Prior log | `test_run_20260802_personal_uat.log` (16 tests before write-isolation unit test) |

## Safety still in force

- No Production upgrade/deploy
- No live LinkedIn actions until Sabry explicitly approves go-live
- Do not commit CV/PDF/filestore/secrets

## Approval gate

Stop here for Sabry’s go-live approval before any live LinkedIn or production action.
