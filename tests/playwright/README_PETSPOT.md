# PetSpot Clinic Playwright E2E

Automated scenarios with screenshots for the WhatsApp → portal → Odoo incomplete-case workflow.

## What it covers

| # | Scenario | Platforms |
| --- | --- | --- |
| 01 | Health checks | Odoo portal API, Bridge |
| 02 | Bot intent `حجز` | Bridge / Evolution webhook |
| 03–04 | Booking form + submit | Public portal |
| 05 | Status lookup + exam link | Odoo API + Bridge |
| 06–07 | Exam form + incomplete visit | Public portal |
| 08–10 | Incomplete Cases, tokens, slots, complete checklist | Odoo backend |
| 11 | Status after completion | Bridge bot |
| 12 | Chatwoot home (optional) | Chatwoot |
| 13 | Results summary | Report |

## Run

```bash
# One-shot (starts Odoo/bridge if needed)
./run_petspot_e2e.sh
```

Or manually:

```bash
export ODOO_URL=http://127.0.0.1:8027
export ODOO_DB=pet_spot_elsahel
export ODOO_LOGIN=admin
export ODOO_PASSWORD=admin
export BRIDGE_URL=http://127.0.0.1:3010
export BRIDGE_SHARED_SECRET=...   # from bridge .env
export PETSPOT_BRIDGE_TOKEN=...

# Chrome for Testing is used (Playwright browsers unsupported on Ubuntu 26)
npm install
npx @puppeteer/browsers install chrome@stable --path ./browsers
npm run test:petspot
npm run copy:petspot
```

## Output

- Screenshots: `screenshots/petspot_clinic/*.png`
- Report: `screenshots/petspot_clinic/RESULTS.md`
- Copied to: `docs/screenshots/petspot_clinic/`
