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
  await page.waitForTimeout(300);
  await page.screenshot({ path: file, fullPage: true });
  return file;
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
    ...health.pageErrors,
    ...health.failedRequests,
    ...health.rpcErrors.filter((e) => !/Select or create a pet/i.test(e)),
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
  if (await page.locator(".o_main_navbar, .o_home_menu, .o_web_client").count()) {
    return;
  }
  const dbSelect = page.locator('select[name="db"], #db');
  if (await dbSelect.count()) {
    await dbSelect.first().selectOption(ODOO_DB).catch(() => undefined);
  }
  await page.locator('input[name="login"]').first().fill(ODOO_LOGIN);
  await page.locator('input[name="password"]').first().fill(ODOO_PASSWORD);
  await page.getByRole("button", { name: /log ?in/i }).click();
  await page.waitForSelector(
    ".o_action_manager, .o_home_menu, .o_main_navbar, .o_web_client",
    { timeout: 90_000 },
  );
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
  const runId = `${Date.now()}`;
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
