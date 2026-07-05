# Veterinary Demo — Playwright Screenshots

Automated capture of **USER_GUIDE.md** scenarios as PNG screenshots.

## Prerequisites

1. Odoo running with database `neo_odoo` (default `http://127.0.0.1:8076`).
2. Modules installed: `veterinary_clinic`, `pet_management`, `veterinary_petget_bridge`, `veterinary_pet_management_bridge`.
3. Demo data seeded (pets like **Max**, consultations, CRM, etc.).

## Setup

```powershell
cd D:\odoo\odoo19\projects\edafa__veterinary_demo\tests\playwright
copy .env.example .env
# Edit .env if login/password differ
npm install
npx playwright install chromium
```

## Run

```powershell
$env:ODOO_PASSWORD = "admin"
npm run test:screenshots
```

Screenshots are written to `screenshots/`:

| File | User guide |
|------|------------|
| `uc01_clinic_pets_list.png` | UC-01 Register pet |
| `uc01_clinic_pet_form_bridge.png` | UC-01 / UC-02 Bridge |
| `uc03_website_appointment.png` | UC-03 Website booking |
| `uc04_pm_appointments_list.png` | UC-04 PM appointments |
| `uc05_consultations_*.png` | UC-05 Consultation |
| `uc06`–`uc12_*.png` | Health & ops scenarios |
| `uc13_*.png` | Petget documents / dog profile |
| `uc14`–`uc21_*.png` | Enterprise & configuration |
| `uc_pm_pet_form_clinic_button.png` | PM ↔ clinic link |

## Environment variables

| Variable | Default |
|----------|---------|
| `ODOO_URL` | `http://127.0.0.1:8076` |
| `ODOO_DB` | `neo_odoo` |
| `ODOO_LOGIN` | `admin` |
| `ODOO_PASSWORD` | *(required)* |

## HTML report

After a run: `npx playwright show-report report`

## Copy into docs (optional)

```powershell
Copy-Item -Recurse screenshots ..\..\docs\screenshots
```

Then reference images from `docs/USER_GUIDE.md`.
