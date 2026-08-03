# Production Personal Job Digest Preview Canary — Evidence

**Stamp:** `20260803T024822Z` (folder: `prod_digest_preview_canary_*`)  
**DB:** `pet_spot_elsahel` (Production)  
**Personal account only:** `linkedin.account` **id=2** `Sabry Youssef — Personal`  
**Company account:** **id=1** not modified  
**CV:** version **id=1** / attachment **id=11383**  

## Verdict

**`BLOCKED_MISSING_JOB_SOURCE_OR_CONFIGURATION`**

No useful preview digest was generated. Live search was **not** enabled. No crons activated. No outbound LinkedIn/email/employer contact.

## 1) Workflow inspection (code)

`linkedin.job._cron_daily_job_digest()`:

1. If `linkedin_connector.live_job_search_enabled` is not truthy → **log skip and return** (no HTTP, no writes).
2. Else, for each configured query × location, create `linkedin.job.search` with source `linkedin_guest` and call `action_search()` (live HTTP to LinkedIn guest / optionally RemoteOK / JSearch).
3. Collect today’s `linkedin.job.application` rows in `discovered` with `score >= threshold` (default 50).
4. `_send_job_digest(apps)` posts an internal `mail.mt_note` on each **Job Hunt Manager** group user’s partner (not LinkedIn).

**Filters / config present on Production:**

| Key | Value |
| --- | --- |
| `live_job_search_enabled` | `False` |
| `job_search_queries` | Senior Odoo Developer \| Odoo Developer \| Odoo Consultant \| Senior Odoo |
| `job_search_locations` | Remote \| Egypt \| United Arab Emirates |
| `job_score_threshold` | 50 |

**Recipients (digest delivery path):** group `linkedin_connector.group_linkedin_job_hunt` → currently user `admin` (`HAS_EMAIL`). Delivery is partner chatter `message_type=notification` / `mail.mt_note` (would be internal Odoo note if digest ran).

**Side effects when live=True (not executed):** create/update `linkedin.job`, may create `linkedin.job.application` above threshold, chatter notes to Job Hunt Manager users. Does **not** publish posts, apply, message LinkedIn, or upload CV.

## 2) Can a useful digest run with `live_job_search_enabled=False`?

**No.**

With the flag False, `_cron_daily_job_digest()` returns immediately. Discovery sources all require outbound HTTP (`linkedin_guest`, `remoteok`, `jsearch`). There is no alternate “offline digest from empty DB” path in the module.

## 3) Exact missing configuration / data

| Missing item | Production state | Why it blocks preview |
| --- | --- | --- |
| Local `linkedin.job` rows | **0** | No existing safe/local listings to score or digest |
| Local `linkedin.job.application` rows | **0** | Nothing to shortlist or preview |
| Live discovery permission | Flag must stay **False** under this approval | Cannot fetch LinkedIn/RemoteOK/JSearch without a new approval to enable live search |
| Seeded offline fixtures | None on Production | Creating synthetic jobs would not be “existing” data and was not approved |

Therefore step 4 (“Generate one preview digest only using existing safe/local data”) **cannot** be completed without violating the live-search prohibition or inventing non-existing jobs.

## 4) Actions performed (safe)

| Action | Result |
| --- | --- |
| Reconfirm CV SHA-256 | `29e968d70baf80e04607dcc526d23b776796245cd4ac5c56a0301ebbd7d6f539` — **match**; readable PDF; account_id=2 |
| Call `_cron_daily_job_digest()` once | Skipped as designed; log: `digest skipped: … live_job_search_enabled is False` |
| Enable live search | **Not done** |
| Activate any LinkedIn cron | **Not done** (all 4 remain inactive; digest `lastcall` still null) |
| Publish / apply / LinkedIn message / CV upload / profile edit | **Not done** |
| Outbound email | **Not done** |
| Modify company id=1 | **Not done** (fingerprint MD5 `480bd24a87cbe7707874cc72beb5a460` before=after) |

## 5) Before / after side-effect counts

| Metric | Before | After |
| --- | --- | --- |
| `linkedin.job` | 0 | 0 |
| `linkedin.job.application` | 0 | 0 |
| `linkedin.cv.version` | 1 | 1 |
| `linkedin.post` | 10 | 10 |
| Digest mail notes (subject ilike LinkedIn job digest, today) | 0 | 0 |

Isolation recheck: company + `job_branding` still **blocked** (transaction rolled back).

## 6) Screenshots

`screenshots/`

| File | Evidence |
| --- | --- |
| `01_jobs_empty.png` | Jobs list empty |
| `02_applications_empty.png` | Applications empty |
| `03_settings_live_flag.png` | Settings / live search UI |
| `04_digest_cron_inactive.png` | Daily Job Digest Active=OFF |
| `05_personal_account.png` | Personal account id=2 |
| `06_cv_default.png` | Default CV id=1 |
| `07_company_untouched.png` | Company id=1 unchanged |

Supporting logs: `preflight.sqlout`, `digest_skip_proof.txt`, `company_md5_before.txt`, `company_md5_after.txt`.

## 7) What a later approval must authorize (not done now)

To produce a real personal digest preview on Production, choose **one** explicitly:

1. **Enable live search canary** (`live_job_search_enabled=True` for a bounded run) while keeping crons inactive, using personal account id=2 only; **or**
2. **Approve offline fixture seeding** of local `linkedin.job` / application rows (no HTTP), then call `_send_job_digest` for an internal Odoo preview only.

Either path still requires separate approval before enabling the digest cron or any outbound LinkedIn/email employer contact.

## Stop line

**`BLOCKED_MISSING_JOB_SOURCE_OR_CONFIGURATION`**
