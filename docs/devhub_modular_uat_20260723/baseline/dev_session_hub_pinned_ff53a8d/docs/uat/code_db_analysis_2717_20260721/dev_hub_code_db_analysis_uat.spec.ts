/**
 * Dev Hub UAT — Analyze Against Code & Database (TOURZ task 2717 / WI 3053).
 *
 * Targets PetSpot Test Dev Hub only (:8028 / pet_spot_elsahel_test).
 * Never touches Production :8027 or TOURZ business DB mutations.
 *
 * Env:
 *   ODOO_URL=http://127.0.0.1:8028
 *   ODOO_DB=pet_spot_elsahel_test
 *   ODOO_LOGIN=admin
 *   ODOO_PASSWORD=<test admin>
 */
import { test, expect, request as playwrightRequest } from "@playwright/test";
import type { APIRequestContext, Page, ConsoleMessage } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const EVIDENCE = __dirname;
const SHOTS = path.join(EVIDENCE, "screenshots");

const ODOO_URL = (process.env.ODOO_URL || "http://127.0.0.1:8028").replace(/\/$/, "");
const ODOO_DB = process.env.ODOO_DB || "pet_spot_elsahel_test";
const ODOO_LOGIN = process.env.ODOO_LOGIN || "admin";
const ODOO_PASSWORD = process.env.ODOO_PASSWORD || "";

const WORK_ITEM_ID = Number(process.env.DEV_WORK_ITEM_ID || 3053);
const ANALYSIS_ID = Number(process.env.DEV_ANALYSIS_ID || 2481);
const ACTION_WI = Number(process.env.DEV_WI_ACTION_ID || 1297);

type Evidence = {
  started_at: string;
  finished_at?: string;
  url: string;
  database: string;
  work_item_id: number;
  analysis_id: number;
  fingerprint?: string;
  replay_analysis_id?: number;
  screenshots: string[];
  console_errors: string[];
  results: { name: string; ok: boolean; detail?: string }[];
};

const evidence: Evidence = {
  started_at: new Date().toISOString(),
  url: ODOO_URL,
  database: ODOO_DB,
  work_item_id: WORK_ITEM_ID,
  analysis_id: ANALYSIS_ID,
  screenshots: [],
  console_errors: [],
  results: [],
};

function assertHubTarget(): void {
  if (!ODOO_PASSWORD) {
    throw new Error("Set ODOO_PASSWORD for Dev Hub UAT");
  }
  if (!ODOO_URL.includes("8028")) {
    throw new Error(`Refusing non-Dev-Hub URL: ${ODOO_URL}`);
  }
  if (ODOO_DB !== "pet_spot_elsahel_test") {
    throw new Error(`Refusing non-test database: ${ODOO_DB}`);
  }
  if (ODOO_URL.includes("8027") || ODOO_DB === "pet_spot_elsahel") {
    throw new Error("Refusing production target");
  }
}

async function jsonRpc(
  api: APIRequestContext,
  endpoint: string,
  params: Record<string, unknown>,
): Promise<unknown> {
  const res = await api.post(`${ODOO_URL}${endpoint}`, {
    data: {
      jsonrpc: "2.0",
      method: "call",
      params,
      id: Date.now(),
    },
  });
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  if (body.error) {
    throw new Error(JSON.stringify(body.error));
  }
  return body.result;
}

async function callKw(
  api: APIRequestContext,
  model: string,
  method: string,
  args: unknown[] = [],
  kwargs: Record<string, unknown> = {},
): Promise<unknown> {
  return jsonRpc(api, `/web/dataset/call_kw/${model}/${method}`, {
    model,
    method,
    args,
    kwargs,
  });
}

async function loginUi(page: Page): Promise<void> {
  const apiLogin = await playwrightRequest.newContext();
  const authRes = await apiLogin.post(`${ODOO_URL}/web/session/authenticate`, {
    data: {
      jsonrpc: "2.0",
      method: "call",
      id: Date.now(),
      params: { db: ODOO_DB, login: ODOO_LOGIN, password: ODOO_PASSWORD },
    },
  });
  expect(authRes.ok()).toBeTruthy();
  const authBody = await authRes.json();
  expect(authBody.result?.uid).toBeTruthy();
  const cookies = await apiLogin.storageState();
  await page.context().addCookies(
    cookies.cookies.map((c) => ({
      ...c,
      domain: c.domain || "127.0.0.1",
      path: c.path || "/",
    })),
  );
  await apiLogin.dispose();
  await page.goto(`${ODOO_URL}/odoo`);
  await page.waitForLoadState("domcontentloaded");
  await page.locator(".o_main_navbar, .o_web_client, .o_home_menu").first().waitFor({
    timeout: 60_000,
  });
}

async function shot(page: Page, name: string): Promise<string> {
  fs.mkdirSync(SHOTS, { recursive: true });
  const file = path.join(SHOTS, `${name}.png`);
  await page
    .locator(".o_loading, .o_blockUI")
    .waitFor({ state: "hidden", timeout: 5_000 })
    .catch(() => undefined);
  await page.screenshot({ path: file, fullPage: true });
  evidence.screenshots.push(file);
  return file;
}

function trackConsole(page: Page): void {
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() === "error") {
      const text = msg.text();
      // Ignore known noisy Odoo assets
      if (/favicon|sourcemap|ResizeObserver/i.test(text)) {
        return;
      }
      evidence.console_errors.push(text);
    }
  });
  page.on("pageerror", (err) => {
    evidence.console_errors.push(String(err));
  });
}

function mark(name: string, ok: boolean, detail?: string): void {
  evidence.results.push({ name, ok, detail });
  expect(ok, detail || name).toBeTruthy();
}

async function openNotebookTab(page: Page, label: string): Promise<void> {
  const tab = page.locator(".o_notebook .nav-link, .o_notebook_headers a").filter({
    hasText: new RegExp(`^\\s*${label}\\s*$`, "i"),
  });
  await tab.first().click();
  await page.waitForTimeout(800);
}

test.describe.configure({ mode: "serial" });

test("Dev Hub code+DB analysis UAT for TOURZ 2717", async ({ page }) => {
  assertHubTarget();
  trackConsole(page);
  fs.mkdirSync(SHOTS, { recursive: true });

  const api = await playwrightRequest.newContext();
  await jsonRpc(api, "/web/session/authenticate", {
    db: ODOO_DB,
    login: ODOO_LOGIN,
    password: ODOO_PASSWORD,
  });

  // Baseline: completed analysis exists
  const rows = (await callKw(
    api,
    "dev.work.analysis",
    "search_read",
    [
      [["id", "=", ANALYSIS_ID]],
      [
        "id",
        "execution_state",
        "analysis_kind",
        "database_identifier",
        "analysis_fingerprint",
        "problem_summary",
        "technical_findings",
        "reproduction_context",
        "work_item_id",
        "environment_id",
        "repository_id",
        "runtime_label",
      ],
    ],
    { limit: 1 },
  )) as Array<Record<string, unknown>>;
  expect(rows.length).toBe(1);
  const analysis = rows[0];
  evidence.fingerprint = String(analysis.analysis_fingerprint || "");
  mark(
    "analysis_completed_in_db",
    analysis.execution_state === "completed" &&
      analysis.database_identifier === "tours_trading_test",
    JSON.stringify({
      state: analysis.execution_state,
      db: analysis.database_identifier,
    }),
  );

  await loginUi(page);

  // 1) Work item page
  await page.goto(`${ODOO_URL}/odoo/action-${ACTION_WI}/${WORK_ITEM_ID}`);
  await page.locator(".o_form_view").first().waitFor({ timeout: 90_000 });
  await expect(page.locator(".o_form_view")).toContainText(/TOURZ|Torz|warranty/i);
  await shot(page, "01_work_item_3053");
  mark("work_item_opened", true);

  // 2) Analysis tab
  await openNotebookTab(page, "Analysis");
  await page.waitForTimeout(1000);
  const list = page.locator(".o_list_view, .o_list_renderer, .o_notebook .o_list_table").first();
  await list.waitFor({ timeout: 30_000 });
  const bodyText = await page.locator(".o_form_view").innerText();
  mark(
    "analysis_tab_shows_completed",
    /completed/i.test(bodyText) && /code_database|Code/i.test(bodyText),
    bodyText.slice(0, 400),
  );
  mark(
    "analysis_tab_shows_tourz_db",
    /tours_trading_test/i.test(bodyText) || /Tours Trading Test/i.test(bodyText),
  );
  await shot(page, "02_analysis_tab_completed");

  // 3) Open full analysis via Open button on completed row
  const completedRow = page.locator(".o_data_row").filter({ hasText: /completed/i }).first();
  await completedRow.waitFor({ timeout: 30_000 });
  const openBtn = completedRow.locator("button").filter({ hasText: /Open/i }).first();
  if (await openBtn.count()) {
    await openBtn.click();
  } else {
    await page.goto(`${ODOO_URL}/odoo/dev.work.analysis/${ANALYSIS_ID}`);
  }
  await page.locator(".o_form_view").first().waitFor({ timeout: 90_000 });
  // Char fields are reliable; many2one display text is often only in a11y tree.
  await expect(
    page.locator(
      '.o_field_widget[name="database_identifier"] input, input[id*="database_identifier"]',
    ),
  ).toHaveValue("tours_trading_test", { timeout: 60_000 });
  await expect(
    page.locator('.o_field_widget[name="runtime_label"] input, input[id*="runtime_label"]'),
  ).toHaveValue(/ODOO19/i);
  const fingerprintText = await page
    .locator('.o_field_widget[name="analysis_fingerprint"]')
    .innerText();
  expect(fingerprintText).toMatch(/4441b87f/i);
  await shot(page, "03_full_analysis_report");

  async function collectFormValues(p: Page): Promise<string> {
    const chunks: string[] = [await p.locator(".o_form_view").innerText()];
    const fields = p.locator(
      ".o_form_view textarea, .o_form_view input, .o_form_view .o_input",
    );
    const n = await fields.count();
    for (let i = 0; i < n; i++) {
      const val = await fields.nth(i).inputValue().catch(() => "");
      if (val) {
        chunks.push(val);
      }
    }
    return chunks.join("\n");
  }

  let reportText = await collectFormValues(page);
  await openNotebookTab(page, "Findings");
  reportText += "\n" + (await collectFormValues(page));
  await openNotebookTab(page, "Request");
  reportText += "\n" + (await collectFormValues(page));

  // Reproduction context always embeds project/repo/env/db.
  mark("shows_tourz_or_task", /TOURZ|2717|Torz|warranty/i.test(reportText), reportText.slice(0, 400));
  mark("shows_repo", /tours-trading|Tours Trading Odoo/i.test(reportText), reportText.slice(0, 400));
  mark("shows_env", /Tours Trading Test/i.test(reportText), reportText.slice(0, 400));
  mark("shows_db", /tours_trading_test/i.test(reportText), reportText.slice(0, 400));
  mark(
    "shows_code_findings",
    /Code findings|torz_warranty|fleet_vehicle|Likely gaps/i.test(reportText),
    reportText.slice(0, 400),
  );
  mark(
    "shows_db_evidence",
    /Database|module|installed|runtime|ODOO19|Manifests/i.test(reportText),
    reportText.slice(0, 400),
  );
  mark(
    "shows_recommendation",
    /Recommend|implementation|Test plan|Risk|Open Questions|Likely gaps/i.test(reportText),
    reportText.slice(0, 400),
  );
  await shot(page, "04_repo_env_db_evidence");

  // 4) Refresh persistence
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.locator(".o_form_view").first().waitFor({ timeout: 90_000 });
  await expect(
    page.locator(
      '.o_field_widget[name="database_identifier"] input, input[id*="database_identifier"]',
    ),
  ).toHaveValue("tours_trading_test", { timeout: 60_000 });
  const afterRefresh = await collectFormValues(page);
  mark(
    "persists_after_refresh",
    /tours_trading_test/i.test(afterRefresh) &&
      (/completed|generated/i.test(afterRefresh) || /4441b87f/i.test(afterRefresh)),
    afterRefresh.slice(0, 400),
  );
  await shot(page, "05_after_refresh");

  // 5) Idempotent re-run via RPC (same fingerprint → same analysis id)
  const replay = (await callKw(
    api,
    "dev.work.item",
    "action_analyze_against_code_database",
    [[WORK_ITEM_ID]],
  )) as { res_id?: number; res_model?: string };
  evidence.replay_analysis_id = Number(replay.res_id || 0);
  mark(
    "idempotent_replay",
    evidence.replay_analysis_id === ANALYSIS_ID,
    `replay=${evidence.replay_analysis_id} expected=${ANALYSIS_ID}`,
  );

  // Re-open WI Analysis tab after replay
  await page.goto(`${ODOO_URL}/odoo/action-${ACTION_WI}/${WORK_ITEM_ID}`);
  await page.locator(".o_form_view").first().waitFor({ timeout: 90_000 });
  await openNotebookTab(page, "Analysis");
  await page.waitForTimeout(800);
  await shot(page, "06_idempotent_replay_analysis_tab");

  const owlErrors = evidence.console_errors.filter((e) =>
    /OwlError|RPC_ERROR|AccessError|Uncaught/i.test(e),
  );
  mark("no_owl_rpc_access_errors", owlErrors.length === 0, owlErrors.join(" | "));

  evidence.finished_at = new Date().toISOString();
  fs.writeFileSync(
    path.join(EVIDENCE, "evidence.json"),
    JSON.stringify(evidence, null, 2),
  );
  fs.writeFileSync(
    path.join(EVIDENCE, "UAT_REPORT.md"),
    [
      "# Dev Hub Code+DB Analysis UAT — TOURZ 2717",
      "",
      `- Started: ${evidence.started_at}`,
      `- Finished: ${evidence.finished_at}`,
      `- URL: ${evidence.url}`,
      `- Database: ${evidence.database}`,
      `- Work item: ${evidence.work_item_id}`,
      `- Analysis: ${evidence.analysis_id}`,
      `- Fingerprint: ${evidence.fingerprint}`,
      `- Replay analysis id: ${evidence.replay_analysis_id}`,
      "",
      "## Results",
      ...evidence.results.map((r) => `- ${r.ok ? "PASS" : "FAIL"} ${r.name}${r.detail ? ` — ${r.detail.slice(0, 120)}` : ""}`),
      "",
      "## Screenshots",
      ...evidence.screenshots.map((s) => `- ${s}`),
      "",
      "## Console errors",
      evidence.console_errors.length
        ? evidence.console_errors.map((e) => `- ${e}`).join("\n")
        : "- none",
      "",
    ].join("\n"),
  );

  await api.dispose();
});
