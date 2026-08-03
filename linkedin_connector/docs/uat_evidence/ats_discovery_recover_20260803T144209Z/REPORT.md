# ATS Discovery Recovery / Go-Live Closeout

**Verdict:** `ATS_DISCOVERY_LIVE_WAITING_FOR_SAFE_CANARY`

## Recovery
- Aborted shell left TEST upgrade OK and tests complete (0 failed / 0 errors).
- Resumed incomplete steps only: fresh Prod backup, module `19.0.2.14.0` upgrade, registry expansion, discovery re-run, evidence.
- Unrelated dirty tree files were not touched.

## 33 vs 41 tests
- **33** = executed tests this run (`Starting Test` lines; also the Odoo result line).
- Breakdown: 6 at_install (`TestAtsDiscovery`) + 27 post_install.
- **41** = Odoo `odoo.tests.stats` module counter (internal suite bookkeeping; not a second failure set).
- Source has 34 `test_*` methods; `test_bulk_wizard_schema` did not appear in Starting logs.
- **Outcome:** 0 failed, 0 errors.

## Production foundation
- Module: `19.0.2.14.0`
- Backup: `/home/sabry/private/job_orchestrator/backups/pet_spot_elsahel_pre_ats_recover_20260803T144209Z.dump` size=79096041 sha256=`9596e1de8c2ef858343613f4bcb545d63933f7295a7775384d3c57d7adaeb55e` (pg_restore -l OK, 32449 TOC lines)
- Dify: app `7fdf6db3-…`, workflow `34fcdf46-…`, published + pinned
- n8n hunter `caweLvPrZEBjBfku` **active** (6h Africa/Cairo); submit `5X4dygwEwzNPalNc` **inactive**
- Worker 0.2.0 health OK, `submit_enabled=false`
- Account 1 apps: **0**; account 2 apps: 1 (Odoo S.A. already applied)
- Kill switch ON; `live_submit_enabled=False`
- CV SHA match: `29e968d7…`

## Discovery
- Registry: **15** sources
- Last run stats: {"sources_checked": 15, "new_jobs": 6, "safe_canary": 0, "human_required": 0, "ineligible": 34, "unsupported_ats": 3, "errors": 0}
- Safe canary: **0**
- Last / next: see ICP `ats_discovery_last_run` / `ats_discovery_next_run`
- External submissions this run: **0**

## Operating mode
Discovery continues on Odoo cron + n8n. Submission stays fail-closed until a CAPTCHA-free gated canary succeeds; then prior one-shot authorization auto-promotes.
