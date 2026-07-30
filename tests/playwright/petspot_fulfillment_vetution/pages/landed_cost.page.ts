import type { Page } from "@playwright/test";
import { openAction, openModelForm, type OdooRpc } from "../helpers/odoo_rpc.js";
import { ACTION_XML, SYNTHETIC_POLICY_NAME } from "../helpers/env.js";

export class LandedCostPolicyPage {
  constructor(
    private readonly page: Page,
    private readonly rpc: OdooRpc,
  ) {}

  async openList(): Promise<void> {
    const id = await this.rpc.actionXmlIdToId(ACTION_XML.landed_cost_policy);
    await openAction(this.page, id);
  }

  async findCommercial(): Promise<Record<string, unknown> | null> {
    const rows = await this.rpc.callKw<Record<string, unknown>[]>({
      model: "petspot.vetution.landed.cost.policy",
      method: "search_read",
      args: [
        [
          ["is_synthetic_test", "=", false],
          ["active", "=", true],
        ],
        [
          "id",
          "name",
          "active",
          "is_synthetic_test",
          "allow_auto_quotation",
          "allow_customer_message",
          "allow_supplier_po",
          "allow_price_publish",
          "max_auto_delivery_subsidy",
          "customer_delivery_charge_amount",
          "customer_delivery_charge_status",
          "fulfillment_origin_note",
        ],
      ],
      kwargs: { limit: 5, context: { active_test: false } },
    });
    return rows[0] || null;
  }

  async findSynthetic(): Promise<Record<string, unknown> | null> {
    const rows = await this.rpc.callKw<Record<string, unknown>[]>({
      model: "petspot.vetution.landed.cost.policy",
      method: "search_read",
      args: [
        [["name", "=", SYNTHETIC_POLICY_NAME]],
        ["id", "name", "active", "is_synthetic_test"],
      ],
      kwargs: { limit: 1, context: { active_test: false } },
    });
    return rows[0] || null;
  }

  async open(policyId: number): Promise<void> {
    await openModelForm(
      this.page,
      "petspot.vetution.landed.cost.policy",
      policyId,
    );
  }
}
