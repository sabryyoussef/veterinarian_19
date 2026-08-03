# Personal Daily JSearch Automation — Activation Evidence

**DB:** `pet_spot_elsahel`  
**Account:** personal **id=2** only  
**Module:** `linkedin_connector` **19.0.2.9.1**  
**Verdict:** `PERSONAL_DAILY_JOB_DIGEST_ACTIVATED`

## What was activated

| Item | State |
| --- | --- |
| `live_job_search_enabled` | **True** |
| `auto_create_applications` | **False** |
| Cron `LinkedIn: Daily JSearch Job Search` (id=113) | **Active** — daily 07:00 Africa/Cairo (`nextcall` 2026-08-04 04:00 UTC) |
| Cron `LinkedIn: Daily Job Digest` (id=112) | **Active** — daily 07:15 Africa/Cairo (`nextcall` 2026-08-04 04:15 UTC) |
| Publish / Feed / Messages crons | **Inactive** |
| Endpoint | `https://jsearch.p.rapidapi.com/search-v2` only |

## Daily queries (max 3 API requests)

1. Odoo Developer in UAE — `country=ae`
2. Odoo Developer in Egypt — `country=eg`
3. Remote Odoo Developer — `remote_jobs_only`

All use `date_posted=week`, `num_pages=1`. Caps: **3 req/day**, **30 jobs/day**, **120 req/month** (fail closed).

## First cycle (2026-08-03)

| Step | Result |
| --- | --- |
| JSearch cron | Ran 03:52 UTC; **3** search-v2 calls (ae/eg/remote) |
| Import/score | Initial CV-cache bug aborted scoring mid-import; fixed in 19.0.2.9.1; jobs re-scored locally **without** extra API calls |
| Jobs after | **12** on account id=2 (0 on company id=1) |
| Applications | **0** |
| Digest cron | First attempt failed (`res.groups.users` removed in Odoo 19); fixed to `user_ids`; internal note **delivered** |
| Digest content | Top **3** jobs with score ≥ 50 (title/company/location/score/listed/URL) to admin partner as `mail.mt_note` |
| Company id=1 hash | `480bd24a87cbe7707874cc72beb5a460` unchanged |
| Outbound LinkedIn / email / posts | **0** |
| CV | Local id=1 used for scoring only; not uploaded |

Usage counter after cycle: `day_count=3`, `month_count=3`, `day_jobs=0` (imports that completed scoring after the bug were rescored offline; quota correctly consumed).

## Fixes shipped in 19.0.2.9.x

- Split search vs digest crons; JSearch search-v2 only
- Daily/monthly fail-closed caps
- No auto-applications in digest mode
- Digest based on jobs (not applications), Sabry/admin only
- CV relevance boost via local PDF tokens
- Registry CV cache + `user_ids` recipient fix (19.0.2.9.1)

## Still prohibited without new approval

- Applications / Easy Apply / recruiter contact
- LinkedIn posting or messaging
- External email delivery
- CV upload / profile changes

## Stop line

**`PERSONAL_DAILY_JOB_DIGEST_ACTIVATED`**
