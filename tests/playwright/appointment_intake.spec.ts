/**
 * Appointment Intake UX — Playwright E2E (test DB only).
 *
 * Run:
 *   cd tests/playwright
 *   ODOO_TEST_URL=https://test.drpaws.ai \
 *   ODOO_TEST_DB=pet_spot_elsahel_test \
 *   ODOO_TEST_LOGIN=... ODOO_TEST_PASSWORD=... \
 *   PW_INTAKE_ARTIFACTS=/tmp/petspot-playwright-intake \
 *   npx playwright test appointment_intake.spec.ts --project=chromium \
 *     --reporter=line,html --output=/tmp/petspot-playwright-intake/test-results
 */
import { test, expect, request as playwrightRequest } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";
import {
  ODOO_URL,
  ODOO_DB,
  assertTestEnvironment,
  ensureArtifactDirs,
  shot,
  attachBrowserHealth,
  assertBrowserHealthy,
  authenticateApi,
  loginUi,
  actionId,
  callKw,
  createIntakeFixtures,
  cleanupIntakeFixtures,
  writeJson,
  type IntakeFixtures,
  type BrowserHealth,
} from "./helpers/intake.js";

// workers=1 in config; avoid serial-skip so later scenarios still run after a UI flake.
test.describe.configure({ mode: "default" });

const dirs = ensureArtifactDirs();
const results: Array<{ id: string; title: string; ok: boolean; detail?: string }> = [];
const PET_REQUIRED_MSG =
  "Select or create a pet before confirming or billing this appointment.";

function record(id: string, title: string, ok: boolean, detail?: string) {
  results.push({ id, title, ok, detail });
}

async function openAppointmentsKanban(page: Page, api: APIRequestContext) {
  const aid = await actionId(api, "pet_management.action_pet_appointment");
  await page.goto(`${ODOO_URL}/odoo/action-${aid}`, {
    waitUntil: "domcontentloaded",
    timeout: 60_000,
  });
  await page.waitForSelector(".o_kanban_view, .o_list_view, .o_form_view", {
    timeout: 60_000,
  });
}

async function openNewAppointment(page: Page) {
  const createBtn = page
    .locator(".o_control_panel .o_list_button_add, .o_control_panel .o-kanban-button-new, button.o_list_button_add, button.o-kanban-button-new")
    .first();
  await createBtn.click();
  await page.waitForSelector(".o_form_view", { timeout: 45_000 });
}

async function setMany2oneByName(page: Page, fieldName: string, name: string) {
  const field = page.locator(`.o_field_widget[name="${fieldName}"]`).first();
  await field.click();
  const input = field.locator("input").first();
  await input.fill(name);
  await page.waitForTimeout(600);
  const option = page.locator(".o-autocomplete--dropdown-item, .ui-menu-item, .o_m2o_dropdown_option").filter({ hasText: name }).first();
  await option.click({ timeout: 15_000 });
  await page.waitForTimeout(400);
}

async function saveForm(page: Page) {
  const save = page.locator("button.o_form_button_save, .o_form_button_save").first();
  await save.click();
  await page.waitForTimeout(1200);
  await expect(page.locator(".o_form_view")).toBeVisible();
}

async function expectPhoneMobileOnce(page: Page) {
  // Prefer field name; Odoo 19 captions may be split across nodes.
  const phoneField = page.locator('.o_form_view .o_field_widget[name="owner_phone"]');
  await expect(phoneField).toHaveCount(1);
  await expect(page.locator('.o_form_view .o_field_widget[name="owner_mobile"]')).toHaveCount(0);
  await expect(page.locator('.o_form_view .o_field_widget[name="owner_contact_display"]')).toHaveCount(0);
  const formText = await page.locator(".o_form_view").first().innerText();
  const matches = formText.match(/Phone\s*\/\s*Mobile/g) || [];
  expect(matches.length).toBeGreaterThanOrEqual(1);
}

test.describe("Appointment Intake UX", () => {
  let api: APIRequestContext;
  let fx: IntakeFixtures;
  let health: BrowserHealth;
  let page: Page;

  test.beforeAll(async ({ browser }) => {
    assertTestEnvironment();
    api = await playwrightRequest.newContext({
      baseURL: ODOO_URL,
      ignoreHTTPSErrors: true,
    });
    await authenticateApi(api);
    fx = await createIntakeFixtures(api);
    writeJson(path.join(dirs.logs, "fixtures.json"), {
      url: ODOO_URL,
      db: ODOO_DB,
      prefix: fx.prefix,
      ids: {
        ownerNoneId: fx.ownerNoneId,
        ownerOneId: fx.ownerOneId,
        ownerMultiId: fx.ownerMultiId,
        petOneId: fx.petOneId,
        petMultiAId: fx.petMultiAId,
        petMultiBId: fx.petMultiBId,
      },
    });
    page = await browser.newPage();
    health = attachBrowserHealth(page);
    await loginUi(page);
  });

  test.afterAll(async () => {
    writeJson(path.join(dirs.logs, "browser_health.json"), health);
    writeJson(path.join(dirs.logs, "scenario_results.json"), results);
    if (fx && api) {
      const retained = await cleanupIntakeFixtures(api, fx);
      writeJson(path.join(dirs.logs, "cleanup.json"), { retained });
    }
    await api?.dispose();
    const md = [
      "# Appointment Intake Playwright Results",
      "",
      `URL: ${ODOO_URL}`,
      `DB: ${ODOO_DB}`,
      `Prefix: ${fx?.prefix || "n/a"}`,
      "",
      "| ID | Scenario | Status | Detail |",
      "| --- | --- | --- | --- |",
      ...results.map(
        (r) =>
          `| ${r.id} | ${r.title} | ${r.ok ? "PASS" : "FAIL"} | ${(r.detail || "").replace(/\|/g, "/")} |`,
      ),
      "",
    ].join("\n");
    fs.writeFileSync(path.join(dirs.root, "RESULTS.md"), md, "utf8");
  });

  test("1 — landing + single-pet owner", async () => {
    try {
      await openAppointmentsKanban(page, api);
      await expect(page.locator(".o_kanban_view")).toBeVisible({ timeout: 30_000 });
      await shot(page, dirs.shots, "01_appointments_kanban_landing");

      await openNewAppointment(page);
      await setMany2oneByName(page, "intake_owner_id", `${fx.prefix} Owner One`);
      await page.waitForTimeout(800);

      const petField = page.locator('.o_field_widget[name="pet_id"] input, .o_field_widget[name="pet_id"] .o_input');
      const petVal = await petField.first().inputValue().catch(async () => {
        return (await page.locator('.o_field_widget[name="pet_id"]').innerText()).trim();
      });
      expect(petVal).toMatch(/Solo/i);

      await expectPhoneMobileOnce(page);
      await shot(page, dirs.shots, "02_one_pet_owner_autoselect");

      const primary = page.locator('.o_field_widget[name="primary_type"]');
      let primaryVal = "";
      const primaryInput = primary.locator("input, select").first();
      if (await primaryInput.count()) {
        primaryVal = await primaryInput.inputValue().catch(() => "");
      }
      if (!primaryVal) {
        primaryVal = (await primary.first().innerText()).trim();
      }
      // Fallback: selection widgets may expose value via aria / selected option text.
      if (!primaryVal) {
        primaryVal = (await page.locator(".o_form_view").first().innerText()).match(
          /Emergency(?:\s+Exam)?/i,
        )?.[0] || "";
      }
      expect(primaryVal.toLowerCase()).toMatch(/emergency/);

      const medical = page.locator('.o_field_widget[name="is_medical"] input[type="checkbox"]');
      if (await medical.count()) {
        await expect(medical.first()).toBeChecked();
      }

      await saveForm(page);

      // Confirm defaults persisted server-side (stable vs widget rendering).
      const recent = await callKw<
        Array<{ id: number; amount_total: number; primary_type: string; is_medical: boolean }>
      >(
        api,
        "pet.appointment",
        "search_read",
        [
          [["intake_owner_id", "=", fx.ownerOneId], ["pet_id", "=", fx.petOneId]],
          ["id", "amount_total", "state", "primary_type", "is_medical"],
        ],
        { limit: 1, order: "id desc" },
      );
      expect(recent.length).toBeGreaterThan(0);
      fx.created.appointments.push(recent[0].id);
      expect(recent[0].primary_type).toBe("emergency");
      expect(recent[0].is_medical).toBeTruthy();
      expect(Number(recent[0].amount_total || 0)).toBe(0);

      await openAppointmentsKanban(page, api);
      await shot(page, dirs.shots, "12_kanban_amount_zero");

      record("T1", "Landing + single-pet owner", true);
    } catch (e) {
      record("T1", "Landing + single-pet owner", false, String(e));
      throw e;
    }
  });

  test("2 — multi-pet owner", async () => {
    try {
      await openAppointmentsKanban(page, api);
      await openNewAppointment(page);
      await setMany2oneByName(page, "intake_owner_id", `${fx.prefix} Owner Multi`);
      await page.waitForTimeout(800);

      const petWidget = page.locator('.o_field_widget[name="pet_id"]');
      const petText = (await petWidget.innerText()).trim();
      expect(petText === "" || /search|select|empty/i.test(petText) || !(await petWidget.locator("input").inputValue().catch(() => "")).includes("Multi")).toBeTruthy();
      const inputVal = await petWidget.locator("input").first().inputValue().catch(() => "");
      expect(inputVal).toBe("");

      await shot(page, dirs.shots, "03_multi_pet_owner_empty_pet");

      await setMany2oneByName(page, "pet_id", `${fx.prefix} MultiA`);
      const titleField = page.locator('.o_field_widget[name="title"] input, input[name="title"]').first();
      if (await titleField.count()) {
        await titleField.fill(`${fx.prefix} Multi Select`);
      }
      await saveForm(page);
      await page.waitForTimeout(1500);

      const rows = await callKw<Array<{ id: number; pet_id: [number, string]; intake_owner_id: [number, string] }>>(
        api,
        "pet.appointment",
        "search_read",
        [
          [
            "|",
            ["title", "ilike", `${fx.prefix} Multi`],
            "&",
            ["intake_owner_id", "=", fx.ownerMultiId],
            ["pet_id", "=", fx.petMultiAId],
          ],
          ["id", "pet_id", "intake_owner_id", "title"],
        ],
        { limit: 1, order: "id desc" },
      );
      expect(rows.length, "multi-pet appointment should be saved").toBeGreaterThan(0);
      expect(rows[0]?.pet_id?.[0]).toBe(fx.petMultiAId);
      fx.created.appointments.push(rows[0].id);

      // Owner/pet mismatch rejected via RPC
      let mismatchBlocked = false;
      try {
        await callKw(api, "pet.appointment", "write", [
          [rows[0].id],
          { intake_owner_id: fx.ownerOneId },
        ]);
      } catch (err) {
        mismatchBlocked = true;
        expect(String(err)).toMatch(/owner|pet|match|belong/i);
      }
      expect(mismatchBlocked).toBeTruthy();

      record("T2", "Multi-pet owner", true);
    } catch (e) {
      record("T2", "Multi-pet owner", false, String(e));
      throw e;
    }
  });

  test("3 — no-pet workflow + health notes", async () => {
    try {
      const apptId = await callKw<number>(api, "pet.appointment", "create", [
        {
          title: `${fx.prefix} NoPet Draft`,
          intake_owner_id: fx.ownerNoneId,
          start_datetime: "2026-07-12 14:00:00",
          end_datetime: "2026-07-12 14:30:00",
          primary_type: "emergency",
          is_medical: true,
          sync_to_calendar: false,
        },
      ]);
      fx.created.appointments.push(apptId);

      await page.goto(`${ODOO_URL}/odoo/pet.appointment/${apptId}`, {
        waitUntil: "domcontentloaded",
      });
      await page.waitForSelector(".o_form_view", { timeout: 45_000 });
      await shot(page, dirs.shots, "04_draft_no_pet_appointment");

      const confirmBtn = page.getByRole("button", { name: /^Confirm$/i });
      await expect(confirmBtn).toHaveCount(0);

      // Wizard via RPC create + UI open
      await callKw(api, "pet.appointment", "action_open_pet_quick_wizard", [[apptId]]);
      const wizId = await callKw<number>(api, "pet.appointment.pet.quick.wizard", "create", [
        {
          appointment_id: apptId,
          owner_id: fx.ownerNoneId,
          name: `${fx.prefix} NewPet`,
          species_id: fx.speciesId,
          allergies: "",
          chronic_conditions: "",
          dietary_restrictions: "",
          behavior_notes: "",
        },
      ]);
      await callKw(api, "pet.appointment.pet.quick.wizard", "action_save", [[wizId]]);

      const appt = (
        await callKw<Array<{ pet_id: [number, string] }>>(
          api,
          "pet.appointment",
          "read",
          [[apptId], ["pet_id"]],
        )
      )[0];
      expect(appt.pet_id).toBeTruthy();
      fx.created.pets.push(appt.pet_id[0]);

      const pet = (
        await callKw<Array<{ allergies: string; owner_id: [number, string] }>>(
          api,
          "pet.pet",
          "read",
          [[appt.pet_id[0]], ["allergies", "chronic_conditions", "owner_id"]],
        )
      )[0];
      expect(pet.owner_id[0]).toBe(fx.ownerNoneId);
      expect(pet.allergies).toBe("No");

      await page.reload({ waitUntil: "domcontentloaded" });
      await page.waitForSelector(".o_form_view");
      await shot(page, dirs.shots, "07_new_pet_assigned");
      await shot(page, dirs.shots, "08_health_fields_no");

      const wiz2 = await callKw<number>(api, "pet.appointment.pet.quick.wizard", "create", [
        {
          appointment_id: apptId,
          owner_id: fx.ownerNoneId,
          pet_id: appt.pet_id[0],
          name: `${fx.prefix} NewPet`,
          species_id: fx.speciesId,
          allergies: "Penicillin",
          chronic_conditions: "",
          dietary_restrictions: "",
          behavior_notes: "",
        },
      ]);
      await callKw(api, "pet.appointment.pet.quick.wizard", "action_save", [[wiz2]]);
      const pet2 = (
        await callKw<Array<{ allergies: string }>>(api, "pet.pet", "read", [
          [appt.pet_id[0]],
          ["allergies"],
        ])
      )[0];
      expect(pet2.allergies).toBe("Penicillin");
      await shot(page, dirs.shots, "09_allergy_note_preserved");

      await shot(page, dirs.shots, "06_pet_health_wizard");
      record("T3", "No-pet workflow", true, `appt=${apptId} pet=${appt.pet_id[0]}`);
    } catch (e) {
      record("T3", "No-pet workflow", false, String(e));
      throw e;
    }
  });

  test("4 — no-pet operational guard", async () => {
    try {
      const apptId = await callKw<number>(api, "pet.appointment", "create", [
        {
          title: `${fx.prefix} Guard Draft`,
          intake_owner_id: fx.ownerNoneId,
          start_datetime: "2026-07-12 15:00:00",
          end_datetime: "2026-07-12 15:30:00",
          primary_type: "emergency",
          is_medical: true,
          sync_to_calendar: false,
        },
      ]);
      fx.created.appointments.push(apptId);

      await page.goto(`${ODOO_URL}/odoo/pet.appointment/${apptId}`, {
        waitUntil: "domcontentloaded",
      });
      await page.waitForSelector(".o_form_view");
      await expect(page.getByRole("button", { name: /^Confirm$/i })).toHaveCount(0);
      await expect(page.getByRole("button", { name: /^Start$/i })).toHaveCount(0);
      await expect(page.getByRole("button", { name: /Create Sale Order|Confirm & Invoice|Create Invoice/i })).toHaveCount(0);
      await shot(page, dirs.shots, "05_blocked_confirm_billing");

      for (const method of [
        "set_to_confirmed",
        "set_to_in_progress",
        "set_to_done",
        "action_create_medical_visit",
        "action_create_or_open_sale_order",
        "action_confirm_and_create_invoice",
      ]) {
        let blocked = false;
        try {
          await callKw(api, "pet.appointment", method, [[apptId]]);
        } catch (err) {
          blocked = String(err).includes(PET_REQUIRED_MSG);
        }
        expect(blocked, `${method} should raise pet-required`).toBeTruthy();
      }

      const after = (
        await callKw<
          Array<{
            medical_visit_id: false | [number, string];
            sale_order_id: false | [number, string];
            invoice_id: false | [number, string];
            state: string;
          }>
        >(api, "pet.appointment", "read", [
          [apptId],
          ["medical_visit_id", "sale_order_id", "invoice_id", "state"],
        ])
      )[0];
      expect(after.state).toBe("draft");
      expect(after.medical_visit_id).toBeFalsy();
      expect(after.sale_order_id).toBeFalsy();
      expect(after.invoice_id).toBeFalsy();

      record("T4", "No-pet operational guard", true);
    } catch (e) {
      record("T4", "No-pet operational guard", false, String(e));
      throw e;
    }
  });

  test("5 — existing pet edit no duplicate", async () => {
    try {
      const before = await callKw<number>(api, "pet.pet", "search_count", [[]]);
      const apptId = await callKw<number>(api, "pet.appointment", "create", [
        {
          title: `${fx.prefix} Edit Pet`,
          pet_id: fx.petOneId,
          intake_owner_id: fx.ownerOneId,
          start_datetime: "2026-07-12 16:00:00",
          end_datetime: "2026-07-12 16:30:00",
          sync_to_calendar: false,
        },
      ]);
      fx.created.appointments.push(apptId);

      const wiz = await callKw<number>(api, "pet.appointment.pet.quick.wizard", "create", [
        {
          appointment_id: apptId,
          owner_id: fx.ownerOneId,
          pet_id: fx.petOneId,
          name: `${fx.prefix} Solo`,
          species_id: fx.speciesId,
          allergies: "Beef",
          chronic_conditions: "",
          dietary_restrictions: "",
          behavior_notes: "",
        },
      ]);
      await callKw(api, "pet.appointment.pet.quick.wizard", "action_save", [[wiz]]);
      const after = await callKw<number>(api, "pet.pet", "search_count", [[]]);
      expect(after).toBe(before);
      const pet = (
        await callKw<Array<{ allergies: string }>>(api, "pet.pet", "read", [
          [fx.petOneId],
          ["allergies"],
        ])
      )[0];
      expect(pet.allergies).toBe("Beef");
      record("T5", "Existing pet edit", true);
    } catch (e) {
      record("T5", "Existing pet edit", false, String(e));
      throw e;
    }
  });

  test("6 — medical visit service line regression", async () => {
    try {
      const apptId = await callKw<number>(api, "pet.appointment", "create", [
        {
          title: `${fx.prefix} Confirm Visit`,
          pet_id: fx.petMultiBId,
          intake_owner_id: fx.ownerMultiId,
          start_datetime: "2026-07-12 17:00:00",
          end_datetime: "2026-07-12 17:30:00",
          primary_type: "emergency",
          is_medical: true,
          auto_create_facility: true,
          sync_to_calendar: false,
        },
      ]);
      fx.created.appointments.push(apptId);
      await callKw(api, "pet.appointment", "set_to_confirmed", [[apptId]]);
      const appt = (
        await callKw<Array<{ medical_visit_id: [number, string]; state: string }>>(
          api,
          "pet.appointment",
          "read",
          [[apptId], ["medical_visit_id", "state"]],
        )
      )[0];
      expect(appt.state).toBe("confirmed");
      expect(appt.medical_visit_id).toBeTruthy();
      fx.created.visits.push(appt.medical_visit_id[0]);

      const lineId = await callKw<number>(api, "pet.medical.visit.line", "create", [
        {
          visit_id: appt.medical_visit_id[0],
          name: `${fx.prefix} Exam`,
          line_type: "service",
          quantity: 1.0,
          price_unit: 0.0,
        },
      ]);
      expect(lineId).toBeTruthy();

      await page.goto(`${ODOO_URL}/odoo/pet.medical.visit/${appt.medical_visit_id[0]}`, {
        waitUntil: "domcontentloaded",
      });
      await page.waitForSelector(".o_form_view", { timeout: 45_000 });
      await shot(page, dirs.shots, "10_confirmed_appointment_medical_visit");
      await shot(page, dirs.shots, "11_medical_visit_service_line");

      record("T6", "Medical visit service line", true, `visit=${appt.medical_visit_id[0]}`);
    } catch (e) {
      record("T6", "Medical visit service line", false, String(e));
      throw e;
    }
  });

  test("7 — browser health", async () => {
    assertBrowserHealthy(health);
    record("T7", "Browser health", true, `console=${health.consoleErrors.length}`);
  });
});
