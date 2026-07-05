import { expect, type APIRequestContext, type Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

export const ODOO_URL = (process.env.ODOO_URL || "http://127.0.0.1:8027").replace(
  /\/$/,
  "",
);
export const ODOO_DB = process.env.ODOO_DB || "pet_spot_elsahel";
export const ODOO_LOGIN = process.env.ODOO_LOGIN || "admin";
export const ODOO_PASSWORD = process.env.ODOO_PASSWORD || "admin";

export const BRIDGE_URL = (process.env.BRIDGE_URL || "http://127.0.0.1:3010").replace(
  /\/$/,
  "",
);
export const BRIDGE_SECRET =
  process.env.BRIDGE_SHARED_SECRET || process.env.BRIDGE_SECRET || "";
export const BRIDGE_TOKEN =
  process.env.PETSPOT_BRIDGE_TOKEN ||
  process.env.INTEGRATION_BRIDGE_MASTER_TOKEN ||
  "ib_cw_fzm_7xK9mN2pQ4rT6vY8zA1bD3eF5g";

export const CHATWOOT_URL = (
  process.env.CHATWOOT_URL || "http://127.0.0.1:3000"
).replace(/\/$/, "");

export const PETSPOT_GROUP_JID =
  process.env.PETSPOT_GROUP_JID || "120363409395291215@g.us";

export function shotsDir(baseDir: string): string {
  const dir = path.join(baseDir, "screenshots", "petspot_clinic");
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

export async function shot(
  page: Page,
  dir: string,
  name: string,
): Promise<string> {
  const file = path.join(dir, `${name}.png`);
  await page.waitForTimeout(400);
  await page.screenshot({ path: file, fullPage: true });
  return file;
}

export async function mintPortalToken(
  request: APIRequestContext,
  payload: Record<string, unknown>,
): Promise<{ ok: boolean; url?: string; token?: string; token_id?: number; error?: string }> {
  const res = await request.post(`${ODOO_URL}/petspot/portal/token`, {
    headers: {
      "Content-Type": "application/json",
      "X-Bridge-Token": BRIDGE_TOKEN,
    },
    data: payload,
  });
  const body = await res.json();
  return body;
}

export async function portalLookup(
  request: APIRequestContext,
  phone: string,
): Promise<Record<string, unknown>> {
  const res = await request.post(`${ODOO_URL}/petspot/portal/lookup`, {
    headers: {
      "Content-Type": "application/json",
      "X-Bridge-Token": BRIDGE_TOKEN,
    },
    data: { phone },
  });
  return res.json();
}

export async function triggerClinicBot(
  request: APIRequestContext,
  text: string,
  opts: { fromMe?: boolean; messageId?: string } = {},
): Promise<Record<string, unknown>> {
  if (!BRIDGE_SECRET) {
    throw new Error("BRIDGE_SHARED_SECRET is required for bot webhook tests");
  }
  const messageId = opts.messageId || `PW_${Date.now()}_${Math.random().toString(16).slice(2)}`;
  const res = await request.post(
    `${BRIDGE_URL}/webhook/evolution?secret=${encodeURIComponent(BRIDGE_SECRET)}`,
    {
      headers: { "Content-Type": "application/json" },
      data: {
        event: "messages.upsert",
        instance: process.env.EVOLUTION_INSTANCE_NAME || "sabry min",
        data: {
          key: {
            id: messageId,
            fromMe: opts.fromMe !== false,
            remoteJid: PETSPOT_GROUP_JID,
          },
          pushName: "playwright",
          message: { conversation: text },
          messageTimestamp: Math.floor(Date.now() / 1000),
        },
      },
    },
  );
  expect(res.ok(), `bridge webhook HTTP ${res.status()}`).toBeTruthy();
  return res.json();
}

export async function loginOdoo(page: Page): Promise<void> {
  await page.goto(`${ODOO_URL}/web/login?db=${encodeURIComponent(ODOO_DB)}`, {
    waitUntil: "domcontentloaded",
    timeout: 60_000,
  });
  // Already logged in?
  if (await page.locator(".o_main_navbar, .o_home_menu, .o_web_client").count()) {
    return;
  }
  const dbSelect = page.locator('select[name="db"], #db');
  if (await dbSelect.count()) {
    await dbSelect.first().selectOption({ label: ODOO_DB }).catch(async () => {
      await dbSelect.first().selectOption(ODOO_DB).catch(() => undefined);
    });
  }
  await page.locator('input[name="login"]').first().fill(ODOO_LOGIN);
  await page.locator('input[name="password"]').first().fill(ODOO_PASSWORD);
  await page.getByRole("button", { name: /log ?in|تسجيل/i }).click();
  await page.waitForSelector(
    ".o_action_manager, .o_home_menu, .o_main_navbar, .o_web_client",
    { timeout: 90_000 },
  );
}

export async function openOdooPath(page: Page, pathSuffix: string): Promise<void> {
  const url = pathSuffix.startsWith("http")
    ? pathSuffix
    : `${ODOO_URL}${pathSuffix.startsWith("/") ? "" : "/"}${pathSuffix}`;
  await page.goto(url);
  await page.waitForLoadState("domcontentloaded");
  await page.waitForTimeout(800);
}

export async function authenticateOdooApi(
  request: APIRequestContext,
): Promise<void> {
  const res = await request.post(`${ODOO_URL}/web/session/authenticate`, {
    headers: { "Content-Type": "application/json" },
    data: {
      jsonrpc: "2.0",
      method: "call",
      params: {
        db: ODOO_DB,
        login: ODOO_LOGIN,
        password: ODOO_PASSWORD,
      },
      id: Date.now(),
    },
  });
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  if (body.error) {
    throw new Error(JSON.stringify(body.error));
  }
}

export async function odooCallKw<T>(
  request: APIRequestContext,
  model: string,
  method: string,
  args: unknown[] = [],
  kwargs: Record<string, unknown> = {},
): Promise<T> {
  const res = await request.post(`${ODOO_URL}/web/dataset/call_kw`, {
    headers: { "Content-Type": "application/json" },
    data: {
      jsonrpc: "2.0",
      method: "call",
      params: { model, method, args, kwargs },
      id: Date.now(),
    },
  });
  const body = await res.json();
  if (body.error) {
    throw new Error(body.error.data?.message || body.error.message || "odoo error");
  }
  return body.result as T;
}
