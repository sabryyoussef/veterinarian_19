import type { Page } from "@playwright/test";
import { openModelForm, type OdooRpc } from "../helpers/odoo_rpc.js";

export class InquiryPage {
  constructor(
    private readonly page: Page,
    private readonly rpc: OdooRpc,
  ) {}

  async open(inquiryId: number): Promise<void> {
    await openModelForm(this.page, "petspot.availability.inquiry", inquiryId);
  }

  async clickAssess(): Promise<void> {
    const btn = this.page.getByRole("button", {
      name: /Assess Vetution Availability/i,
    });
    await btn.click();
    await this.page.waitForSelector(".o_form_view, .o_list_view", {
      timeout: 90_000,
    });
  }

  async assessViaRpc(inquiryId: number): Promise<number | null> {
    const action = await this.rpc.callKw<{ res_id?: number } | boolean>({
      model: "petspot.availability.inquiry",
      method: "action_assess_vetution_availability",
      args: [[inquiryId]],
    });
    if (action && typeof action === "object" && action.res_id) {
      return action.res_id;
    }
    const rows = await this.rpc.searchRead<{ id: number }>(
      "petspot.vetution.shadow.assessment",
      [["inquiry_id", "=", inquiryId]],
      ["id"],
      { limit: 1 },
    );
    return rows[0]?.id ?? null;
  }
}
