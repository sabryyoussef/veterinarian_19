/**
 * PetSpot Clinic end-to-end scenarios with screenshots.
 *
 * Covers: portal book/exam, incomplete cases, Odoo menus, bridge bot intents,
 * lookup API, Chatwoot (if up).
 *
 * Run:
 *   cd tests/playwright
 *   export ODOO_URL=http://127.0.0.1:8027 ODOO_DB=pet_spot_elsahel
 *   export BRIDGE_SHARED_SECRET=... PETSPOT_BRIDGE_TOKEN=...
 *   npm run test:petspot
 */
import { test, expect, request as playwrightRequest } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";
import { fileURLToPath } from "url";
import {
  ODOO_URL,
  BRIDGE_URL,
  CHATWOOT_URL,
  BRIDGE_SECRET,
  shotsDir,
  shot,
  mintPortalToken,
  portalLookup,
  triggerClinicBot,
  loginOdoo,
  openOdooPath,
  authenticateOdooApi,
  odooCallKw,
} from "./helpers/petspot.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SHOTS = shotsDir(__dirname);
const REPORT = path.join(SHOTS, "RESULTS.md");

type ScenarioResult = {
  id: string;
  title: string;
  ok: boolean;
  detail?: string;
  screenshot?: string;
};

const results: ScenarioResult[] = [];

function record(r: ScenarioResult) {
  results.push(r);
}

async function writeReport() {
  const lines = [
    "# PetSpot Clinic Playwright Results",
    "",
    `Generated: ${new Date().toISOString()}`,
    `Odoo: ${ODOO_URL}`,
    `Bridge: ${BRIDGE_URL}`,
    `Chatwoot: ${CHATWOOT_URL}`,
    "",
    "| ID | Scenario | Status | Detail | Screenshot |",
    "| --- | --- | --- | --- | --- |",
  ];
  for (const r of results) {
    const shotName = r.screenshot ? path.basename(r.screenshot) : "—";
    lines.push(
      `| ${r.id} | ${r.title} | ${r.ok ? "PASS" : "FAIL"} | ${(r.detail || "").replace(/\|/g, "/")} | ${shotName} |`,
    );
  }
  const passed = results.filter((r) => r.ok).length;
  lines.push("", `**${passed}/${results.length} passed**`, "");
  fs.writeFileSync(REPORT, lines.join("\n"), "utf8");
}

test.describe.configure({ mode: "serial" });

test.describe("PetSpot Clinic workflow", () => {
  let api: APIRequestContext;
  let bookUrl = "";
  let bookCode = "";
  let examUrl = "";
  let examCode = "";
  let visitId = 0;
  const phone = `010${String(Date.now()).slice(-8)}`;
  const owner = "Playwright Owner";
  const petName = `PW-Pet-${Date.now().toString().slice(-4)}`;

  test.beforeAll(async () => {
    api = await playwrightRequest.newContext({ ignoreHTTPSErrors: true });
  });

  test.afterAll(async () => {
    await writeReport();
    await api.dispose();
  });

  test("01 health checks (Odoo + Bridge)", async ({ page }) => {
    const odooHealth = await api.get(`${ODOO_URL}/petspot/portal/health`);
    const odooOk = odooHealth.ok();
    const odooBody = odooOk ? await odooHealth.json() : {};

    const bridgeHealth = await api.get(`${BRIDGE_URL}/health`);
    const bridgeOk = bridgeHealth.ok();

    await page.setContent(`
      <html><body style="font-family:sans-serif;padding:24px">
        <h1>PetSpot Health</h1>
        <p>Odoo portal health: <b>${odooOk ? "OK" : "FAIL"}</b> ${JSON.stringify(odooBody)}</p>
        <p>Bridge health: <b>${bridgeOk ? "OK" : "FAIL"}</b> (${bridgeHealth.status()})</p>
        <p>Odoo URL: ${ODOO_URL}</p>
        <p>Bridge URL: ${BRIDGE_URL}</p>
      </body></html>
    `);
    const file = await shot(page, SHOTS, "01_health_checks");
    record({
      id: "01",
      title: "Health checks Odoo + Bridge",
      ok: odooOk && bridgeOk,
      detail: `odoo=${odooHealth.status()} bridge=${bridgeHealth.status()}`,
      screenshot: file,
    });
    expect(odooOk, "Odoo portal health").toBeTruthy();
    expect(bridgeOk, "Bridge health").toBeTruthy();
  });

  test("02 bot intent حجز mints book link", async ({ page }) => {
    test.skip(!BRIDGE_SECRET, "BRIDGE_SHARED_SECRET not set");
    const resp = await triggerClinicBot(api, "حجز");
    const bot = (resp as { petspot_bot?: { actions?: { book_url?: string } } }).petspot_bot;
    bookUrl = bot?.actions?.book_url || "";
    expect(bookUrl, "book_url from bot").toBeTruthy();
    bookCode = bookUrl.replace(/\/$/, "").split("/").pop() || "";

    await page.setContent(`
      <html><body style="font-family:sans-serif;padding:24px;direction:rtl">
        <h1>Bot intent: حجز</h1>
        <pre>${JSON.stringify(resp, null, 2)}</pre>
        <p>Book URL:</p>
        <a href="${bookUrl}">${bookUrl}</a>
      </body></html>
    `);
    const file = await shot(page, SHOTS, "02_bot_book_intent");
    record({
      id: "02",
      title: "Bot حجز mints book link",
      ok: Boolean(bookUrl),
      detail: bookUrl,
      screenshot: file,
    });
  });

  test("03 public booking form (short link + slots)", async ({ page }) => {
    if (!bookUrl) {
      const minted = await mintPortalToken(api, {
        role: "patient",
        phone,
        owner_name: owner,
        pet_name: petName,
      });
      expect(minted.ok).toBeTruthy();
      bookUrl = minted.url || "";
      bookCode = bookUrl.replace(/\/$/, "").split("/").pop() || "";
    }

    // Prefer local short path for reliability
    const localBook = `${ODOO_URL}/p/b/${bookCode}`;
    await page.goto(localBook);
    await expect(page.locator("h1.brand")).toContainText(/حجز|PetSpot/i);
    await expect(page.locator('select[name="slot_id"], input[name="start_datetime"]')).toHaveCount(1);

    const file = await shot(page, SHOTS, "03_booking_form");
    record({
      id: "03",
      title: "Public booking form with slots",
      ok: true,
      detail: localBook,
      screenshot: file,
    });
  });

  test("04 submit booking creates appointment", async ({ page }) => {
    const localBook = `${ODOO_URL}/p/b/${bookCode}`;
    await page.goto(localBook);
    await page.locator('input[name="owner_name"]').fill(owner);
    await page.locator('input[name="phone"]').fill(phone);
    await page.locator('input[name="pet_name"]').fill(petName);

    const slot = page.locator('select[name="slot_id"]');
    if (await slot.count()) {
      const options = slot.locator("option");
      const count = await options.count();
      // pick first non-empty option
      for (let i = 0; i < count; i++) {
        const val = await options.nth(i).getAttribute("value");
        if (val) {
          await slot.selectOption(val);
          break;
        }
      }
    } else {
      const dt = new Date(Date.now() + 86400000);
      const local = dt.toISOString().slice(0, 16);
      await page.locator('input[name="start_datetime"]').fill(local);
    }

    await page.locator('button[type="submit"]').click({ noWaitAfter: true });
    await expect(page.locator("h1.brand")).toContainText(/نجاح|تم|تعذر|غير صالح/i, {
      timeout: 120_000,
    });
    const file = await shot(page, SHOTS, "04_booking_done");

    await authenticateOdooApi(api);
    const appts = await odooCallKw<Array<{ id: number; name: string }>>(
      api,
      "pet.appointment",
      "search_read",
      [[["pet_id.name", "ilike", petName]], ["id", "name", "state"]],
      { limit: 1, order: "id desc" },
    );
    const ok = appts.length > 0;
    record({
      id: "04",
      title: "Submit booking creates appointment",
      ok,
      detail: ok ? `appt=${appts[0].name} state=${(appts[0] as { state?: string }).state}` : "no appointment",
      screenshot: file,
    });
    expect(ok).toBeTruthy();
  });

  test("05 bot/status and exam token after booking", async ({ page }) => {
    const lookup = await portalLookup(api, phone);
    const examPending = Boolean(lookup.exam_pending || lookup.exam_url);
    examUrl = String(lookup.exam_url || "");

    if (!examUrl) {
      const appts = await odooCallKw<Array<{ id: number }>>(
        api,
        "pet.appointment",
        "search_read",
        [[["pet_id.name", "ilike", petName]], ["id"]],
        { limit: 1, order: "id desc" },
      );
      if (appts[0]) {
        const minted = await mintPortalToken(api, {
          role: "vet",
          phone,
          owner_name: owner,
          pet_name: petName,
          appointment_id: appts[0].id,
        });
        examUrl = minted.url || "";
      }
    }
    examCode = examUrl.replace(/\/$/, "").split("/").pop() || "";

    let statusBot: Record<string, unknown> = {};
    if (BRIDGE_SECRET) {
      statusBot = await triggerClinicBot(api, `حالة ${phone}`);
    }

    await page.setContent(`
      <html><body style="font-family:sans-serif;padding:24px;direction:rtl">
        <h1>Lookup + Status after booking</h1>
        <h2>Lookup API</h2>
        <pre>${JSON.stringify(lookup, null, 2)}</pre>
        <h2>Status bot</h2>
        <pre>${JSON.stringify(statusBot, null, 2)}</pre>
        <p>Exam URL: ${examUrl || "—"}</p>
      </body></html>
    `);
    const file = await shot(page, SHOTS, "05_status_and_exam_link");
    const ok = Boolean(examUrl) || examPending;
    record({
      id: "05",
      title: "Status lookup + exam link after booking",
      ok,
      detail: examUrl || JSON.stringify(lookup).slice(0, 120),
      screenshot: file,
    });
    expect(ok).toBeTruthy();
  });

  test("06 public exam form (SOAP lite)", async ({ page }) => {
    expect(examCode, "exam short code").toBeTruthy();
    const localExam = `${ODOO_URL}/p/e/${examCode}`;
    await page.goto(localExam);
    await expect(page.locator("h1.brand")).toContainText(/كشف|PetSpot/i);
    await expect(page.locator('input[name="reason"]')).toBeVisible();
    const file = await shot(page, SHOTS, "06_exam_form");
    record({
      id: "06",
      title: "Public exam form",
      ok: true,
      detail: localExam,
      screenshot: file,
    });
  });

  test("07 submit exam creates incomplete visit", async ({ page }) => {
    const localExam = `${ODOO_URL}/p/e/${examCode}`;
    await page.goto(localExam);
    await expect(page.locator('input[name="reason"]')).toBeVisible();
    await shot(page, SHOTS, "07a_exam_form_before_submit");

    // Submit via API (multipart) — more reliable than browser form POST in headless Chrome
    const res = await api.post(localExam, {
      multipart: {
        reason: "كشف Playwright",
        visit_type: "checkup",
        subjective: "الحيوان متعب",
        objective: "حرارة طبيعية",
        assessment: "",
        plan: "",
        diagnosis: "",
        vital_signs: "",
        medications: "",
        follow_up_date: "",
        reminder_text: "",
      },
      timeout: 120_000,
    });
    expect(res.ok(), `exam POST ${res.status()}`).toBeTruthy();
    const html = await res.text();
    await page.setContent(html, { waitUntil: "domcontentloaded" });
    const bodyText = await page.locator("body").innerText();
    const hasOdooLink = /odoo\/pet\.medical\.visit|فتح الحالة|غير مكتمل|النواقص|نجاح|تم/i.test(
      bodyText,
    );
    const file = await shot(page, SHOTS, "07_exam_done_incomplete");

    await authenticateOdooApi(api);
    const visits = await odooCallKw<
      Array<{ id: number; portal_incomplete: boolean; portal_missing_fields: string; status: string }>
    >(
      api,
      "pet.medical.visit",
      "search_read",
      [[["pet_id.name", "ilike", petName]], ["id", "portal_incomplete", "portal_missing_fields", "status"]],
      { limit: 1, order: "id desc" },
    );
    visitId = visits[0]?.id || 0;
    const incomplete = Boolean(visits[0]?.portal_incomplete);
    record({
      id: "07",
      title: "Exam submit creates incomplete visit",
      ok: incomplete && visitId > 0,
      detail: visits[0]
        ? `visit=${visitId} status=${visits[0].status} missing=${(visits[0].portal_missing_fields || "").replace(/\n/g, " | ")}`
        : "no visit",
      screenshot: file,
    });
    expect(incomplete).toBeTruthy();
    expect(hasOdooLink || incomplete).toBeTruthy();
  });

  test("08 Odoo login + Incomplete Cases menu", async ({ page }) => {
    await loginOdoo(page);
    const fileLogin = await shot(page, SHOTS, "08a_odoo_home");

    // Open incomplete cases action
    await openOdooPath(
      page,
      `/web#action=petspot_clinic_portal.action_petspot_incomplete_cases&model=pet.medical.visit&view_type=list`,
    );
    // Fallback deep link by model domain
    if (!(await page.locator(".o_list_view, .o_kanban_view, .o_form_view").count())) {
      await openOdooPath(page, `/odoo/pet.medical.visit`);
    }
    await page.waitForTimeout(1500);
    const fileList = await shot(page, SHOTS, "08b_incomplete_cases");

    // Open the visit form
    if (visitId) {
      await openOdooPath(page, `/odoo/pet.medical.visit/${visitId}`);
      await page.waitForSelector(".o_form_view, .o_form_sheet", { timeout: 60_000 });
      const fileForm = await shot(page, SHOTS, "08c_incomplete_visit_form");
      record({
        id: "08",
        title: "Odoo Incomplete Cases + visit form",
        ok: true,
        detail: `visit=${visitId}`,
        screenshot: fileForm,
      });
    } else {
      record({
        id: "08",
        title: "Odoo Incomplete Cases menu",
        ok: true,
        detail: "list only",
        screenshot: fileList,
      });
    }
    expect(fileLogin).toBeTruthy();
  });

  test("09 Odoo portal tokens / slots / submit log", async ({ page }) => {
    await loginOdoo(page);

    await openOdooPath(page, `/web#model=petspot.portal.token&view_type=list`);
    await page.waitForTimeout(1000);
    const t1 = await shot(page, SHOTS, "09a_portal_tokens");

    await openOdooPath(page, `/web#model=petspot.clinic.slot&view_type=list`);
    await page.waitForTimeout(1000);
    const t2 = await shot(page, SHOTS, "09b_booking_slots");

    await openOdooPath(page, `/web#model=petspot.portal.submit.log&view_type=list`);
    await page.waitForTimeout(1000);
    const t3 = await shot(page, SHOTS, "09c_submit_log");

    record({
      id: "09",
      title: "Odoo tokens / slots / submit log",
      ok: true,
      detail: "screenshots captured",
      screenshot: t3,
    });
    expect(t1 && t2 && t3).toBeTruthy();
  });

  test("10 complete visit checklist in Odoo", async ({ page }) => {
    expect(visitId).toBeGreaterThan(0);
    await authenticateOdooApi(api);
    const partners = await odooCallKw<Array<{ id: number }>>(
      api,
      "res.partner",
      "search_read",
      [[["name", "!=", false]], ["id"]],
      { limit: 1 },
    );
    await odooCallKw(api, "pet.medical.visit", "write", [
      [visitId],
      {
        diagnosis: "Playwright diagnosis",
        assessment: "Playwright assessment",
        plan: "Playwright plan",
        vet_id: partners[0].id,
      },
    ]);
    const visits = await odooCallKw<
      Array<{ portal_incomplete: boolean; status: string; portal_completed_at: string }>
    >(
      api,
      "pet.medical.visit",
      "search_read",
      [[["id", "=", visitId]], ["portal_incomplete", "status", "portal_completed_at"]],
      { limit: 1 },
    );
    const done = visits[0] && !visits[0].portal_incomplete && visits[0].status === "completed";

    await loginOdoo(page);
    await openOdooPath(page, `/odoo/pet.medical.visit/${visitId}`);
    await page.waitForSelector(".o_form_view, .o_form_sheet", { timeout: 60_000 });
    const file = await shot(page, SHOTS, "10_visit_completed");

    record({
      id: "10",
      title: "Complete checklist auto-closes case",
      ok: Boolean(done),
      detail: visits[0]
        ? `incomplete=${visits[0].portal_incomplete} status=${visits[0].status}`
        : "missing",
      screenshot: file,
    });
    expect(done).toBeTruthy();
  });

  test("11 bot status after completion", async ({ page }) => {
    test.skip(!BRIDGE_SECRET, "BRIDGE_SHARED_SECRET not set");
    const lookup = await portalLookup(api, phone);
    const statusBot = await triggerClinicBot(api, `حالة ${phone}`);
    await page.setContent(`
      <html><body style="font-family:sans-serif;padding:24px;direction:rtl">
        <h1>Status after completion</h1>
        <h2>Lookup</h2>
        <pre>${JSON.stringify(lookup, null, 2)}</pre>
        <h2>Bot</h2>
        <pre>${JSON.stringify(statusBot, null, 2)}</pre>
      </body></html>
    `);
    const file = await shot(page, SHOTS, "11_status_after_complete");
    const ok = Boolean((statusBot as { ok?: boolean }).ok);
    record({
      id: "11",
      title: "Bot status after completion",
      ok,
      detail: JSON.stringify(lookup).slice(0, 160),
      screenshot: file,
    });
    expect(ok).toBeTruthy();
  });

  test("12 Chatwoot login + PetSpot inbox", async ({ page }) => {
    // Chatwoot returns 406 without Accept: text/html (not a real outage).
    const probe = await api.get(`${CHATWOOT_URL}/app/login`, {
      headers: { Accept: "text/html,application/xhtml+xml" },
    });
    expect(probe.ok(), `Chatwoot login HTTP ${probe.status()}`).toBeTruthy();

    await page.goto(`${CHATWOOT_URL}/app/login`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });
    await page.waitForTimeout(1500);
    const loginShot = await shot(page, SHOTS, "12_chatwoot_login");

    // Confirm PetSpot Sahel inbox via API
    const token =
      process.env.CHATWOOT_API_TOKEN ||
      process.env.PETSPOT_CHATWOOT_TOKEN ||
      "";
    let inboxDetail = "login page only";
    let inboxOk = true;
    if (token) {
      const inboxRes = await api.get(`${CHATWOOT_URL}/api/v1/accounts/2/inboxes`, {
        headers: { api_access_token: token },
      });
      inboxOk = inboxRes.ok();
      if (inboxOk) {
        const body = await inboxRes.json();
        const list = (body.payload || body) as Array<{ id: number; name: string }>;
        const petspot = list.find(
          (i) => i.id === 3 || /petspot/i.test(i.name || ""),
        );
        inboxDetail = petspot
          ? `inbox id=${petspot.id} name=${petspot.name}`
          : `inboxes=${list.map((i) => i.name).join(", ")}`;
        await page.setContent(`
          <html><body style="font-family:sans-serif;padding:24px">
            <h1>Chatwoot — PetSpot inbox check</h1>
            <p>Login page: OK (${CHATWOOT_URL}/app/login)</p>
            <p>API inboxes: OK</p>
            <pre>${JSON.stringify(list, null, 2)}</pre>
            <p><b>${inboxDetail}</b></p>
          </body></html>
        `);
      }
    }
    const file = await shot(page, SHOTS, "12_chatwoot_petspot_inbox");
    record({
      id: "12",
      title: "Chatwoot login + PetSpot inbox",
      ok: inboxOk,
      detail: inboxDetail,
      screenshot: file || loginShot,
    });
    expect(inboxOk).toBeTruthy();
  });

  test("13 write summary report page", async ({ page }) => {
    await writeReport();
    const md = fs.readFileSync(REPORT, "utf8");
    await page.setContent(`
      <html><body style="font-family:monospace;padding:24px;white-space:pre-wrap">${md
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")}</body></html>
    `);
    const file = await shot(page, SHOTS, "13_results_summary");
    const failed = results.filter((r) => !r.ok);
    record({
      id: "13",
      title: "Results summary",
      ok: failed.length === 0,
      detail: `${results.filter((r) => r.ok).length}/${results.length} passed`,
      screenshot: file,
    });
    await writeReport();
    expect(failed, `Failed scenarios: ${failed.map((f) => f.id).join(",")}`).toHaveLength(0);
  });
});
