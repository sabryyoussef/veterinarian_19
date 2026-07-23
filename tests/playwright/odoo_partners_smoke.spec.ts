/**
 * Odoo Partners directory smoke — PetSpot Test only.
 *
 *   export ODOO_TEST_URL=http://127.0.0.1:8028
 *   export ODOO_TEST_DB=pet_spot_elsahel_test
 *   export ODOO_TEST_LOGIN=admin ODOO_TEST_PASSWORD=admin
 *   npm run test:odoo-partners
 */
import { test, expect, request as playwrightRequest } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";
import { fileURLToPath } from "url";
import {
  ODOO_URL,
  ODOO_DB,
  assertTestEnvironment,
  shot,
  authenticateApi,
  callKw,
  loginUi,
  actionId,
} from "./helpers/intake.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SHOTS = path.join(__dirname, "screenshots", "odoo_partners");

async function opShot(page: Page, name: string): Promise<string> {
  fs.mkdirSync(SHOTS, { recursive: true });
  return shot(page, SHOTS, name);
}

test.describe.configure({ mode: "serial" });

let api: APIRequestContext;

test.beforeAll(async () => {
  assertTestEnvironment();
  api = await playwrightRequest.newContext();
  await authenticateApi(api);
});

test.afterAll(async () => {
  await api?.dispose();
});

test("Odoo Partners directory + outreach lead + clinic untouched", async ({
  page,
}) => {
  assertTestEnvironment();
  expect(ODOO_URL).toContain("8028");
  expect(ODOO_DB).toBe("pet_spot_elsahel_test");

  const hubPartnerCat = await callKw(
    api,
    "ir.model.data",
    "check_object_reference",
    ["developer_hub", "category_odoo_partner"],
  );
  const catId = hubPartnerCat[1];
  const tagged = await callKw(api, "res.partner", "search_count", [
    [["category_id", "in", [catId]]],
  ]);
  expect(tagged).toBeGreaterThan(10);

  await loginUi(page);
  await opShot(page, "01_home");

  // Developer Hub → Odoo Partners action (same pattern as Gate C)
  const partnerAction = await actionId(
    api,
    "developer_hub.action_developer_partner_contacts",
  );
  await page.goto(`${ODOO_URL}/odoo/action-${partnerAction}`);
  await expect(page.getByText(/Odoo Partners/i).first()).toBeVisible({
    timeout: 30000,
  });
  await opShot(page, "02_odoo_partners_list");

  // Dismiss any residual error dialogs from prior sessions
  const oops = page.getByRole("button", { name: /Close/i });
  if (await oops.count()) {
    await oops.first().click().catch(() => undefined);
  }

  // Search/filter: list should show company partners (Odoo 19 list or kanban)
  const rows = page.locator(
    ".o_list_table tbody tr.o_data_row, .o_list_renderer .o_data_row, .o_kanban_record, .o_list_view .o_data_row",
  );
  await expect(rows.first()).toBeVisible({ timeout: 45000 });
  const partnerIds: number[] = await callKw(
    api,
    "res.partner",
    "search",
    [[["category_id", "in", [catId]]]],
    { limit: 3, order: "id desc" },
  );
  expect(partnerIds.length).toBeGreaterThanOrEqual(3);

  // Search box filter sanity
  const search = page.locator(".o_searchview_input, input.o_searchview_input").first();
  if (await search.count()) {
    await search.fill("Odoo");
    await search.press("Enter").catch(() => undefined);
    await page.waitForTimeout(800);
    await opShot(page, "02b_search_filter");
  }

  for (let i = 0; i < 3; i++) {
    const pid = partnerIds[i];
    await page.goto(`${ODOO_URL}/odoo/res.partner/${pid}`);
    await expect(page.locator(".o_form_view, .o_form_sheet").first()).toBeVisible({
      timeout: 20000,
    });
    await opShot(page, `03_partner_${i + 1}`);
  }

  // Create reversible outreach lead via RPC (no send)
  const teamRef = await callKw(
    api,
    "ir.model.data",
    "check_object_reference",
    ["developer_hub", "crm_team_odoo_partner_outreach"],
  );
  const teamId = Array.isArray(teamRef) ? teamRef[1] : teamRef;
  const leadId = await callKw(api, "crm.lead", "create", [
    {
      name: `[TEST] Odoo Partner smoke ${Date.now()}`,
      partner_id: partnerIds[0],
      type: "lead",
      team_id: teamId,
    },
  ]);
  expect(leadId).toBeTruthy();
  const lead = (
    await callKw(
      api,
      "crm.lead",
      "read",
      [[leadId]],
      { fields: ["partner_id", "team_id", "name"] },
    )
  )[0];
  expect(lead.partner_id[0]).toBe(partnerIds[0]);
  expect(lead.team_id[0]).toBe(teamId);

  // Archive/cancel the test lead (reversible cleanup)
  await callKw(api, "crm.lead", "write", [[leadId], { active: false }]);

  // Clinic contacts still accessible
  await page.goto(`${ODOO_URL}/odoo/contacts`);
  await expect(
    page.getByText(/Contacts|Customers|Partners/i).first(),
  ).toBeVisible({ timeout: 30000 });
  await opShot(page, "04_clinic_contacts");

  // Clinic Hub app still present on home
  await page.goto(`${ODOO_URL}/odoo`);
  await page.waitForTimeout(800);
  const clinicApp = page
    .locator(".o_app, .o_home_menu .o_app")
    .filter({ hasText: /Clinic Hub/i })
    .first();
  expect(await clinicApp.count()).toBeGreaterThan(0);
  await opShot(page, "05_apps_home");

  // No pet created for smoke partner
  const petCount = await callKw(
    api,
    "pet.pet",
    "search_count",
    [[["owner_id", "=", partnerIds[0]]]],
  ).catch(() => 0);
  expect(petCount).toBe(0);

  fs.writeFileSync(
    path.join(SHOTS, "results.json"),
    JSON.stringify(
      {
        url: ODOO_URL,
        db: ODOO_DB,
        tagged,
        openedPartners: partnerIds,
        leadId,
        petCount,
        ok: true,
      },
      null,
      2,
    ),
  );
});
