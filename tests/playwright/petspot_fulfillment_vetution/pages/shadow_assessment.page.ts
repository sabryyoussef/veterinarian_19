import type { Page } from "@playwright/test";
import { openAction, openModelForm, type OdooRpc } from "../helpers/odoo_rpc.js";
import { ACTION_XML } from "../helpers/env.js";

export class ShadowAssessmentPage {
  constructor(
    private readonly page: Page,
    private readonly rpc: OdooRpc,
  ) {}

  async openList(): Promise<void> {
    const id = await this.rpc.actionXmlIdToId(ACTION_XML.shadow_assessments);
    await openAction(this.page, id);
  }

  async open(assessmentId: number): Promise<void> {
    await openModelForm(
      this.page,
      "petspot.vetution.shadow.assessment",
      assessmentId,
    );
  }

  async readFields(assessmentId: number): Promise<Record<string, unknown>> {
    const rows = await this.rpc.searchRead<Record<string, unknown>>(
      "petspot.vetution.shadow.assessment",
      [["id", "=", assessmentId]],
      [
        "id",
        "name",
        "state",
        "supplier_cost",
        "landed_cost_incomplete",
        "eligible_future_automation",
        "product_decision_code",
        "delivery_decision_code",
        "suggested_price",
        "customer_delivery_charge",
      ],
      { limit: 1 },
    );
    return rows[0] || {};
  }
}
