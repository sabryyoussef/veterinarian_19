# Live Draft Canary — Vivandi / BeBee (Prod job id=10)

**Verdict:** `JOB_ORCHESTRATOR_LIVE_DRAFT_BLOCKED`

## Why blocked (preflight stop rules)

| Check | Result |
| --- | --- |
| Prod job 10 still Vivandi / Odoo Techno Functional Consultant / score 65 | Yes (read-only) |
| Apply URL resolve | `https://bebee.com/ae/jobs/odoo-techno-functional-consultant-vivandi-dubai--t7xk-773739037` |
| Redirects | **0** (stays on bebee.com) |
| CAPTCHA | None on listing |
| BeBee apply CTA | **Sign in required** (“Sign in to continue to this offer…”) → `login_wall` |
| Underlying source | Indeed `http://ae.indeed.com/job/odoo-techno-functional-consultant-50dea3e8b77b2e49` |
| Indeed probe | **HTTP 403** (bot/auth wall; unsafe to continue) |
| HTML forms on listing | **0** (SPA; apply gated behind login) |
| Personal data entered | **No** |
| Submit clicked | **No** |
| Login performed | **No** |

Stop rule hit: BeBee login wall + Indeed unreachable/unsafe. Live DOM fill and n8n/Dify pack execution against this live apply path were **not** continued.

## Network containment (proven)

- Browser route interceptor allowed only **GET/HEAD/OPTIONS**.
- **14** non-safe requests aborted (method/host/path logged, no bodies).
- Context switched **offline** before any fill (fill never performed).
- `post_put_patch_delete_reached_network`: **false**
- External CV upload: **false**
- Submit API still **403**

See `network/SANITIZED_NETWORK.json`, `BROWSER_PREFLIGHT.json`.

## Platform classification

- Surface: **bebee**
- Underlying apply target: **indeed** (403)
- Recommended channel after block: **manual_browser** / human (with account) — not auto-orchestrator

## Odoo TEST audit records (only)

| Record | ID |
| --- | --- |
| UAT job copy | `39` (`uat_live_draft_vivandi_bebee_10`) |
| Application | `31` |
| Attempt | `4` (`stopped` / `login_wall`) |
| Idempotency | `uat-live-draft-vivandi-bebee-20260803` |
| Account | **2** only; company apps = 0 |

Dify run / n8n execution: **skipped-blocked-preflight** (inactive n8n workflow left inactive).

## Production safety

| Metric | Before | After |
| --- | --- | --- |
| Module | 19.0.2.9.1 | 19.0.2.9.1 |
| Jobs | 12 | 12 |
| Applications | 0 | 0 |
| Cron 112/113 | active, lastcall unchanged | same |
| Job 10 | read-only | unchanged title/company |

No Production application/attempt created. No Production config/cron changes.

## Sanitized field map (listing page)

| Area | Mapping |
| --- | --- |
| Visible apply CTA | unsupported without login → `login_wall` / manual review |
| Listing description | content only; not an application form |
| easyApply i18n schema (name/email in JS strings) | not actionable without auth session |
| File upload | not reachable without login |
| Consent / ToS | not presented (stopped before) |
| Salary / visa / notice / relocation | unset / `missing_facts` (not invented) |

## Screenshots

- `screenshots/01_preflight_loaded.png`
- `screenshots/02_offline_no_fill.png`

## Cleanup

- No live submit state left enabled
- n8n UAT workflow remains **inactive**
- Stray `uat-odoo-test-proxy` removed if present
- `uat-job-worker` may remain for prior UAT; not used for live fill this canary

## Next options (require new approval)

1. Manual BeBee/Indeed apply by Sabry (human session).
2. Pick a different high-score job whose apply URL is Greenhouse/Lever/company ATS **without** login wall.
3. Only if approved later: authenticated browser profile for a specific ATS (still no CAPTCHA bypass).
