# -*- coding: utf-8 -*-
import json

from odoo import fields, models
from odoo.exceptions import AccessError, UserError


class PetspotVendorSellThroughInvoiceBackfillWizard(models.TransientModel):
    _name = "petspot.vendor.sell.through.invoice.backfill.wizard"
    _description = "Invoice Commercial Sell-Through Backfill"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    cutoff_date = fields.Date(
        required=True,
        default=lambda self: fields.Date.to_date(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("petspot_vendor_sell_through.invoice_commercial_cutoff", "2026-08-01")
        ),
    )
    dry_run = fields.Boolean(default=True)
    vendor_bill_id = fields.Many2one(
        "account.move",
        domain="[('move_type', '=', 'in_invoice'), ('state', '=', 'posted'), ('company_id', '=', company_id)]",
        help="Optional: limit backfill to products on this vendor bill.",
    )
    result_json = fields.Text(readonly=True)
    result_summary = fields.Html(readonly=True)

    def action_run(self):
        self.ensure_one()
        if not self.env.user.has_group("petspot_vendor_sell_through.group_vst_allocation_manager"):
            raise AccessError("Only Inventory allocation managers may run invoice commercial backfill.")
        from odoo.addons.petspot_vendor_sell_through.services.invoice_commercial import (
            allocate_invoice_commercial_for_bill,
            backfill_company,
        )

        if self.vendor_bill_id:
            report = allocate_invoice_commercial_for_bill(
                self.env,
                self.vendor_bill_id,
                cutoff_date=self.cutoff_date,
                dry_run=self.dry_run,
            )
            report["dry_run"] = self.dry_run
            report["cutoff"] = str(self.cutoff_date)
        else:
            report = backfill_company(
                self.env,
                self.company_id,
                cutoff_date=self.cutoff_date,
                dry_run=self.dry_run,
            )

        summary = (
            "<p><b>%s</b> cutoff=%s</p>"
            "<p>Allocated base qty: %s</p>"
            "<p>Eligible amount: %s</p>"
            "<p>Sources: %s · Blocked: %s</p>"
            % (
                "DRY RUN" if self.dry_run else "APPLIED",
                report.get("cutoff"),
                report.get("allocated_qty_base"),
                report.get("eligible_amount"),
                len(report.get("sources") or []),
                len(report.get("blocked") or []),
            )
        )
        self.write(
            {
                "result_json": json.dumps(report, default=str, indent=2),
                "result_summary": summary,
            }
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
