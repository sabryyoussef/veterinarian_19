import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const BASE = (process.env.ODOO_URL || "http://127.0.0.1:8076").replace(
  /\/$/,
  "",
);
export const DB = process.env.ODOO_DB || "neo_odoo";
export const LOGIN = process.env.ODOO_LOGIN || "admin";
export const PASSWORD = process.env.ODOO_PASSWORD || "admin";

export async function jsonRpc<T>(
  api: APIRequestContext,
  urlPath: string,
  params: Record<string, unknown>,
): Promise<T> {
  const res = await api.post(urlPath, {
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

export async function authenticateSession(
  api: APIRequestContext,
  login = LOGIN,
  password = PASSWORD,
): Promise<void> {
  await jsonRpc(api, "/web/session/authenticate", {
    db: DB,
    login,
    password,
  });
}

export async function actionXmlIdToId(
  api: APIRequestContext,
  xmlId: string,
): Promise<number> {
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

export async function searchOneId(
  api: APIRequestContext,
  model: string,
  domain: unknown[],
): Promise<number | null> {
  const rows = await callKw<Array<{ id: number }>>(
    api,
    model,
    "search_read",
    [domain, ["id"]],
    { limit: 1, order: "id desc" },
  );
  return rows?.[0]?.id ?? null;
}

export type OdooViewTarget = {
  model: string;
  viewType?: "list" | "form" | "kanban" | "calendar";
  actionXmlId?: string;
  actionId?: number;
  recordId?: number;
};

/** Build backend URL (Odoo 19 path router; hash fallback on /web). */
export function backendUrl(target: OdooViewTarget): string {
  const viewType = target.viewType || (target.recordId ? "form" : "list");
  if (target.actionId && target.recordId) {
    return `/odoo/action-${target.actionId}/${target.recordId}`;
  }
  if (target.actionId) {
    return `/odoo/action-${target.actionId}`;
  }
  if (target.recordId) {
    return `/odoo/${target.model}/${target.recordId}`;
  }
  const hashParts: string[] = [`model=${target.model}`, `view_type=${viewType}`];
  return `/web#${hashParts.join("&")}`;
}

export async function loginBackend(page: Page): Promise<void> {
  await page.goto("/web/login?redirect=/web");
  await page.locator('input[name="login"]').first().fill(LOGIN);
  await page.locator('input[name="password"]').first().fill(PASSWORD);
  await page.getByRole("button", { name: /log in/i }).click();
  await page.waitForSelector(
    ".o_action_manager, .o_home_menu, .o_main_navbar",
    { timeout: 90_000 },
  );
}

export async function openBackendView(
  page: Page,
  target: OdooViewTarget,
  actionIds: Map<string, number>,
): Promise<void> {
  let actionId = target.actionId;
  if (!actionId && target.actionXmlId) {
    actionId = actionIds.get(target.actionXmlId);
  }
  const url = backendUrl({
    ...target,
    actionId,
  });
  await page.goto(url);
  const viewType = target.viewType || (target.recordId ? "form" : "list");
  const viewSelectors: Record<string, string> = {
    list: ".o_list_view, .o_list_renderer",
    form: ".o_form_view",
    kanban: ".o_kanban_view, .o_kanban_renderer",
    calendar: ".o_calendar_view",
  };
  const viewSel = viewSelectors[viewType] || ".o_action_manager";
  await page.waitForSelector(
    `${viewSel}, .o_action_manager .o_content`,
    { timeout: 90_000 },
  );
  await page.waitForTimeout(500);
}

export async function resolveActionIds(
  api: APIRequestContext,
  xmlIds: string[],
  optional = false,
): Promise<Map<string, number>> {
  const map = new Map<string, number>();
  for (const xmlId of xmlIds) {
    try {
      map.set(xmlId, await actionXmlIdToId(api, xmlId));
    } catch (err) {
      if (!optional) {
        throw err;
      }
    }
  }
  return map;
}
