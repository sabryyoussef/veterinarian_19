import type { Page } from "@playwright/test";
import { odooUrl } from "../helpers/env.js";
import type { OdooRpc } from "../helpers/odoo_rpc.js";

export class SystemParametersPage {
  constructor(
    private readonly page: Page,
    private readonly rpc: OdooRpc,
  ) {}

  /** Prefer RPC reads; open UI list filtered by key prefix for screenshots. */
  async openVetutionParamsUi(): Promise<void> {
    // Technical → System Parameters via model URL (stable)
    await this.page.goto(
      `${odooUrl()}/odoo/ir.config_parameter?search=petspot_fulfillment`,
      { waitUntil: "domcontentloaded", timeout: 90_000 },
    );
    await this.page.waitForSelector(
      ".o_list_view, .o_list_renderer, .o_action_manager .o_content",
      { timeout: 90_000 },
    );
  }

  async readIcpMap(keys: string[]): Promise<Record<string, string>> {
    const out: Record<string, string> = {};
    for (const key of keys) {
      out[key] = await this.rpc.getParam(key, "");
    }
    return out;
  }
}
