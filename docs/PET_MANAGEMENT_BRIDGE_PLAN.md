# Pet Management ↔ Veterinary Clinic Bridge Plan

**Goal:** Keep **Pet Management**’s full feature set while preserving **Veterinary Clinic + Petget + Enterprise** flows already built on `x_pets`.

**Date:** June 2026  
**Modules involved:** `pet_management`, `veterinary_clinic`, `veterinary_petget_bridge`, `petget_*`

---

## 1. What each stack does today

### Pet Management (`pet_management`) — Python app, LGPL

| Area | Models | Strength |
|------|--------|----------|
| **Registry** | `pet.pet`, `pet.species`, `pet.breed` | Real ORM, chatter, sequences, microchip rules, security |
| **Health** | `pet.vaccination`, `pet.vaccine`, `pet.medical.visit`, `pet.weight.history` | SOAP visits, vaccination lifecycle, weight graphs |
| **Operations** | `pet.boarding.stay`, `pet.kennel`, `pet.grooming.*`, `pet.training.*`, `pet.diet.plan` | Boarding, grooming, training, diet — **not in clinic pack** |
| **Scheduling** | `pet.appointment` | Hub appointment → auto-creates visit/vaccination/grooming/etc., optional `calendar.event`, **invoicing** |
| **Ops** | `pet.notification`, crons, mail templates | Reminders, emails |
| **Security** | Many groups (own / all / admin per area) | Portal-style “own pets only” |

**Depends on:** `base`, `mail`, `contacts`, `hr`, `product`, `account` only — lightweight.

---

### Your stack (`veterinary_clinic` + `veterinary_petget_bridge` + Petget)

| Area | Models | Strength |
|------|--------|----------|
| **Registry** | `x_pets` (Studio) | Industry demo, seeded on Odoo.sh |
| **Consultation** | `x_pets_line_model` | Rich exam (vitals, labs, illnesses, vaccines on line) |
| **Config** | `x_species`, `x_breeds`, `x_vaccines`, `x_illnesses` | Studio data |
| **Enterprise** | `sale.order` (`x_pet`), `calendar.event` + **website** `appointment.type`, CRM, POS, FSM, planning, documents, knowledge | **Cannot drop without rework** |
| **Petget** | `x_petget_*` on `x_pets`, documents/reminders on `x_pet_id` | AKC breed card, dog lifecycle |

**Depends on:** Enterprise + Studio (`web_studio`, `website_appointment_crm`, FSM, POS, etc.).

---

## 2. Overlap map (where things collide)

```mermaid
flowchart TB
    subgraph PM [Pet Management]
        pet_pet[pet.pet]
        pet_species[pet.species]
        pet_breed[pet.breed]
        pet_med[pet.medical.visit]
        pet_vac[pet.vaccination]
        pet_appt[pet.appointment]
        pet_weight[pet.weight.history]
    end

    subgraph VC [Veterinary Clinic]
        x_pets[x_pets]
        x_species[x_species]
        x_breed[x_breeds]
        x_line[x_pets_line_model]
        cal[calendar.event]
        so[sale.order]
        web[appointment.type website]
    end

    subgraph PG [Petget Bridge]
        petget[petget docs / reminders / AKC]
    end

    pet_pet -.->|DUPLICATE registry| x_pets
    pet_species -.->|DUPLICATE| x_species
    pet_breed -.->|DUPLICATE| x_breeds
    pet_med -.->|OVERLAP| x_line
    pet_vac -.->|OVERLAP| x_vaccines + line
    pet_appt -.->|OVERLAP| cal + web
    pet_weight -.->|PARTIAL| x_line.x_weight

    x_pets --> petget
    x_line --> so
    x_pets --> cal
    x_pets --> web
```

### Overlap table

| Function | Pet Management | Your clinic | Risk if both installed as-is |
|----------|----------------|-------------|------------------------------|
| Pet master | `pet.pet` | `x_pets` | Two registries, double entry |
| Species/breed | `pet.species` / `pet.breed` | `x_species` / `x_breeds` | Duplicate masters |
| Clinical visit | `pet.medical.visit` (SOAP) | `x_pets_line_model` (exam + files) | Two “consultation” concepts |
| Vaccination | `pet.vaccination` records | `x_vaccines_given` on line | Duplicate history |
| Appointments | `pet.appointment` + calendar sync | `calendar.event` + public booking | Two schedulers |
| Weight | `pet.weight.history` + graphs | Per-consult `x_weight` only | PM richer; clinic fragmented |
| Boarding/grooming/training/diet | Full modules | None | **PM-only win** |
| Billing | `account.move` from PM appointment | `sale.order` + POS + FSM | Different pipelines |
| Petget / AKC | — | `veterinary_petget_bridge` on `x_pets` | Must stay linked to chosen master |

**Conclusion:** Do **not** merge codebases into one model overnight. Use a **bridge** with one **canonical pet** and clear ownership per domain.

---

## 3. Recommended strategy: Pet Management master + Clinic bridge

### Principle

| Layer | Owner | Why |
|-------|--------|-----|
| **Pet identity & daily ops** (health, boarding, grooming, training, diet, PM appointments) | **`pet.pet`** | Real Python, better UX, notifications |
| **Industry clinic flows** (consultation lines, POS, FSM, website booking, CRM) | **`x_pets` + `x_pets_line_model`** until migrated | Studio + Enterprise wired here today |
| **Dog knowledge & documents** | **Petget on `x_pets`** (phase 1), then **`pet.pet`** (phase 2) | Bridge already on `x_pets` |

Link the two registries with **1:1** `pet.pet` ↔ `x_pets`, sync core fields, expose everything from **one pet form**.

---

## 4. New module: `veterinary_pet_management_bridge`

**Depends on:** `veterinary_clinic`, `pet_management`, `veterinary_petget_bridge`

**Suggested install order:** clinic stack → `pet_management` → `veterinary_pet_management_bridge`

### 4.1 Data model (minimal)

On **`pet.pet`** (Python inherit):

```python
x_pets_id = fields.Many2one('x_pets', string='Clinic record', index=True, copy=False)
```

On **`x_pets`** (via bridge `ir.model.fields` XML, same pattern as Petget):

```python
pet_pet_id = fields.Many2one('pet.pet', string='Pet Management', index=True, copy=False)
```

**Constraints:** unique per company on both sides — one pair only.

### 4.2 Sync rules (bidirectional, controlled)

| Field | `pet.pet` | `x_pets` | Sync direction |
|-------|-----------|----------|----------------|
| Name | `name` | `x_name` | Both (master = `pet.pet` recommended) |
| Owner | `owner_id` | `x_owner` | Both |
| Species | `species_id` | `x_species` | **Map table** `pet.species` ↔ `x_species` |
| Breed | `breed_id` | `x_breed` | **Map table** `pet.breed` ↔ `x_breeds` |
| DOB | `dob` | `x_date_of_birth` | Both |
| Gender | `gender` | `x_gender` | Map selection values |
| Microchip | `microchip_no` | `x_microchip_number` | Both |
| Photo | `image_1920` | `x_avatar_image` | Both |
| Status | `status` | `x_active` / custom | Mapped |

Implement sync in `create` / `write` on **one side only** (recommend **`pet.pet` as write master** for profile fields). Use `context={'syncing_pet_bridge': True}` to avoid infinite loops.

### 4.3 Species/breed mapping (one-time + ongoing)

- New models: `pet.clinic.species.map` / `pet.clinic.breed.map`, **or**
- Post-init: match by `name` (Dog↔Dog, Cat↔Cat) from `x_species.xml` + `pet_seed_data.xml`.

Without mapping, PM and clinic will show different species/breed IDs for the same animal.

### 4.4 Consultation ↔ medical visit (do not merge models)

Keep both; **link on create**:

- When **`x_pets_line_model`** is created → optional auto-create **`pet.medical.visit`**:
  - `pet_id` from linked `pet.pet`
  - `date` ← `x_appointment_date`
  - `vital_signs` ← weight/temp/heart/resp
  - `subjective` / `plan` ← remarks, rehab, diet
- Add `x_consultation_id` on `pet.medical.visit` (M2O to `x_pets_line_model`).

**UI:** Smart buttons both ways (“Open SOAP visit” / “Open clinic consultation”).

You keep Studio consultation PDFs/labs **and** PM SOAP + notifications.

### 4.5 Vaccination

- **Catalog:** map `pet.vaccine` ↔ `x_vaccines` by name.
- **Events:** when line has `x_vaccines_given`, create/update `pet.vaccination` for linked `pet.pet`.
- PM = source of truth for **due dates / boosters**; clinic line = source for **that visit’s chart**.

### 4.6 Appointments (phased — hardest part)

| Phase | Behavior |
|-------|----------|
| **A** | Keep **website** on `calendar.event` + `appointment.type` (unchanged). |
| **A** | Keep **`pet.appointment`** for internal ops (boarding/grooming/medical flags). |
| **B** | On `calendar.event` create: optional `pet.appointment` if pet links to `pet.pet`. |
| **C** | PM appointment confirms → update linked `calendar.event` (optional). |

Do **not** replace website booking with `pet.appointment` until phase B is stable.

### 4.7 Petget bridge

**Phase 1:** Keep `x_pet_id` on documents/reminders; expose related counts on `pet.pet` via `x_pets_id`.

**Phase 2:** Add `pet_pet_id` on `petget.document` / `reminder` / `note`; deprecate `petget.animal`.

### 4.8 Menus & UX

- Single **“Pets”** menu under Veterinary.
- Default form: **`pet.pet`** with notebook tabs:
  - **Clinic** (smart button / embedded `x_pets`)
  - **Consultations** (`x_pets_line_ids` related)
  - **Petget** (existing bridge page)
  - PM: vaccinations, medical, boarding, grooming, training, diet, weight
- Set `pet_management` `application: False` after bridge, or demote duplicate app icon.

### 4.9 Security

- Map PM groups for clinic staff (vets → health + appointments “all data”).
- Keep PM “own data” for portal pet owners if needed.
- Record rules: `pet.pet` visible if user can see linked `x_pets` (same company).

### 4.10 Migration (Odoo.sh / existing pets)

1. Install `pet_management`.
2. Install `veterinary_pet_management_bridge`.
3. Run server action **“Sync clinic pets → pet.pet”**:
   - For each `x_pets` without `pet_pet_id`: create `pet.pet`, map species/breed/owner, set reciprocal links.
4. Backfill vaccinations/weight from consultation lines where possible.
5. **Do not delete `x_pets`** — Enterprise integrations depend on it.

---

## 5. What to keep vs retire

| Keep | Retire / hide later |
|------|---------------------|
| `pet.pet` + all PM operational models | Manual `x_pets` entry without link |
| `x_pets` + `x_pets_line_model` for clinic/POS/FSM/web | Second “Pets” menu without bridge |
| `veterinary_clinic` Enterprise data | Standalone `petget.animal` app |
| `veterinary_petget_bridge` on `x_pets` (extend later) | Broken `x_petget_breed_growth_ids` O2M on `x_pets` |
| `calendar.event` + website appointments | `pet.appointment` replacing web booking on day 1 |

---

## 6. Phased rollout

| Phase | Deliverable | Effort (est.) |
|-------|-------------|----------------|
| **0** | Install PM on dev DB; validate conflicts | 1 day |
| **1** | `veterinary_pet_management_bridge`: links + species/breed map + sync + smart buttons | 3–5 days |
| **2** | Migration script + Odoo.sh backfill for existing `x_pets` | 1–2 days |
| **3** | Consultation → `pet.medical.visit` + vaccination sync | 2–3 days |
| **4** | Weight: `x_weight` on lines → `pet.weight.history` | 1 day |
| **5** | Appointment bridge (calendar ↔ `pet.appointment`) | 3–5 days |
| **6** | Petget `pet_pet_id`; unified menus; user training | 2–3 days |

---

## 7. Module install order

1. `base_industry_data`
2. `pos_stock`
3. `planning_field_service_worksheet`
4. `petget_core` → `petget_dog` → `petget_dog_knowledge`
5. `veterinary_clinic`
6. `veterinary_petget_bridge`
7. **`pet_management`**
8. **`veterinary_pet_management_bridge`** (to be built)
9. Upgrade all; run sync job

---

## 8. Architecture decision

**Recommended canonical pet for new UI:** `pet.pet` for health/ops; `x_pets` remains the **Enterprise integration anchor** until phase 6.

**Alternative (not recommended):** Keep `x_pets` as master and bolt PM on — fights PM’s design (everything expects `pet.pet`).

---

## 9. Next step

Implement **Phase 1**: scaffold `veterinary_pet_management_bridge` with:

- Link fields (`x_pets_id` / `pet_pet_id`)
- Species/breed mapping data
- One-shot sync server action for existing clinic pets

---

## Related paths

| Item | Path |
|------|------|
| Pet Management | `projects/edafa__veterinary_demo/pet_management-19.0.1.0.0/pet_management/` |
| Veterinary Clinic | `projects/edafa__veterinary_demo/veterinary_clinic-saas-19.3.1.3/veterinary_clinic/` |
| Petget bridge | `projects/edafa__veterinary_demo/veterinary_clinic-saas-19.3.1.3/veterinary_petget_bridge/` |
| Remote seed tools | `tools/seed_odoo_sh_veterinary_all.py` |
| GitHub branch | `feature/edafa-veterinary-demo` on `veterinarian_19` |
