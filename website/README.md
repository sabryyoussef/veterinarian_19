# Pet Spot Sahel — Website tooling

Deploy and test the PetSpot El Sahel landing page on local Odoo and [petspot.odoo.com](https://petspot.odoo.com).

## Setup

1. Copy `.env.example` → `.env` and fill `REMOTE_ODOO_API_KEY`.
2. Clinic/social fields in `.env` override `business_data.json`.
3. Logo: `assets/logo/petspot-logo.png` (TODO: replace with final brand asset).
4. Gallery photos: add to `assets/gallery/` (see `assets/gallery/README.md`).

## Commands

```bash
cd projects/pet_spot_elsahel/website
../../venv19/bin/python3 test_connection.py
../../venv19/bin/python3 deploy.py --target local
../../venv19/bin/python3 deploy.py --target remote
../../venv19/bin/python3 deploy_online.py   # remote alias
```

## Content sources

- `business_data.json` — canonical marketing data
- `petspot_marketing_assets/` — source briefs and manifests
- `PETSPOT_WEBSITE_UPDATE_REPORT.md` — latest update log

## QA (2026-06-19 marketing update)

| Check | Result |
|-------|--------|
| Homepage HTTP 200 (local + remote) | OK |
| Hero “Trusted Pet Care in El Sahel” | OK |
| WhatsApp + Maps + Facebook links | OK |
| Bilingual AR/EN inline | OK |
| Services / campaign cards | OK |
| Gallery placeholders (no fake photos) | OK |
| Contact `/contactus` | OK |
| SEO meta title/description | OK |
| Logo placeholder in company | OK |
