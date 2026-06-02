/**
 * USER_GUIDE.md scenario screenshots (Playwright).
 *
 * Prerequisites:
 *   - Odoo on ODOO_URL (default http://127.0.0.1:8076), DB neo_odoo
 *   - veterinary_clinic, pet_management, bridges installed
 *   - Demo/seed data (pets named Max, Buddy, etc.)
 *
 * Run:
 *   cd projects/edafa__veterinary_demo/tests/playwright
 *   npm install && npx playwright install chromium
 *   set ODOO_PASSWORD=admin && npm run test:screenshots
 *
 * Output: ./screenshots/uc*.png
 */
import { test, expect, request as playwrightRequest } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";
import { fileURLToPath } from "url";
import {
  BASE,
  PASSWORD,
  authenticateSession,
  loginBackend,
  openBackendView,
  resolveActionIds,
  searchOneId,
  callKw,
} from "./helpers/odoo.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SHOTS = path.join(__dirname, "screenshots");

const REQUIRED_ACTIONS = [
  "veterinary_clinic.action_window_pets",
  "veterinary_clinic.consultations_pet_line_action_window",
  "veterinary_petget_bridge.action_all_pet_documents",
  "veterinary_petget_bridge.action_all_pet_reminders",
  "veterinary_clinic.species_window_action",
  "pet_management.action_pet_pet",
  "pet_management.action_pet_appointment",
  "pet_management.action_pet_medical_visit",
  "pet_management.action_pet_vaccination",
  "pet_management.action_pet_weight",
  "pet_management.action_pet_boarding",
  "pet_management.action_pet_grooming_session",
  "pet_management.action_pet_training_session",
  "pet_management.action_pet_diet_plan",
  "pet_management.action_pet_notification",
  "pet_management.action_pet_management_settings",
  "crm.crm_lead_action_pipeline",
  "sale.action_orders",
  "calendar.action_calendar_event",
] as const;

const OPTIONAL_ACTIONS = [
  "industry_fsm.project_task_action_fsm",
  "point_of_sale.action_client_pos_menu",
  "documents.document_action",
  "knowledge.knowledge_article_action",
] as const;

type DemoIds = {
  clinicPetId: number | null;
  dogPetId: number | null;
  pmPetId: number | null;
  consultationId: number | null;
};

async function loadDemoIds(api: APIRequestContext): Promise<DemoIds> {
  const clinicPetId = await searchOneId(api, "x_pets", [["x_name", "=", "Max"]]);
  const dogSpeciesId = await searchOneId(api, "x_species", [["x_name", "=", "Dog"]]);
  const dogPetId =
    (clinicPetId && dogSpeciesId
      ? await searchOneId(api, "x_pets", [
          ["id", "=", clinicPetId],
          ["x_species", "=", dogSpeciesId],
        ])
      : null) ||
    (dogSpeciesId
      ? await searchOneId(api, "x_pets", [["x_species", "=", dogSpeciesId]])
      : null);
  const pmPetId =
    (await searchOneId(api, "pet.pet", [["x_pets_id", "!=", false]])) ||
    (await searchOneId(api, "pet.pet", []));
  let consultationId: number | null = null;
  if (clinicPetId) {
    consultationId = await searchOneId(api, "x_pets_line_model", [
      ["x_pets_id", "=", clinicPetId],
    ]);
  }
  if (!consultationId) {
    consultationId = await searchOneId(api, "x_pets_line_model", []);
  }
  return { clinicPetId, dogPetId, pmPetId, consultationId };
}

async function shot(page: Page, filename: string, fullPage = true): Promise<void> {
  await page.screenshot({
    path: path.join(SHOTS, filename),
    fullPage,
  });
}

test.describe.configure({ mode: "serial" });

test.describe("Veterinary demo — USER_GUIDE screenshots", () => {
  test.skip(!PASSWORD, "Set ODOO_PASSWORD (e.g. admin) to run screenshot tests.");

  let actionIds: Map<string, number>;
  let demo: DemoIds;

  test.beforeAll(async () => {
    fs.mkdirSync(SHOTS, { recursive: true });
    const api = await playwrightRequest.newContext({ baseURL: BASE });
    await authenticateSession(api);
    actionIds = await resolveActionIds(api, [...REQUIRED_ACTIONS], false);
    const optional = await resolveActionIds(api, [...OPTIONAL_ACTIONS], true);
    optional.forEach((v, k) => actionIds.set(k, v));
    demo = await loadDemoIds(api);
    await api.dispose();
  });

  test("capture all user-guide scenarios", async ({ browser }) => {
    const ctx = await browser.newContext({
      baseURL: BASE,
      viewport: { width: 1920, height: 1080 },
    });
    const page = await ctx.newPage();
    const consoleErrors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        consoleErrors.push(msg.text());
      }
    });

    await loginBackend(page);

    // UC-01 / UC-02 — Clinic pets registry + bridge
    await test.step("UC-01 Clinic pets list", async () => {
      await openBackendView(
        page,
        {
          actionXmlId: "veterinary_clinic.action_window_pets",
          model: "x_pets",
          viewType: "list",
        },
        actionIds,
      );
      await shot(page, "uc01_clinic_pets_list.png");
    });

    await test.step("UC-01 Clinic pet form (bridge)", async () => {
      test.skip(!demo.clinicPetId, "No clinic pet Max in database");
      await openBackendView(
        page,
        {
          actionXmlId: "veterinary_clinic.action_window_pets",
          model: "x_pets",
          viewType: "form",
          recordId: demo.clinicPetId!,
        },
        actionIds,
      );
      await shot(page, "uc01_clinic_pet_form_bridge.png");
    });

    // UC-03 — Website appointments (public)
    await test.step("UC-03 Website appointment booking", async () => {
      const web = await browser.newContext({ baseURL: BASE });
      const wpage = await web.newPage();
      await wpage.goto("/appointment");
      await wpage.waitForSelector("body", { timeout: 60_000 });
      await wpage.waitForTimeout(1500);
      await wpage.screenshot({
        path: path.join(SHOTS, "uc03_website_appointment.png"),
        fullPage: true,
      });
      await web.close();
    });

    // UC-04 — PM appointments
    await test.step("UC-04 Pet Management appointments", async () => {
      await openBackendView(
        page,
        {
          actionXmlId: "pet_management.action_pet_appointment",
          model: "pet.appointment",
          viewType: "list",
        },
        actionIds,
      );
      await shot(page, "uc04_pm_appointments_list.png");
    });

    // UC-05 — Consultations
    await test.step("UC-05 Consultations list", async () => {
      await openBackendView(
        page,
        {
          actionXmlId: "veterinary_clinic.consultations_pet_line_action_window",
          model: "x_pets_line_model",
          viewType: "list",
        },
        actionIds,
      );
      await shot(page, "uc05_consultations_list.png");
    });

    await test.step("UC-05 Consultation form", async () => {
      test.skip(!demo.consultationId, "No consultation lines seeded");
      await openBackendView(
        page,
        {
          actionXmlId: "veterinary_clinic.consultations_pet_line_action_window",
          model: "x_pets_line_model",
          viewType: "form",
          recordId: demo.consultationId!,
        },
        actionIds,
      );
      await shot(page, "uc05_consultation_form.png");
    });

    // UC-06 — Medical visits
    await test.step("UC-06 Medical visits", async () => {
      await openBackendView(
        page,
        {
          actionXmlId: "pet_management.action_pet_medical_visit",
          model: "pet.medical.visit",
          viewType: "list",
        },
        actionIds,
      );
      await shot(page, "uc06_medical_visits.png");
    });

    // UC-07 — Vaccinations
    await test.step("UC-07 Vaccinations", async () => {
      await openBackendView(
        page,
        {
          actionXmlId: "pet_management.action_pet_vaccination",
          model: "pet.vaccination",
          viewType: "list",
        },
        actionIds,
      );
      await shot(page, "uc07_vaccinations.png");
    });

    // UC-08 — Weight history
    await test.step("UC-08 Weight history", async () => {
      await openBackendView(
        page,
        {
          actionXmlId: "pet_management.action_pet_weight",
          model: "pet.weight.history",
          viewType: "list",
        },
        actionIds,
      );
      await shot(page, "uc08_weight_history.png");
    });

    // UC-09 — Boarding
    await test.step("UC-09 Boarding stays", async () => {
      await openBackendView(
        page,
        {
          actionXmlId: "pet_management.action_pet_boarding",
          model: "pet.boarding.stay",
          viewType: "list",
        },
        actionIds,
      );
      await shot(page, "uc09_boarding_stays.png");
    });

    // UC-10 — Grooming
    await test.step("UC-10 Grooming sessions", async () => {
      await openBackendView(
        page,
        {
          actionXmlId: "pet_management.action_pet_grooming_session",
          model: "pet.grooming.session",
          viewType: "list",
        },
        actionIds,
      );
      await shot(page, "uc10_grooming_sessions.png");
    });

    // UC-11 — Training
    await test.step("UC-11 Training sessions", async () => {
      await openBackendView(
        page,
        {
          actionXmlId: "pet_management.action_pet_training_session",
          model: "pet.training.session",
          viewType: "list",
        },
        actionIds,
      );
      await shot(page, "uc11_training_sessions.png");
    });

    // UC-12 — Diet
    await test.step("UC-12 Diet plans", async () => {
      await openBackendView(
        page,
        {
          actionXmlId: "pet_management.action_pet_diet_plan",
          model: "pet.diet.plan",
          viewType: "list",
        },
        actionIds,
      );
      await shot(page, "uc12_diet_plans.png");
    });

    // UC-13 — Petget documents / reminders / dog profile
    await test.step("UC-13 Pet documents", async () => {
      await openBackendView(
        page,
        {
          actionXmlId: "veterinary_petget_bridge.action_all_pet_documents",
          model: "petget.document",
          viewType: "list",
        },
        actionIds,
      );
      await shot(page, "uc13_pet_documents.png");
    });

    await test.step("UC-13 Pet reminders", async () => {
      await openBackendView(
        page,
        {
          actionXmlId: "veterinary_petget_bridge.action_all_pet_reminders",
          model: "petget.reminder",
          viewType: "list",
        },
        actionIds,
      );
      await shot(page, "uc13_pet_reminders.png");
    });

    await test.step("UC-13 Dog pet form (Petget)", async () => {
      test.skip(!demo.dogPetId, "No dog clinic pet found");
      await openBackendView(
        page,
        {
          actionXmlId: "veterinary_clinic.action_window_pets",
          model: "x_pets",
          viewType: "form",
          recordId: demo.dogPetId!,
        },
        actionIds,
      );
      const breedTab = page.getByRole("tab", { name: /Breed Profile/i });
      if (await breedTab.isVisible().catch(() => false)) {
        await breedTab.click();
        await page.waitForTimeout(500);
      }
      await shot(page, "uc13_dog_breed_profile_tab.png");
    });

    // UC-14 — CRM
    await test.step("UC-14 CRM pipeline", async () => {
      await openBackendView(
        page,
        {
          actionXmlId: "crm.crm_lead_action_pipeline",
          model: "crm.lead",
          viewType: "list",
        },
        actionIds,
      );
      await shot(page, "uc14_crm_pipeline.png");
    });

    // UC-15 — Sales
    await test.step("UC-15 Sales orders", async () => {
      await openBackendView(
        page,
        {
          actionXmlId: "sale.action_orders",
          model: "sale.order",
          viewType: "list",
        },
        actionIds,
      );
      await shot(page, "uc15_sales_orders.png");
    });

    // UC-16 — POS
    await test.step("UC-16 Point of Sale", async () => {
      try {
        await openBackendView(
          page,
          {
            actionXmlId: "point_of_sale.action_client_pos_menu",
            model: "pos.config",
            viewType: "list",
          },
          actionIds,
        );
        await shot(page, "uc16_pos.png");
      } catch {
        await openBackendView(
          page,
          { model: "pos.config", viewType: "list" },
          actionIds,
        );
        await shot(page, "uc16_pos.png");
      }
    });

    // UC-17 — Field Service
    await test.step("UC-17 Field Service tasks", async () => {
      test.skip(
        !actionIds.has("industry_fsm.project_task_action_fsm"),
        "FSM not installed",
      );
      await openBackendView(
        page,
        {
          actionXmlId: "industry_fsm.project_task_action_fsm",
          model: "project.task",
          viewType: "kanban",
        },
        actionIds,
      );
      await shot(page, "uc17_field_service.png");
    });

    // UC-18 — Calendar / appointments
    await test.step("UC-18 Calendar appointments", async () => {
      await openBackendView(
        page,
        {
          actionXmlId: "calendar.action_calendar_event",
          model: "calendar.event",
          viewType: "calendar",
        },
        actionIds,
      );
      await page.waitForTimeout(1200);
      await shot(page, "uc18_calendar.png");
    });

    // UC-19 — Documents & Knowledge
    await test.step("UC-19 Documents", async () => {
      test.skip(
        !actionIds.has("documents.document_action"),
        "Documents app not installed",
      );
      await openBackendView(
        page,
        {
          actionXmlId: "documents.document_action",
          model: "documents.document",
          viewType: "list",
        },
        actionIds,
      );
      await shot(page, "uc19_documents.png");
    });

    await test.step("UC-19 Knowledge", async () => {
      test.skip(
        !actionIds.has("knowledge.knowledge_article_action"),
        "Knowledge app not installed",
      );
      await openBackendView(
        page,
        {
          actionXmlId: "knowledge.knowledge_article_action",
          model: "knowledge.article",
          viewType: "list",
        },
        actionIds,
      );
      await shot(page, "uc19_knowledge.png");
    });

    // UC-20 — Notifications
    await test.step("UC-20 PM notifications", async () => {
      await openBackendView(
        page,
        {
          actionXmlId: "pet_management.action_pet_notification",
          model: "pet.notification",
          viewType: "list",
        },
        actionIds,
      );
      await shot(page, "uc20_notifications.png");
    });

    // UC-21 — Configuration
    await test.step("UC-21 Clinic species config", async () => {
      await openBackendView(
        page,
        {
          actionXmlId: "veterinary_clinic.species_window_action",
          model: "x_species",
          viewType: "list",
        },
        actionIds,
      );
      await shot(page, "uc21_clinic_species.png");
    });

    await test.step("UC-21 PM settings", async () => {
      await openBackendView(
        page,
        {
          actionXmlId: "pet_management.action_pet_management_settings",
          model: "res.config.settings",
          viewType: "form",
        },
        actionIds,
      );
      await page.waitForTimeout(800);
      await shot(page, "uc21_pm_settings.png");
    });

    // PM pet + clinic smart button
    await test.step("UC-PM pet form with clinic link", async () => {
      test.skip(!demo.pmPetId, "No pet.pet linked to clinic");
      await openBackendView(
        page,
        {
          actionXmlId: "pet_management.action_pet_pet",
          model: "pet.pet",
          viewType: "form",
          recordId: demo.pmPetId!,
        },
        actionIds,
      );
      await shot(page, "uc_pm_pet_form_clinic_button.png");
    });

    await ctx.close();

    const critical = consoleErrors.filter(
      (e) =>
        !e.includes("favicon") &&
        !e.includes("ResizeObserver") &&
        !e.includes("Warning"),
    );
    if (critical.length) {
      await test.info().attach("console-errors", {
        body: critical.join("\n"),
        contentType: "text/plain",
      });
    }

    const files = fs.readdirSync(SHOTS).filter((f) => f.endsWith(".png"));
    expect(files.length).toBeGreaterThanOrEqual(15);
  });
});
