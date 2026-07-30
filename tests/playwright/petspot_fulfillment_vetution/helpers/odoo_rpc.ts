import { expect, type APIRequestContext, type Page } from "@playwright/test";
import {
  odooDb,
  odooLogin,
  odooPassword,
  odooUrl,
  requireCredentials,
} from "./env.js";

export type CallKwArgs = {
  model: string;
  method: string;
  args?: unknown[];
  kwargs?: Record<string, unknown>;
};

export class OdooRpc {
  constructor(
    private readonly api: APIRequestContext,
    private readonly baseUrl = odooUrl(),
    private readonly db = odooDb(),
  ) {}

  async authenticate(login = odooLogin(), password = odooPassword()): Promise<number> {
    requireCredentials();
    const res = await this.api.post(`${this.baseUrl}/web/session/authenticate`, {
      headers: { "Content-Type": "application/json" },
      data: {
        jsonrpc: "2.0",
        method: "call",
        params: { db: this.db, login, password },
        id: Date.now(),
      },
    });
    expect(res.ok(), `auth HTTP ${res.status()}`).toBeTruthy();
    const body = await res.json();
    if (body.error) {
      throw new Error(
        body.error.data?.message || body.error.message || "authenticate failed",
      );
    }
    const uid = body.result?.uid;
    if (!uid) {
      throw new Error("BLOCKED_MISSING_UI_CREDENTIALS: authenticate returned no uid");
    }
    return uid as number;
  }

  async callKw<T = unknown>(opts: CallKwArgs): Promise<T> {
    const res = await this.api.post(`${this.baseUrl}/web/dataset/call_kw`, {
      headers: { "Content-Type": "application/json" },
      data: {
        jsonrpc: "2.0",
        method: "call",
        params: {
          model: opts.model,
          method: opts.method,
          args: opts.args ?? [],
          kwargs: opts.kwargs ?? {},
        },
        id: Date.now(),
      },
    });
    const body = await res.json();
    if (body.error) {
      const msg =
        body.error.data?.message ||
        body.error.message ||
        JSON.stringify(body.error);
      throw new Error(msg);
    }
    return body.result as T;
  }

  async getParam(key: string, defaultValue = ""): Promise<string> {
    const val = await this.callKw<string | false>({
      model: "ir.config_parameter",
      method: "get_param",
      args: [key, defaultValue],
    });
    return val === false || val == null ? defaultValue : String(val);
  }

  async searchRead<T extends Record<string, unknown>>(
    model: string,
    domain: unknown[],
    fields: string[],
    opts: { limit?: number; order?: string } = {},
  ): Promise<T[]> {
    return this.callKw<T[]>({
      model,
      method: "search_read",
      args: [domain, fields],
      kwargs: {
        limit: opts.limit ?? 80,
        order: opts.order ?? "id desc",
      },
    });
  }

  async searchCount(model: string, domain: unknown[] = []): Promise<number> {
    return this.callKw<number>({
      model,
      method: "search_count",
      args: [domain],
    });
  }

  async actionXmlIdToId(xmlId: string): Promise<number> {
    const [mod, name] = xmlId.split(".");
    const rows = await this.searchRead<{ res_id: number }>(
      "ir.model.data",
      [
        ["module", "=", mod],
        ["name", "=", name],
      ],
      ["res_id"],
      { limit: 1 },
    );
    if (!rows.length) throw new Error(`xml id not found: ${xmlId}`);
    return rows[0].res_id;
  }

  async resolveActionIds(xmlIds: string[]): Promise<Map<string, number>> {
    const map = new Map<string, number>();
    for (const xmlId of xmlIds) {
      try {
        map.set(xmlId, await this.actionXmlIdToId(xmlId));
      } catch {
        // optional menus
      }
    }
    return map;
  }

  async moduleVersion(technicalName: string): Promise<string | null> {
    const rows = await this.searchRead<{ latest_version?: string; name: string }>(
      "ir.module.module",
      [["name", "=", technicalName]],
      ["name", "latest_version", "installed_version"],
      { limit: 1 },
    );
    if (!rows.length) return null;
    const row = rows[0] as { latest_version?: string; installed_version?: string };
    return row.installed_version || row.latest_version || null;
  }
}

export async function loginBackend(page: Page): Promise<void> {
  requireCredentials();
  const url = odooUrl();
  const db = odooDb();
  await page.goto(`${url}/web/login?db=${encodeURIComponent(db)}`, {
    waitUntil: "domcontentloaded",
    timeout: 60_000,
  });
  if (await page.locator(".o_main_navbar, .o_home_menu, .o_web_client").count()) {
    return;
  }
  // Do not screenshot the password form
  await page.locator('input[name="login"]').first().fill(odooLogin());
  await page.locator('input[name="password"]').first().fill(odooPassword());
  await page.getByRole("button", { name: /log ?in|تسجيل/i }).click();
  await page.waitForSelector(
    ".o_action_manager, .o_home_menu, .o_main_navbar, .o_web_client",
    { timeout: 90_000 },
  );
}

export function backendActionUrl(actionId: number, recordId?: number): string {
  const base = odooUrl();
  if (recordId) return `${base}/odoo/action-${actionId}/${recordId}`;
  return `${base}/odoo/action-${actionId}`;
}

export async function dismissClientErrors(page: Page): Promise<void> {
  const dialog = page.locator(".modal, .o_error_dialog, .o_dialog").filter({
    hasText: /Oops|Something went wrong|traceback|Error/i,
  });
  if (await dialog.count()) {
    const close = dialog
      .locator(
        "button:has-text('Ok'), button:has-text('Close'), button:has-text('OK'), .btn-close, button[aria-label='Close']",
      )
      .first();
    if (await close.count()) {
      await close.click({ timeout: 5_000 }).catch(() => undefined);
    } else {
      await page.keyboard.press("Escape").catch(() => undefined);
    }
  }
}

async function waitForBackendView(
  page: Page,
  view: "list" | "form" = "list",
): Promise<void> {
  await dismissClientErrors(page);
  const sel =
    view === "form"
      ? ".o_form_view, .o_form_renderer, .o_action_manager .o_content, .o_control_panel"
      : ".o_list_view, .o_list_renderer, .o_kanban_view, .o_kanban_renderer, .o_action_manager .o_content, .o_control_panel";
  await page.waitForSelector(sel, { timeout: 90_000 });
}

export async function openAction(
  page: Page,
  actionId: number,
  opts: { recordId?: number; view?: "list" | "form"; model?: string } = {},
): Promise<void> {
  const view = opts.view || (opts.recordId ? "form" : "list");
  // Prefer Odoo 19 path router, then hash fallback
  await page.goto(backendActionUrl(actionId, opts.recordId), {
    waitUntil: "domcontentloaded",
    timeout: 90_000,
  });
  try {
    await waitForBackendView(page, view);
    return;
  } catch {
    await dismissClientErrors(page);
  }
  const hashParts = [`action=${actionId}`, `view_type=${view}`];
  if (opts.model) hashParts.push(`model=${opts.model}`);
  if (opts.recordId) hashParts.push(`id=${opts.recordId}`);
  await page.goto(`${odooUrl()}/web#${hashParts.join("&")}`, {
    waitUntil: "domcontentloaded",
    timeout: 90_000,
  });
  await waitForBackendView(page, view);
}

export async function openModelForm(
  page: Page,
  model: string,
  recordId: number,
  actionId?: number,
): Promise<void> {
  if (actionId) {
    await openAction(page, actionId, {
      recordId,
      view: "form",
      model,
    });
    return;
  }
  await page.goto(`${odooUrl()}/odoo/${model}/${recordId}`, {
    waitUntil: "domcontentloaded",
    timeout: 90_000,
  });
  try {
    await waitForBackendView(page, "form");
    return;
  } catch {
    await dismissClientErrors(page);
  }
  await page.goto(
    `${odooUrl()}/web#id=${recordId}&model=${model}&view_type=form`,
    { waitUntil: "domcontentloaded", timeout: 90_000 },
  );
  await waitForBackendView(page, "form");
}

export async function hasTraceback(page: Page): Promise<boolean> {
  await dismissClientErrors(page);
  const n = await page
    .locator(
      ".o_error_dialog, .o_notification_manager .o_notification_danger, .o_traceback, .modal:has-text('Oops')",
    )
    .count();
  return n > 0;
}
