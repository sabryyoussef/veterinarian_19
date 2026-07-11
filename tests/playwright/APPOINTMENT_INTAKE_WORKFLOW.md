# Appointment Intake — Reception Workflows

Documented reception scenarios for the Appointment Intake UX.

**Environment:** test only (`pet_spot_elsahel_test` / `https://test.drpaws.ai` / port `8028`).

**Automation:** Playwright suite at `tests/playwright/appointment_intake.spec.ts` (existing Playwright infrastructure under `tests/playwright/`, not a new nested package under `pet_management/tests/playwright/`).

**Prefix for disposable data:** `PW-INTAKE-<timestamp>`

---

## Workflow A — Owner with one existing pet

1. Open the Pets application.
2. Verify Appointments kanban is the landing page.
3. Create a new appointment.
4. Select an owner with exactly one pet.
5. Verify the pet is auto-selected.
6. Verify **Phone / Mobile** appears once only.
7. Verify Primary Type defaults to **Emergency**.
8. Verify **Medical** is enabled.
9. Save the appointment.
10. Confirm the appointment.
11. Verify the expected medical visit is created (emergency mapping).
12. Verify amount displays even when zero (`0.00` on kanban/form).

---

## Workflow B — Owner with multiple pets

1. Create a new appointment.
2. Select an owner with at least two pets.
3. Verify no pet is auto-selected.
4. Verify the pet dropdown is restricted to that owner’s pets.
5. Select one pet.
6. Save and confirm.
7. Verify owner/pet consistency (mismatch rejected server-side).

---

## Workflow C — Owner with no pets

1. Create a new appointment.
2. Select an owner with no pets.
3. Save the draft appointment.
4. Verify confirm and billing actions are unavailable or rejected.
5. Open **Pet / Health Details**.
6. Create a new pet.
7. Leave health fields blank.
8. Save the wizard.
9. Verify the pet is linked to the owner.
10. Verify the pet is assigned to the appointment.
11. Verify empty health values display as `No`.
12. Reopen the wizard.
13. Add a real allergy note.
14. Save.
15. Verify the real note is preserved.
16. Confirm the appointment.
17. Verify the emergency medical visit is created correctly.

---

## Workflow D — Guard validation

1. Create or open a draft appointment with owner but no pet.
2. Attempt to confirm through the UI.
3. Verify the action is hidden or blocked.
4. Trigger the operation through RPC / model method.
5. Verify the server rejects with:  
   `Select or create a pet before confirming or billing this appointment.`
6. Verify no sale order, invoice, or medical visit was created.

---

## Workflow E — Existing pet edit

1. Open a saved appointment with an existing pet.
2. Open **Pet / Health Details**.
3. Edit a health note.
4. Save.
5. Verify the same pet record was updated.
6. Verify no duplicate pet was created.

---

## Operational methods protected (server-side)

- `set_to_confirmed`, `set_to_in_progress`, `set_to_done`
- Direct `write` of operational states without `pet_id`
- `action_send_notification`, `action_create_reminder_notification`
- `action_create_facility_entry`, `action_create_medical_visit`, and other facility creators
- `action_create_or_open_sale_order` / `action_create_invoice`
- `action_confirm_and_create_invoice`
- `action_open_additional_invoice_wizard`, `action_register_appointment_payment`

Helper: `pet.appointment._check_pet_required_for_operation()`
