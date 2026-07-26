/**
 * Appointment Intake Playwright helpers — test environment only.
 * Prefer ODOO_TEST_* vars; refuse production URL/DB.
 */
import { expect, type APIRequestContext, type Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

export const ODOO_URL = (
  process.env.ODOO_TEST_URL ||
  process.env.ODOO_URL ||
  "https://test.drpaws.ai"
).replace(/\/$/, "");

export const ODOO_DB =
  process.env.ODOO_TEST_DB || process.env.ODOO_DB || "pet_spot_elsahel_test";

export const ODOO_LOGIN =
  process.env.ODOO_TEST_LOGIN || process.env.ODOO_LOGIN || "";

export const ODOO_PASSWORD =
  process.env.ODOO_TEST_PASSWORD || process.env.ODOO_PASSWORD || "";

const PROD_URLS = ["https://drpaws.ai", "http://127.0.0.1:8027", "http://localhost:8027"];
const PROD_DBS = ["pet_spot_elsahel"];

export function assertTestEnvironment(): void {
  if (!ODOO_LOGIN || !ODOO_PASSWORD) {
    throw new Error(
      "Missing credentials. Set ODOO_TEST_LOGIN and ODOO_TEST_PASSWORD (or ODOO_LOGIN / ODOO_PASSWORD).",
    );
  }
  const urlNorm = ODOO_URL.replace(/\/$/, "");
  if (PROD_URLS.some((u) => urlNorm === u || urlNorm.startsWith(u + "/"))) {
    throw new Error(`Refusing production URL: ${ODOO_URL}`);
  }
  if (PROD_DBS.includes(ODOO_DB)) {
    throw new Error(`Refusing production database: ${ODOO_DB}`);
  }
}

export const ARTIFACT_ROOT =
  process.env.PW_INTAKE_ARTIFACTS || "/tmp/petspot-playwright-intake";

export function ensureArtifactDirs(): {
  root: string;
  shots: string;
  logs: string;
} {
  const root = ARTIFACT_ROOT;
  const shots = path.join(root, "screenshots");
  const logs = path.join(root, "logs");
  fs.mkdirSync(shots, { recursive: true });
  fs.mkdirSync(logs, { recursive: true });
  fs.mkdirSync(path.join(root, "report"), { recursive: true });
  fs.mkdirSync(path.join(root, "traces"), { recursive: true });
  return { root, shots, logs };
}

export async function shot(page: Page, shotsDir: string, name: string): Promise<string> {
  const file = path.join(shotsDir, `${name}.png`);
  // Wait for network idle-ish UI: no blocking overlay before capture.
  await page.locator(".o_loading, .o_blockUI").waitFor({ state: "hidden", timeout: 5_000 }).catch(() => undefined);
  await page.screenshot({ path: file, fullPage: true });
  return file;
}

/** True when a Playwright response is an Odoo JSON-RPC call_kw for model/method. */
export function isCallKw(
  res: { url: () => string; request: () => { method: () => string; postData: () => string | null } },
  model: string,
  methods: string[],
): boolean {
  if (res.request().method() !== "POST") return false;
  const url = res.url();
  if (!url.includes("/web/dataset/call_kw") && !url.includes("/web/dataset/call_button")) {
    return false;
  }
  // Odoo 19 often encodes model/method in the URL path.
  for (const method of methods) {
    if (url.includes(`/call_kw/${model}/${method}`) || url.includes(`/call_button/${model}/${method}`)) {
      return true;
    }
  }
  const body = res.request().postData() || "";
  if (!body.includes(model)) return false;
  return methods.some(
    (m) =>
      body.includes(`"method":"${m}"`) ||
      body.includes(`"method": "${m}"`) ||
      body.includes(`'method':'${m}'`),
  );
}

/**
 * Select a many2one by visible name and wait for autocomplete + optional onchange.
 * Reacquires the field locator after OWL may rerender the widget.
 */
export async function setMany2oneByName(
  page: Page,
  fieldName: string,
  name: string,
  opts: { waitOnchange?: boolean } = {},
): Promise<void> {
  const field = () => page.locator(`.o_field_widget[name="${fieldName}"]`).first();
  await field().click();
  const input = field().locator("input").first();
  await input.fill(name);
  const option = page
    .locator("li.o-autocomplete--dropdown-item, li.ui-menu-item")
    .filter({ hasText: name })
    .first();
  await expect(option).toBeVisible({ timeout: 20_000 });

  const waitOnchange = opts.waitOnchange ?? fieldName === "intake_owner_id";
  const onchangePromise = waitOnchange
    ? page.waitForResponse(
        (res) =>
          res.ok() &&
          (isCallKw(res, "pet.appointment", ["onchange", "web_onchange", "onchange_intake_owner_id"]) ||
            isCallKw(res, "pet.appointment", ["onchange"]) ||
            (res.url().includes("/web/dataset/call_kw") &&
              (res.request().postData() || "").includes("onchange"))),
        { timeout: 30_000 },
      ).catch(() => null)
    : Promise.resolve(null);

  await option.click();
  await onchangePromise;

  // Field value must reflect selection after any OWL replace.
  await expect
    .poll(async () => {
      const el = field().locator("input").first();
      if (await el.count()) {
        return (await el.inputValue().catch(() => "")).trim();
      }
      return (await field().innerText()).trim();
    }, { timeout: 20_000 })
    .toMatch(new RegExp(name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
}

/**
 * Click Save and wait until the appointment create/web_save RPC succeeds and the
 * form shows a persisted record id (URL or breadcrumb). Returns that id.
 */
export async function saveAppointmentForm(page: Page): Promise<number> {
  const save = page.locator("button.o_form_button_save, .o_form_button_save").first();
  await expect(save).toBeVisible({ timeout: 15_000 });

  const saveRpc = page.waitForResponse(
    (res) =>
      res.ok() &&
      isCallKw(res, "pet.appointment", ["web_save", "create", "write"]),
    { timeout: 45_000 },
  );

  await save.click();
  const resp = await saveRpc;
  const body = await resp.json().catch(() => null);
  if (body?.error) {
    const msg =
      body.error?.data?.message || body.error?.message || JSON.stringify(body.error);
    throw new Error(`Appointment save RPC failed: ${msg}`);
  }

  // Prefer id from web_save result when present.
  let savedId: number | undefined;
  const result = body?.result;
  if (Array.isArray(result) && typeof result[0] === "number") {
    savedId = result[0];
  } else if (Array.isArray(result) && result[0] && typeof result[0].id === "number") {
    savedId = result[0].id;
  } else if (result && typeof result === "object" && typeof result.id === "number") {
    savedId = result.id;
  }

  // Form must leave dirty/new state: save control hidden or URL carries record id.
  await expect
    .poll(
      async () => {
        const href = page.url();
        const urlMatch = href.match(/pet\.appointment\/(\d+)/) || href.match(/\/action-\d+\/(\d+)/);
        if (urlMatch) return Number(urlMatch[1]);
        if (savedId) return savedId;
        const dirty = await page.locator(".o_form_dirty").count();
        const saveVisible = await page.locator("button.o_form_button_save:visible").count();
        if (!dirty && !saveVisible && savedId) return savedId;
        return 0;
      },
      { timeout: 45_000 },
    )
    .toBeGreaterThan(0);

  const href = page.url();
  const urlMatch = href.match(/pet\.appointment\/(\d+)/) || href.match(/\/action-\d+\/(\d+)/);
  const id = (urlMatch ? Number(urlMatch[1]) : savedId) as number;
  if (!id) {
    throw new Error(`Could not resolve saved appointment id from URL=${href}`);
  }
  await expect(page.locator(".o_form_view")).toBeVisible();
  await page.locator(".o_loading, .o_blockUI").waitFor({ state: "hidden", timeout: 10_000 }).catch(() => undefined);
  return id;
}

/**
 * Shift recent draft/confirmed appointments out of the immediate schedule so a
 * UI save with default start/end cannot hit `_check_overlap`.
 *
 * Why this is required:
 * - `pet.appointment.create()` re-injects the current user's employee as vet
 *   when vet is empty, so clearing the UI vet does not help.
 * - Odoo 19 datetime fields are button widgets; relying on picker typing is brittle.
 * - Search windows must use the same naive datetimes Odoo stores (not UTC-only).
 */
export async function clearNearbyVetOverlaps(
  api: APIRequestContext,
): Promise<void> {
  const rows = await callKw<Array<{ id: number }>>(
    api,
    "pet.appointment",
    "search_read",
    [
      [["state", "in", ["draft", "confirmed", "in_progress"]]],
      ["id"],
    ],
    { limit: 40, order: "id desc" },
  );
  const stamp = Date.now();
  for (let i = 0; i < rows.length; i++) {
    const slot = uniqueRpcSlot(`overlap-clear-${stamp}`, 300 + i);
    try {
      await callKw(api, "pet.appointment", "write", [
        [rows[i].id],
        {
          start_datetime: slot.start,
          end_datetime: slot.end,
          // Keep vet; only move the window.
        },
      ]);
    } catch {
      /* leave record if write blocked */
    }
  }
}

/**
 * Set an Odoo 19 datetime field (often a button that opens a picker).
 */
export async function setDatetimeField(
  page: Page,
  fieldName: string,
  displayValue: string,
): Promise<void> {
  const widget = page.locator(`.o_field_widget[name="${fieldName}"]`).first();
  await expect(widget).toBeVisible({ timeout: 15_000 });

  const directInput = widget.locator("input").first();
  if (await directInput.count()) {
    await directInput.click();
    await directInput.fill(displayValue);
    await directInput.press("Tab");
    return;
  }

  const btn = widget.getByRole("button").first();
  await btn.click();
  const popInput = page
    .locator(
      ".o_datetime_picker input, .o-datepicker input, .o_popover input, .o_datetime_input input, input.o_datetime_input",
    )
    .first();
  await expect(popInput).toBeVisible({ timeout: 10_000 });
  await popInput.fill(displayValue);
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape").catch(() => undefined);
  await page
    .locator(".o_datetime_picker, .o_popover")
    .waitFor({ state: "hidden", timeout: 5_000 })
    .catch(() => undefined);
}

/**
 * Best-effort UI datetime adjustment; prefer clearNearbyVetOverlaps before save.
 */
export async function setUniqueAppointmentSlot(
  page: Page,
  slotIndex: number,
): Promise<void> {
  const start = new Date(
    Date.now() + (24 + slotIndex * 2) * 3600_000 + slotIndex * 180_000,
  );
  const end = new Date(start.getTime() + 30 * 60_000);
  const fmt = (d: Date) => {
    const p = (n: number) => String(n).padStart(2, "0");
    let h = d.getHours();
    const ampm = h >= 12 ? "PM" : "AM";
    h = h % 12 || 12;
    return `${p(d.getMonth() + 1)}/${p(d.getDate())}/${d.getFullYear()} ${p(h)}:${p(d.getMinutes())}:${p(d.getSeconds())} ${ampm}`;
  };
  try {
    await setDatetimeField(page, "start_datetime", fmt(start));
    await setDatetimeField(page, "end_datetime", fmt(end));
  } catch {
    // Datetime button/picker variants differ; overlap clearing is the guarantee.
  }
}

/** Unique UTC-naive datetimes for RPC-created appointments. */
export function uniqueRpcSlot(
  runId: string,
  slotIndex: number,
): { start: string; end: string } {
  const seed =
    Number(String(runId).replace(/\D/g, "").slice(-6)) || Date.now() % 1_000_000;
  const start = new Date(
    Date.UTC(2026, 7, 1, 8, 0, 0) + seed * 60_000 + slotIndex * 3_600_000,
  );
  const end = new Date(start.getTime() + 30 * 60_000);
  const fmt = (d: Date) => {
    const p = (n: number) => String(n).padStart(2, "0");
    return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`;
  };
  return { start: fmt(start), end: fmt(end) };
}

export type BrowserHealth = {
  consoleErrors: string[];
  pageErrors: string[];
  failedRequests: string[];
  rpcErrors: string[];
};

export function attachBrowserHealth(page: Page): BrowserHealth {
  const health: BrowserHealth = {
    consoleErrors: [],
    pageErrors: [],
    failedRequests: [],
    rpcErrors: [],
  };
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      health.consoleErrors.push(msg.text());
    }
  });
  page.on("pageerror", (err) => {
    health.pageErrors.push(String(err));
  });
  page.on("response", async (res) => {
    const url = res.url();
    const status = res.status();
    if (status >= 500) {
      health.failedRequests.push(`${status} ${url}`);
    }
    if (url.includes("/web/dataset/") && status >= 400) {
      health.failedRequests.push(`${status} ${url}`);
    }
    if (url.includes("/web/dataset/") && status === 200) {
      try {
        const ct = res.headers()["content-type"] || "";
        if (ct.includes("json")) {
          const body = await res.json().catch(() => null);
          if (body?.error) {
            const msg =
              body.error?.data?.message ||
              body.error?.message ||
              JSON.stringify(body.error);
            health.rpcErrors.push(String(msg));
          }
        }
      } catch {
        /* ignore body parse */
      }
    }
  });
  return health;
}

const HARMLESS = [
  /Download the React DevTools/i,
  /favicon\.ico/i,
  /third-party cookie/i,
  /Deprecated/i,
  // Intentional server validations exercised by the suite (also filtered in assert).
  /Select or create a pet before confirming or billing/i,
];

export function assertBrowserHealthy(health: BrowserHealth): void {
  const unexpectedConsole = health.consoleErrors.filter(
    (e) => !HARMLESS.some((re) => re.test(e)),
  );
  const bad = [
    ...unexpectedConsole.filter(
      (e) =>
        /OwlError|RPC_ERROR|Uncaught|TypeError|ReferenceError/i.test(e) ||
        /\/web\/dataset\//i.test(e),
    ),
    ...health.pageErrors.filter((e) => !HARMLESS.some((re) => re.test(e))),
    ...health.failedRequests,
    ...health.rpcErrors.filter((e) => !HARMLESS.some((re) => re.test(e))),
  ];
  expect(bad, `Browser health failures:\n${bad.join("\n")}`).toEqual([]);
}

export async function jsonRpc<T>(
  api: APIRequestContext,
  urlPath: string,
  params: Record<string, unknown>,
): Promise<T> {
  const res = await api.post(`${ODOO_URL}${urlPath}`, {
    headers: { "Content-Type": "application/json" },
    data: {
      jsonrpc: "2.0",
      method: "call",
      params,
      id: Date.now(),
    },
  });
  expect(res.ok(), `HTTP ${res.status()} for ${urlPath}`).toBeTruthy();
  const body = (await res.json()) as {
    result?: T;
    error?: { data?: { message?: string }; message?: string };
  };
  if (body.error) {
    const msg =
      body.error.data?.message || body.error.message || JSON.stringify(body.error);
    throw new Error(msg);
  }
  return body.result as T;
}

export async function callKw<T>(
  api: APIRequestContext,
  model: string,
  method: string,
  args: unknown[] = [],
  kwargs: Record<string, unknown> = {},
): Promise<T> {
  return jsonRpc<T>(api, "/web/dataset/call_kw", {
    model,
    method,
    args,
    kwargs,
  });
}

export async function authenticateApi(api: APIRequestContext): Promise<number> {
  assertTestEnvironment();
  const result = await jsonRpc<{ uid: number }>(api, "/web/session/authenticate", {
    db: ODOO_DB,
    login: ODOO_LOGIN,
    password: ODOO_PASSWORD,
  });
  if (!result?.uid) {
    throw new Error("Authentication failed (no uid)");
  }
  return result.uid;
}

export async function loginUi(page: Page): Promise<void> {
  assertTestEnvironment();
  await page.goto(`${ODOO_URL}/web/login?db=${encodeURIComponent(ODOO_DB)}`, {
    waitUntil: "domcontentloaded",
    timeout: 60_000,
  });
  // Do not treat body.o_web_client as logged-in: the login/boot shell uses it
  // while still hidden, which makes a visible wait hang forever.
  if (await page.locator(".o_main_navbar, .o_home_menu, .o_action_manager").count()) {
    return;
  }
  const dbSelect = page.locator('select[name="db"], #db');
  if (await dbSelect.count()) {
    await dbSelect.first().selectOption(ODOO_DB).catch(() => undefined);
  }
  await page.locator('input[name="login"]').first().fill(ODOO_LOGIN);
  await page.locator('input[name="password"]').first().fill(ODOO_PASSWORD);
  await page.getByRole("button", { name: /log ?in/i }).click();
  await page.waitForSelector(".o_action_manager, .o_home_menu, .o_main_navbar", {
    timeout: 120_000,
  });
}

export async function actionId(api: APIRequestContext, xmlId: string): Promise<number> {
  const [mod, name] = xmlId.split(".");
  const rows = await callKw<Array<{ res_id: number }>>(
    api,
    "ir.model.data",
    "search_read",
    [[["module", "=", mod], ["name", "=", name]], ["res_id"]],
    { limit: 1 },
  );
  if (!rows?.length) {
    throw new Error(`xml id not found: ${xmlId}`);
  }
  return rows[0].res_id;
}

export type IntakeFixtures = {
  runId: string;
  prefix: string;
  speciesId: number;
  ownerNoneId: number;
  ownerOneId: number;
  ownerMultiId: number;
  petOneId: number;
  petMultiAId: number;
  petMultiBId: number;
  created: {
    partners: number[];
    pets: number[];
    appointments: number[];
    visits: number[];
  };
};

export async function createIntakeFixtures(
  api: APIRequestContext,
): Promise<IntakeFixtures> {
  // Allow stress runs to force unique prefixes: PW_INTAKE_RUN_TAG=MULTI-…-N
  const runId = process.env.PW_INTAKE_RUN_TAG || `${Date.now()}`;
  const prefix = `PW-INTAKE-${runId}`;
  const created: IntakeFixtures["created"] = {
    partners: [],
    pets: [],
    appointments: [],
    visits: [],
  };

  let speciesRows = await callKw<Array<{ id: number }>>(
    api,
    "pet.species",
    "search_read",
    [[], ["id"]],
    { limit: 1 },
  );
  let speciesId = speciesRows[0]?.id;
  if (!speciesId) {
    speciesId = await callKw<number>(api, "pet.species", "create", [{ name: `${prefix} Species` }]);
  }

  const ownerNoneId = await callKw<number>(api, "res.partner", "create", [
    { name: `${prefix} Owner None`, phone: "01990000001", email: `${prefix}-none@example.test` },
  ]);
  created.partners.push(ownerNoneId);

  const ownerOneId = await callKw<number>(api, "res.partner", "create", [
    { name: `${prefix} Owner One`, phone: "01990000002", email: `${prefix}-one@example.test` },
  ]);
  created.partners.push(ownerOneId);

  const ownerMultiId = await callKw<number>(api, "res.partner", "create", [
    { name: `${prefix} Owner Multi`, phone: "01990000003", email: `${prefix}-multi@example.test` },
  ]);
  created.partners.push(ownerMultiId);

  const petOneId = await callKw<number>(api, "pet.pet", "create", [
    {
      name: `${prefix} Solo`,
      owner_id: ownerOneId,
      species_id: speciesId,
      allergies: "No",
    },
  ]);
  created.pets.push(petOneId);

  const petMultiAId = await callKw<number>(api, "pet.pet", "create", [
    { name: `${prefix} MultiA`, owner_id: ownerMultiId, species_id: speciesId },
  ]);
  created.pets.push(petMultiAId);

  const petMultiBId = await callKw<number>(api, "pet.pet", "create", [
    { name: `${prefix} MultiB`, owner_id: ownerMultiId, species_id: speciesId },
  ]);
  created.pets.push(petMultiBId);

  return {
    runId,
    prefix,
    speciesId,
    ownerNoneId,
    ownerOneId,
    ownerMultiId,
    petOneId,
    petMultiAId,
    petMultiBId,
    created,
  };
}

export async function cleanupIntakeFixtures(
  api: APIRequestContext,
  fx: IntakeFixtures,
): Promise<string[]> {
  const retained: string[] = [];
  // Cancel/delete appointments first (draft preferred)
  for (const id of [...fx.created.appointments].reverse()) {
    try {
      const rows = await callKw<Array<{ state: string }>>(
        api,
        "pet.appointment",
        "search_read",
        [[["id", "=", id]], ["state"]],
        { limit: 1 },
      );
      const state = rows[0]?.state;
      if (state === "draft") {
        await callKw(api, "pet.appointment", "unlink", [[id]]);
      } else {
        try {
          await callKw(api, "pet.appointment", "write", [[id], { state: "cancelled" }]);
        } catch {
          /* keep */
        }
        retained.push(`pet.appointment(${id}) state=${state}`);
      }
    } catch (e) {
      retained.push(`pet.appointment(${id}) cleanup failed: ${e}`);
    }
  }
  for (const id of [...fx.created.visits].reverse()) {
    try {
      await callKw(api, "pet.medical.visit", "unlink", [[id]]);
    } catch {
      retained.push(`pet.medical.visit(${id})`);
    }
  }
  for (const id of [...fx.created.pets].reverse()) {
    try {
      await callKw(api, "pet.pet", "unlink", [[id]]);
    } catch {
      retained.push(`pet.pet(${id})`);
    }
  }
  for (const id of [...fx.created.partners].reverse()) {
    try {
      await callKw(api, "res.partner", "unlink", [[id]]);
    } catch {
      retained.push(`res.partner(${id})`);
    }
  }
  return retained;
}

export function writeJson(filePath: string, data: unknown): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2), "utf8");
}
