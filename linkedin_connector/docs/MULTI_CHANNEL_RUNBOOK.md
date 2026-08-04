# Multi-channel job discovery + safe auto-apply

Version: `linkedin_connector` **19.0.2.18.0**

## Rules (non-negotiable)

- Automation sets **Applied** only via `action_record_submission_evidence` with `ok=True` plus thank-you URL / reference / Message-ID.
- CAPTCHA / login / 2FA / unsupported → `human_required` (Needs Action).
- LinkedIn Easy Apply stays blocked; LinkedIn URLs are inventory/review only.
- Personal account **id=2** only; company **id=1** excluded.
- Kill switches: `live_job_search_enabled`, `live_submit_enabled`.

## Phase 1 — Aggregators + ATS (implemented)

| Piece | Detail |
|-------|--------|
| `source_channel` | On `linkedin.job`; dashboard filter + chart; list/search filters |
| JSearch pack | AE / EG / SA / remote Odoo (+ overflow queries); caps 4 req/day, 40 jobs/day |
| Aggregators | Arbeitnow + Remotive wizard sources + `_cron_daily_aggregators` (inactive until enabled) |
| ATS seeds | Extra company_ats + Greenhouse/Lever/Ashby/Workable probes |
| Auto-apply | Canary uses evidence path; worker prefers **Firefox** for company_ats / odoo_careers |

### Enable discovery (after UAT)

```text
ICP linkedin_connector.live_job_search_enabled = True
Activate crons: Daily JSearch, Daily Aggregator, Direct ATS Discovery
Keep live_submit_enabled=False until one live canary with thank-you proof
```

## Phase 2 — Telegram (scaffolded)

- Model: `linkedin.job.channel.source` (`channel_type=telegram`)
- Menu: Jobs → Telegram / Facebook
- Bot token: env `TELEGRAM_JOB_BOT_TOKEN` (never commit)
- Cron: `LinkedIn: Telegram Channel Ingest` (inactive)

**Blocked until:** allowlisted chat IDs + bot membership. Then enable sources and cron.

## Phase 3 — Facebook (scaffolded)

- Same model with `channel_type=facebook`
- `run_facebook_scan` logs browser-assisted pending (Glass / facebook-account-manager)
- Cron inactive

**Blocked until:** named Pages/groups + which FB account.

## UAT checklist

1. Upgrade TEST → inventory dry-run (aggregators + ATS, submit off)
2. Confirm `source_channel` populated; dashboard channel filter works
3. One Prod canary on known-good company ATS with thank-you screenshot
4. Only then bounded `live_submit_enabled` + policy caps (e.g. 2/day)
