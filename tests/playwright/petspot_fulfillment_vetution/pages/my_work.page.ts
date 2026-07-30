import type { Page } from "@playwright/test";
import { openAction, openModelForm, type OdooRpc } from "../helpers/odoo_rpc.js";
import { ACTION_XML } from "../helpers/env.js";

export class MyWorkPage {
  constructor(
    private readonly page: Page,
    private readonly rpc: OdooRpc,
  ) {}

  async openQueue(): Promise<number> {
    const actionId = await this.rpc.actionXmlIdToId(ACTION_XML.my_work);
    await openAction(this.page, actionId);
    return actionId;
  }

  async openInquiry(inquiryId: number): Promise<void> {
    await openModelForm(this.page, "petspot.availability.inquiry", inquiryId);
  }

  async clickOpenCorrectAction(): Promise<void> {
    const btn = this.page.getByRole("button", {
      name: /Open Correct Action/i,
    });
    await btn.first().click({ timeout: 30_000 });
    await this.page.waitForTimeout(1500);
  }

  async clickMarkDoneAndReassess(): Promise<void> {
    const btn = this.page.getByRole("button", {
      name: /Mark Done and Reassess/i,
    });
    await btn.first().click({ timeout: 30_000 });
    await this.page.waitForSelector(".o_form_view, .o_list_view, .o_kanban_view", {
      timeout: 90_000,
    });
  }

  async switchToList(): Promise<void> {
    const list = this.page.locator(
      "button[data-tooltip*='List'], button[aria-label*='List'], .o_cp_switch_buttons button:has(.oi-view-list), .o_switch_view[data-tooltip='List']",
    );
    if (await list.count()) {
      await list.first().click({ timeout: 10_000 }).catch(() => undefined);
      await this.page.waitForTimeout(800);
    }
  }
}
