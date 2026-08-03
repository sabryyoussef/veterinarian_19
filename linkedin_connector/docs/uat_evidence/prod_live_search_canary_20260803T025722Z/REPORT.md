# Production Bounded Live-Search Canary — Evidence

**DB:** `pet_spot_elsahel` (Production)  
**Target account:** `linkedin.account` **id=2** only  
**Company account id=1:** not modified  
**Verdict:** `BLOCKED_LINKEDIN_JOB_SEARCH_SCOPE_OR_API`

## Safety outcome

| Action | Status |
| --- | --- |
| Enable `live_job_search_enabled` | **Not enabled** (remained `False`) |
| Manual LinkedIn guest / JSearch / RemoteOK HTTP | **Not executed** |
| Cron activation | **None** (all 4 inactive) |
| Publish / apply / message / connect / CV upload | **None** |
| OAuth reauthorize / extra scopes | **None** |
| Jobs / applications written | **0 / 0** |

## 1) Exact live-search implementation (inspected)

### A) Default / digest path: `linkedin_guest`

| Item | Detail |
| --- | --- |
| Method | `_search_linkedin_guest()` via `linkedin.job.search.action_search()` |
| Endpoint | `https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search` |
| Auth | **None** — unauthenticated HTTP GET with browser `User-Agent` |
| OAuth scopes used | **None** (does not send the personal access token) |
| Parsing | HTML/`<li>` regex scrape of job cards |
| Expected writes | `linkedin.job` create/write; then `_maybe_create_applications()` may create `linkedin.job.application` when score ≥ threshold |
| Cron wiring | `_cron_daily_job_digest()` hard-codes `source="linkedin_guest"` after live flag check |

This path is **LinkedIn scraping**, not an official OAuth Jobs API. It conflicts with canary safety: *“Do not scrape LinkedIn…”*.

### B) Alternate: JSearch (RapidAPI)

| Item | Detail |
| --- | --- |
| Endpoint | `https://jsearch.p.rapidapi.com/search` |
| Auth | `X-RapidAPI-Key` from ICP `linkedin_connector.rapidapi_key` |
| Production key | **Absent** (no `rapidapi_key` ICP row) |
| Relation to LinkedIn OAuth | **None** — third-party aggregator; not authorized by `w_member_social` |

### C) Alternate: RemoteOK

| Item | Detail |
| --- | --- |
| Endpoint | `https://remoteok.io/api` |
| Auth | None |
| Coverage | Remote-only; cannot satisfy UAE/Egypt LinkedIn canary as LinkedIn OAuth job search |

### D) Official LinkedIn Jobs API via current scopes

| Item | Detail |
| --- | --- |
| Personal scopes on id=2 | `openid profile w_member_social` |
| What those scopes allow | Sign-in identity + member social posting (Share on LinkedIn) |
| Jobs Search product | **Not granted** — module PLAN explicitly: *“Jobs Search API (separate product request in LinkedIn Developers)”* / phase table *“Jobs Search (request needed)”* |
| Token used for job search in code | **Never** — no `/rest/jobs` (or similar) call with bearer token exists |

## 2) Scope / API gate (preflight step 3)

**Conclusion:** Existing OAuth scopes **cannot** legally/technically access LinkedIn Job Search.

- Technical: no Jobs API client in connector; guest path ignores OAuth.
- Product: Jobs Search requires a separate LinkedIn developer product not present.
- Policy for this canary: guest scrape is explicitly prohibited.

Therefore the canary **stopped without enabling** `live_job_search_enabled`.

## 3) Rollback plan (prepared; unused because flag never flipped)

1. `UPDATE ir_config_parameter SET value='False' WHERE key='linkedin_connector.live_job_search_enabled';`
2. Force all LinkedIn `ir.cron` rows `active=false`.
3. If any jobs/apps were created (none were): delete canary-tagged rows / restore from last Production dump.
4. Re-check company id=1 fingerprint and HTTP 200.

## 4) Before / after state

| Metric | Before | After |
| --- | --- | --- |
| `live_job_search_enabled` | False | False |
| LinkedIn crons active | 0/4 | 0/4 |
| `linkedin.job` | 0 | 0 |
| `linkedin.job.application` | 0 | 0 |
| Company id=1 MD5 | `480bd24a87cbe7707874cc72beb5a460` | **same** |
| Outbound LinkedIn actions | 0 | 0 |

Personal account id=2 remains configured; CV id=1 / attachment 11383 untouched.

## 5) Why the approved canary limits could not be met via current code

Requested: LinkedIn live search for UAE/Egypt/Remote, ≤10 imports, 0 applications, OAuth scopes only, no scrape.

| Requirement | Blocker |
| --- | --- |
| Authorized LinkedIn job search with current scopes | Scopes lack Jobs Search product/API |
| No scrape | Default implementation **is** guest scrape |
| Applications created = 0 | Job `create()` auto-calls `_maybe_create_applications()` unless context skipped — even alternate sources would need a guarded import path |
| RapidAPI JSearch | No Production RapidAPI key configured; still not LinkedIn OAuth |

## 6) Screenshots

`screenshots/`

| File | Shows |
| --- | --- |
| `01_personal_scopes.png` | Personal account scopes / connection |
| `02_settings_live_false.png` | Live search remains off |
| `03_jobs_still_empty.png` | No imported jobs |
| `04_digest_cron_inactive.png` | Digest cron inactive |
| `05_company_untouched.png` | Company id=1 unchanged |
| `06_accounts_list.png` | Personal vs company isolation |

Also: `preflight.sqlout`, `postflight.sqlout`, `code_refs.txt`.

## 7) What a future approval must add (not done)

One of:

1. **Official LinkedIn Jobs Search product** approved on the developer app + documented scopes/endpoints + OAuth-authenticated client (replacing guest scrape); **or**
2. Explicit approval to use a **non-LinkedIn** source (e.g. RapidAPI JSearch / RemoteOK) with a hard cap, `skip_job_postprocess` (or equivalent) to keep applications at 0, and no guest scrape.

## Stop line

**`BLOCKED_LINKEDIN_JOB_SEARCH_SCOPE_OR_API`**
