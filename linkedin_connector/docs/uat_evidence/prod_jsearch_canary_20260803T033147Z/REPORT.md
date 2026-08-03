# JSearch Production Canary — Evidence

**DB:** `pet_spot_elsahel`  
**Account:** personal **id=2** only  
**Module after fix:** `linkedin_connector` **19.0.2.8.2** (`/search-v2`)  
**Verdict:** `JSEARCH_PRODUCTION_CANARY_READY_FOR_APPROVAL`

## Summary

One successful JSearch `search-v2` response for **Odoo Developer in UAE** (`country=ae`, `date_posted=week`, `page=1`) was imported as **10** `linkedin.job` rows on account **id=2**. Applications **0**. Company **id=1** unchanged. Live flag restored **False**. All LinkedIn crons **inactive**. Internal digest preview posted as `mail.mt_note` only (no email).

## API / endpoint notes

| Call | Endpoint | Result |
| --- | --- | --- |
| Initial canary (module default) | `GET /search` | **404** `Endpoint '/search' does not exist` — rolled back, no imports |
| Endpoint discovery | `GET /search-v2` | **200** |
| Canary payload fetch | `GET /search-v2` same params | **200**, 10 jobs — imported without further API calls |

**Fix shipped:** connector now uses `https://jsearch.p.rapidapi.com/search-v2` and reads `data.jobs`.

Honest quota note: this session used **3** RapidAPI HTTP calls (1 failed legacy + 2 successful v2). Import did not add a fourth.

## Limits compliance

| Limit | Result |
| --- | --- |
| Query / country / date / page | `Odoo Developer in UAE`, `ae`, `week`, page 1 |
| Max imported jobs | **10** |
| Applications | **0** (`skip_job_postprocess` + score/dedupe only) |
| Outbound LinkedIn / publish / email | **0** |
| Company id=1 | MD5 `480bd24a87cbe7707874cc72beb5a460` before=after |
| CV | Local SHA `29e968d7…d6f539` verified; **not** uploaded |
| Crons | All 4 inactive after canary and after 19.0.2.8.2 upgrade |
| `live_job_search_enabled` | Temporarily True during import window → restored **False** |

## Before / after

| Metric | Before | After |
| --- | --- | --- |
| Jobs | 0 | 10 (all account_id=2, source=`JSearch-canary`) |
| Applications | 0 | 0 |
| Posted posts | 10 | 10 |

## Relevance review (sanitized)

| id | score | title | company | notes |
| --- | --- | --- | --- | --- |
| 5 | 65 | Software Developer - Odoo | PREMA Consulting | UAE/Indeed |
| 8 | 65 | Odoo Developer (API/Workflow) | Melya Cleaning Services | UAE |
| 10 | 65 | Odoo Techno Functional Consultant | Vivandi | UAE |
| 1–7,9 | 30–40 | various Odoo Developer roles | several | no broken titles/URLs; 0 duplicates; all have descriptions |

Full sanitized rows: `imported_jobs_sanitized.json`  
Internal digest text: `digest_preview_sanitized.txt` (also Odoo note id **78901** on admin partner)

## Screenshots

`screenshots/01_jobs_list.png` … `06_personal_account.png`

## Not done (still need separate approval)

- Scheduled digest / live search left on
- Job applications / Easy Apply / recruiter contact
- Publishing posts
- LinkedIn CV upload

## Stop line

**`JSEARCH_PRODUCTION_CANARY_READY_FOR_APPROVAL`**
