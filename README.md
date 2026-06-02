# Veterinarian 19 — Edafa Veterinary Demo (Odoo 19)

**Repository:** [github.com/sabryyoussef/veterinarian_19](https://github.com/sabryyoussef/veterinarian_19)  
**Branch:** `feature/edafa-veterinary-demo` (full stack) · `app-veterinary_clinic` (clinic app only)

End-to-end **veterinary clinic** demo for Odoo 19 Enterprise: industry pack, Pet Management operations, Petget dog knowledge, and bridge modules that keep a single pet identity across apps.

**Local workspace mirror:** `D:\odoo\odoo19\projects\edafa__veterinary_demo` (same modules, nested vendor folders)  
**Odoo.sh / deploy:** use **this repo root** on `addons_path`  
**Local database:** `neo_odoo` · **Default URL:** `http://127.0.0.1:8076`

---

## What you get

| Component | Path | Role |
|-----------|------|------|
| **Veterinary Clinic** | `veterinary_clinic/` | Studio `x_pets`, consultations, CRM, website appointments, sales, POS, FSM |
| **Pet Management** | `pet_management/` | Health, boarding, grooming, training, diet, internal appointments |
| **Petget** | `petget_core/`, `petget_dog/`, `petget_dog_knowledge/` | AKC breeds, documents, reminders (on clinic pets via bridge) |
| **Petget bridge** | `veterinary_petget_bridge/` | Petget on `x_pets`; hides duplicate Petget app |
| **PM bridge** | `veterinary_pet_management_bridge/` | 1:1 sync `x_pets` ↔ `pet.pet` |
| **Support** | `base_industry_data/`, `pos_stock/`, `planning_field_service_worksheet/` | Industry dependencies |

```mermaid
flowchart TB
    subgraph Enterprise["Odoo Enterprise"]
        VC[Veterinary Clinic x_pets]
        CRM[CRM]
        SALES[Sales]
        CAL[Calendar / Website]
        POS[Point of Sale]
        FSM[Field Service]
        DOC[Documents / Knowledge]
    end

    subgraph PM["Pet Management"]
        PET[pet.pet]
        APPT[Appointments hub]
        HEALTH[Medical / Vaccines / Weight]
        OPS[Boarding / Grooming / Training / Diet]
    end

    subgraph PG["Petget"]
        AKC[AKC breed profile]
        REM[Reminders]
        FILES[Documents]
    end

    VC <-->|veterinary_pet_management_bridge| PET
    VC --> PG
    APPT --> HEALTH
    APPT --> OPS
    VC --> CRM
    VC --> SALES
    VC --> CAL
```

---

## Quick start (local)

### 1. Addons path

Include in `odoo.conf`:

```ini
addons_path = ...,
    D:\odoo\odoo19\projects\veterinarian_19
```

Or clone from GitHub:

```bash
git clone -b feature/edafa-veterinary-demo https://github.com/sabryyoussef/veterinarian_19.git
```

### 2. Install order

1. `base_industry_data` → `pos_stock` → `planning_field_service_worksheet`
2. `petget_core` → `petget_dog` → `petget_dog_knowledge`
3. `veterinary_clinic` → `veterinary_petget_bridge`
4. `pet_management` → `veterinary_pet_management_bridge`
5. Upgrade all → **Pets → Sync to Pet Management** (or run post-init sync)

### 3. Seed demo data (optional)

From repo `tools/` (with Odoo running or RPC):

```powershell
cd D:\odoo\odoo19\tools
python seed_veterinary_demo_data.py
python seed_veterinary_100_pets.py
# Full Odoo.sh pipeline: python seed_odoo_sh_veterinary_all.py
```

### 4. Login

- **URL:** http://127.0.0.1:8076  
- **Database:** `neo_odoo`  
- **User:** `admin` / `admin` (adjust for your instance)

---

## Workflow scenarios (with screenshots)

Screenshots are captured by [Playwright](tests/playwright/) against a seeded `neo_odoo` database. Regenerate anytime (see [Regenerate screenshots](#regenerate-screenshots)).

### Clinic registry & bridge

| Scenario | Steps | Screenshot |
|----------|--------|------------|
| **UC-01** Register / view clinic pets | **Pets → Pets** — create or open `x_pets` | ![Clinic pets list](docs/screenshots/uc01_clinic_pets_list.png) |
| **UC-01 / UC-02** Link to Pet Management | Open pet form → **Pet Management** smart button or **Sync to Pet Management** | ![Clinic pet + bridge](docs/screenshots/uc01_clinic_pet_form_bridge.png) |
| **PM** Open linked `pet.pet` | **Pets app → Pets** → **Clinic Record** button | ![PM pet + clinic link](docs/screenshots/uc_pm_pet_form_clinic_button.png) |

### Appointments & consultations

| Scenario | Steps | Screenshot |
|----------|--------|------------|
| **UC-03** Website booking | Public `/appointment` — choose type & slot | ![Website appointments](docs/screenshots/uc03_website_appointment.png) |
| **UC-04** Internal PM appointment | **Pets app → Appointments** — multi-service hub | ![PM appointments](docs/screenshots/uc04_pm_appointments_list.png) |
| **UC-05** Clinic consultation | **Pets → Consultations** or pet form → consultation line | ![Consultations list](docs/screenshots/uc05_consultations_list.png) |
| | Open consultation — vitals, illness, vaccines | ![Consultation form](docs/screenshots/uc05_consultation_form.png) |
| **UC-18** Staff calendar | **Appointments** app — calendar view | ![Calendar](docs/screenshots/uc18_calendar.png) |

### Pet Management — health & operations

| Scenario | Menu | Screenshot |
|----------|------|------------|
| **UC-06** Medical visit (SOAP) | Health → Medical Visits | ![Medical visits](docs/screenshots/uc06_medical_visits.png) |
| **UC-07** Vaccinations | Health → Vaccinations | ![Vaccinations](docs/screenshots/uc07_vaccinations.png) |
| **UC-08** Weight history | Health → Weight History | ![Weight](docs/screenshots/uc08_weight_history.png) |
| **UC-09** Boarding | Boarding → Boarding Stays | ![Boarding](docs/screenshots/uc09_boarding_stays.png) |
| **UC-10** Grooming | Grooming → Sessions | ![Grooming](docs/screenshots/uc10_grooming_sessions.png) |
| **UC-11** Training | Training → Sessions | ![Training](docs/screenshots/uc11_training_sessions.png) |
| **UC-12** Diet | Diet → Diet Plans | ![Diet](docs/screenshots/uc12_diet_plans.png) |
| **UC-20** Notifications | Operations → Notifications | ![Notifications](docs/screenshots/uc20_notifications.png) |

### Petget (dogs on clinic pets)

| Scenario | Menu / UI | Screenshot |
|----------|-----------|------------|
| **UC-13** Documents | **Pets → Pet Documents** | ![Documents](docs/screenshots/uc13_pet_documents.png) |
| **UC-13** Reminders | **Pets → Pet Reminders** | ![Reminders](docs/screenshots/uc13_pet_reminders.png) |
| **UC-13** AKC breed profile | Dog `x_pets` form → **Breed Profile** tab | ![Breed profile](docs/screenshots/uc13_dog_breed_profile_tab.png) |

### Enterprise — CRM, sales, POS, FSM

| Scenario | App | Screenshot |
|----------|-----|------------|
| **UC-14** New pet owner lead | CRM | ![CRM](docs/screenshots/uc14_crm_pipeline.png) |
| **UC-15** Bill consultation | Sales → Orders | ![Sales](docs/screenshots/uc15_sales_orders.png) |
| **UC-16** Front-desk retail | Point of Sale | ![POS](docs/screenshots/uc16_pos.png) |
| **UC-17** Home visit | Field Service | ![FSM](docs/screenshots/uc17_field_service.png) |
| **UC-19** Files & SOPs | Documents / Knowledge | ![Documents](docs/screenshots/uc19_documents.png) · [Knowledge](docs/screenshots/uc19_knowledge.png) |

### Configuration

| Scenario | Where | Screenshot |
|----------|--------|------------|
| **UC-21** Clinic species | **Pets → Configuration → Species** | ![Species](docs/screenshots/uc21_clinic_species.png) |
| **UC-21** PM settings | **Settings → Pet Management** | ![PM settings](docs/screenshots/uc21_pm_settings.png) |

### End-to-end day (reference flow)

```mermaid
sequenceDiagram
    participant Owner
    participant Web as Website
    participant Clinic as Pets x_pets
    participant PM as Pet Management
    participant Bill as Sales

    Owner->>Web: Book appointment (optional)
    Clinic->>Clinic: Consultation line + vitals
    Clinic->>PM: Sync / medical visit
    Clinic->>Bill: Sales order from consultation
    PM->>Owner: Vaccination reminder
```

1. Confirm **Calendar** or walk-in.  
2. **Pets → Pets** → consultation.  
3. **Create Sales Order** from line (or Sales app).  
4. **Pet Management** for longitudinal health / reminders.  
5. **Petget** documents & reminders on dogs.

---

## Which screen when?

| Task | Use |
|------|-----|
| Consultation chart, labs, visit billing | **Pets** (`x_pets` + consultation lines) |
| Public online booking | **Website** `/appointment` + **Calendar** |
| SOAP, vaccines, weight, boarding, grooming | **Pet Management** (`pet.pet`) |
| AKC breed card, pedigree, Petget files | **Pets** form (dog) + **Pet Documents / Reminders** |
| CRM pipeline, quotes, POS, home visits | Standard Enterprise apps |

Details: **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)** (full step-by-step for all 24 use cases).

---

## Documentation

| Document | Description |
|----------|-------------|
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | Complete user guide & workflows |
| [docs/PET_MANAGEMENT_BRIDGE_PLAN.md](docs/PET_MANAGEMENT_BRIDGE_PLAN.md) | Technical bridge architecture & phases |
| [tests/playwright/README.md](tests/playwright/README.md) | Screenshot automation setup |
| [docs/screenshots/](docs/screenshots/) | UI captures (`uc*.png`) |

---

## Tools (`D:\odoo\odoo19\tools\`)

| Script | Purpose |
|--------|---------|
| `seed_veterinary_demo_data.py` | Base pets, consultations, CRM |
| `seed_veterinary_100_pets.py` | Expand pet registry |
| `seed_odoo_sh_veterinary_all.py` | Full remote demo seed |
| `test_pet_management_bridge.py` | Verify `x_pets` ↔ `pet.pet` links |
| `odoo_run_context.py` | Local / Odoo.sh RPC helper |

---

## Regenerate screenshots

Requires Odoo running with demo data and modules installed.

```powershell
cd tests\playwright
copy .env.example .env
npm install
npx playwright install chromium
$env:ODOO_PASSWORD = "admin"
npm run test:screenshots
npm run copy:screenshots   # optional: refresh docs/screenshots/
```

Environment variables: `ODOO_URL`, `ODOO_DB`, `ODOO_LOGIN`, `ODOO_PASSWORD` — see [tests/playwright/.env.example](tests/playwright/.env.example).

---

## Repository layout

```
veterinarian_19/                       ← repo root = addons_path
├── README.md
├── docs/USER_GUIDE.md
├── docs/PET_MANAGEMENT_BRIDGE_PLAN.md
├── docs/screenshots/
├── veterinary_clinic/
├── veterinary_petget_bridge/
├── veterinary_pet_management_bridge/
├── pet_management/
├── petget_core/ · petget_dog/ · petget_dog_knowledge/
├── base_industry_data/ · pos_stock/ · planning_field_service_worksheet/
└── tests/playwright/
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Settings crash `auto_generate_microchip` undefined | Upgrade `pet_management`, restart Odoo, hard-refresh browser |
| **Pet Management** button missing on `x_pets` | Install `veterinary_pet_management_bridge` |
| Sync skips pets | Set **owner**; use mapped species (Cat, Dog, Hamster, Rabbit) |
| Playwright login fails | Use `/web/login`; set `ODOO_PASSWORD` |
| Empty screenshot lists | Run seed scripts; confirm database `neo_odoo` |

---

## License

- **Veterinary Clinic** (Odoo S.A.): OEEL-1  
- **Pet Management** (WebbyCrown): LGPL-3  
- **Petget** (BSD): AGPL-3  
- **Bridge modules** (demo): LGPL-3  

---

*Built for Odoo 19 Enterprise veterinary industry demos — Edafa / neo_odoo, June 2026.*
