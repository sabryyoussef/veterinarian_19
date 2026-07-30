# PetSpot Fulfillment × Vetution — Playwright UAT

Automates the operator checklist in
`petspot_fulfillment_vetution/docs/MANUAL_TESTING.md` (Shadow Mode on Production,
synthetic E2E on TEST).

## Safety

| Environment | DB | Port | Allowed actions |
|---|---|---|---|
| Production | `pet_spot_elsahel` | 8027 | Read-only + authorized shadow assess only |
| TEST | `pet_spot_elsahel_test` | 8028 | Synthetic workflow with **mock** transports |

Production tests **abort** on `FAIL_UNSAFE_PRODUCTION_CONFIGURATION` and never
flip live transports, auto-quote, RFQ send, ShipBlu create, or Shopify publish.

TEST mutations go through `helpers/shell_workflow.py` (odoo-bin shell) because
`WorkflowEngine` is not a JSON-RPC model. The shell runner **refuses** Production DB.

## Prerequisites

1. Odoo services listening on 8027 / 8028.
2. Modules installed: `petspot_fulfillment` `19.0.1.1.1`, `petspot_fulfillment_vetution` `19.0.1.5.0`.
3. From `tests/playwright`:

```bash
npm install
# Chrome for Testing (Ubuntu 26 may need this instead of stock Chromium)
npx @puppeteer/browsers install chrome@stable --path ./browsers
```

## Environment variables

| Variable | Purpose |
|---|---|
| `ODOO_URL` | Base URL (default by project) |
| `ODOO_DB` | Database name |
| `ODOO_LOGIN` | UI login (default `admin`) |
| `ODOO_PASSWORD` | UI password (**required**, never commit) |
| `PETSPOT_PW_ENV` | `production` or `test` (optional override) |
| `PETSPOT_PW_EVIDENCE_DIR` | Evidence root (default `~/.cursor/evidence/petspot-playwright-uat-…`) |
| `PW_HEADED=1` | Headed browser |

Copy `.env.example` → `.env` locally (gitignored). Do not store session cookies in Git.

## Commands

```bash
cd tests/playwright

# TEST synthetic first (pickup + delivery + exception matrix)
export ODOO_URL=http://127.0.0.1:8028
export ODOO_DB=pet_spot_elsahel_test
export ODOO_LOGIN=admin
export ODOO_PASSWORD='…'   # from your secret store — do not echo
npx playwright test --project=test-synthetic

# Production shadow / safety (only after TEST + safety flags known closed)
export ODOO_URL=http://127.0.0.1:8027
export ODOO_DB=pet_spot_elsahel
export ODOO_PASSWORD='…'
npx playwright test --project=production-shadow

# One file / one scenario
npx playwright test --project=test-synthetic petspot_fulfillment_vetution/test-synthetic-pickup.spec.ts

# HTML report (path printed under evidence dir)
npx playwright show-report "$PETSPOT_PW_EVIDENCE_DIR/playwright-report"
```

Package scripts:

```bash
npm run test:vetution:test
npm run test:vetution:prod
```

## Evidence

Written outside the repo by default:

```text
~/.cursor/evidence/petspot-playwright-uat-YYYYMMDD-HHMMSS/
  screenshots/
  traces/
  videos/
  playwright-report/
  results.json
  evidence-index.md
  production-safety.json
  test-cleanup.json
  run.log
```

Screenshots are named per the manual guide (`01-prod-…`, `20-test-…`, …).
Password fields and phone inputs are masked when possible.

## Cleanup

TEST suites always attempt `cleanup_synthetic` in `finally`:

* Deactivate `TEST-SYNTHETIC-E2E-NOT-FOR-COMMERCE`
* Re-activate a commercial TEST policy when present
* Restore transports to `mock`

Failure → `FAIL_TEST_CLEANUP`. Production is never modified by cleanup.

## Updating locators

1. Prefer role / button string from XML (`Assess Vetution Availability`).
2. Prefer `action` XML IDs listed in `helpers/env.ts` (`ACTION_XML`).
3. Prefer `/odoo/action-<id>` and `/odoo/<model>/<id>` URLs.
4. Avoid generated CSS classes (`o_form_view` / `o_list_view` are stable Odoo shells).
5. After XML renames, update `ACTION_XML` and page objects only — do not guess menu paths.

## Layout

```text
petspot_fulfillment_vetution/
  fixtures/          (reserved)
  helpers/           env, rpc, safety, evidence, shell bridge
  pages/             login, bridge, inquiry, shadow, params, policy
  production-shadow.spec.ts
  test-synthetic-pickup.spec.ts
  test-synthetic-delivery.spec.ts
  exception-matrix.spec.ts
  README.md
```
