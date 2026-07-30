import type { Page } from "@playwright/test";
import { openAction, hasTraceback, type OdooRpc } from "../helpers/odoo_rpc.js";
import { ACTION_XML } from "../helpers/env.js";

export type MenuShot = {
  key: string;
  label: string;
  xmlId: string;
  ok: boolean;
  traceback: boolean;
  actionId?: number;
};

export class VetutionBridgePage {
  constructor(
    private readonly page: Page,
    private readonly rpc: OdooRpc,
  ) {}

  async openMenus(keys?: string[]): Promise<MenuShot[]> {
    const selected = keys || Object.keys(ACTION_XML);
    const actionIds = await this.rpc.resolveActionIds(
      selected.map((k) => ACTION_XML[k]).filter(Boolean),
    );
    const shots: MenuShot[] = [];
    for (const key of selected) {
      const xmlId = ACTION_XML[key];
      if (!xmlId) continue;
      const actionId = actionIds.get(xmlId);
      if (!actionId) {
        shots.push({
          key,
          label: key,
          xmlId,
          ok: false,
          traceback: false,
        });
        continue;
      }
      await openAction(this.page, actionId);
      const tb = await hasTraceback(this.page);
      shots.push({
        key,
        label: key,
        xmlId,
        ok: !tb,
        traceback: tb,
        actionId,
      });
    }
    return shots;
  }
}
