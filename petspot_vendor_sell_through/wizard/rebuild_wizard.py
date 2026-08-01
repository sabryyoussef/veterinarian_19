# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError


class PetspotVendorSellThroughRebuildWizard(models.TransientModel):
    _name = "petspot.vendor.sell.through.rebuild.wizard"
    _description = "Rebuild Sell-Through Allocations Wizard"

    move_id = fields.Many2one("account.move", required=True, readonly=True)
    company_id = fields.Many2one(related="move_id.company_id")
    system_layer_count = fields.Integer(compute="_compute_preview", readonly=True)
    system_alloc_count = fields.Integer(compute="_compute_preview", readonly=True)
    legacy_alloc_count = fields.Integer(compute="_compute_preview", readonly=True)
    approved_legacy_count = fields.Integer(compute="_compute_preview", readonly=True)
    reason = fields.Text(required=True)
    confirm = fields.Boolean(
        string="I confirm rebuilding system sell-through allocations for this bill",
        default=False,
    )

    @api.depends("move_id")
    def _compute_preview(self):
        Layer = self.env["petspot.vendor.sell.through.layer"]
        Allocation = self.env["petspot.vendor.sell.through.allocation"]
        for wiz in self:
            if not wiz.move_id:
                wiz.system_layer_count = 0
                wiz.system_alloc_count = 0
                wiz.legacy_alloc_count = 0
                wiz.approved_legacy_count = 0
                continue
            layers = Layer.search([("vendor_bill_id", "=", wiz.move_id.id)])
            allocs = Allocation.search([("vendor_bill_id", "=", wiz.move_id.id), ("active", "=", True)])
            wiz.system_layer_count = len(layers.filtered(lambda l: l.source_kind == "receipt"))
            wiz.system_alloc_count = len(allocs.filtered(lambda a: a.source_kind == "system"))
            wiz.legacy_alloc_count = len(allocs.filtered(lambda a: a.source_kind == "legacy"))
            wiz.approved_legacy_count = len(allocs.filtered(lambda a: a.status == "approved_legacy"))

    def action_confirm_rebuild(self):
        self.ensure_one()
        if not self.env.user.has_group("petspot_vendor_sell_through.group_vst_allocation_manager"):
            raise AccessError("Only Inventory allocation managers may rebuild sell-through allocations.")
        if not self.confirm:
            raise UserError("Please confirm the rebuild checkbox before continuing.")
        if not (self.reason or "").strip():
            raise UserError("A reason is required.")
        self.move_id._vst_run_rebuild(self.reason.strip())
        return {"type": "ir.actions.act_window_close"}
