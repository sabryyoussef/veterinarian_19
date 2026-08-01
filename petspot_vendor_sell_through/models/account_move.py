# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    vst_total_bill = fields.Monetary(string="Total Bill", currency_field="currency_id", copy=False)
    vst_eligible_amount = fields.Monetary(
        string="Sell-Through Eligible Amount",
        currency_field="currency_id",
        copy=False,
    )
    vst_already_paid = fields.Monetary(string="Already Paid", currency_field="currency_id", copy=False)
    vst_suggested_payment = fields.Monetary(
        string="Suggested Payment Now",
        currency_field="currency_id",
        copy=False,
    )
    vst_bill_residual = fields.Monetary(string="Bill Residual", currency_field="currency_id", copy=False)
    vst_unallocated_qty = fields.Float(string="Unallocated/Uncertain Quantity", copy=False)
    vst_last_recalculation = fields.Datetime(string="Last Recalculation", copy=False)
    vst_allocation_ids = fields.One2many(
        "petspot.vendor.sell.through.allocation",
        "vendor_bill_id",
        string="Sell-Through Allocations",
    )
    vst_layer_ids = fields.One2many(
        "petspot.vendor.sell.through.layer",
        "vendor_bill_id",
        string="Sell-Through Layers",
    )
    vst_sold_count = fields.Integer(compute="_compute_vst_counts")
    vst_receipt_count = fields.Integer(compute="_compute_vst_counts")
    vst_sale_count = fields.Integer(compute="_compute_vst_counts")
    # Read-only display of product bill lines (avoids a second editable invoice_line_ids on the form)
    vst_sold_line_ids = fields.Many2many(
        "account.move.line",
        compute="_compute_vst_sold_line_ids",
        string="Sold Items Lines",
    )
    vst_rebuild_recommended = fields.Boolean(
        compute="_compute_vst_rebuild_recommended",
        string="Sell-through rebuild recommended",
    )
    vst_purchased_value = fields.Monetary(
        string="Purchased value",
        currency_field="currency_id",
        compute="_compute_vst_dashboard_fields",
        store=True,
    )
    vst_net_sold_value = fields.Monetary(
        string="Net sold value",
        currency_field="currency_id",
        compute="_compute_vst_dashboard_fields",
        store=True,
    )
    vst_payment_cap = fields.Monetary(
        string="Suggested payment now",
        currency_field="currency_id",
        compute="_compute_vst_dashboard_fields",
        store=True,
    )
    vst_allocation_confidence = fields.Char(
        string="Allocation confidence",
        compute="_compute_vst_dashboard_fields",
        store=True,
    )
    vst_blocking_warning = fields.Char(
        string="Blocking warning",
        compute="_compute_vst_dashboard_fields",
        store=True,
    )
    vst_sell_through_status = fields.Selection(
        [
            ("none", "No sell-through"),
            ("payable", "Payable"),
            ("legacy_only", "Legacy/estimated only"),
            ("blocked", "Blocked/unallocated"),
            ("paid", "No residual"),
        ],
        compute="_compute_vst_dashboard_fields",
        store=True,
        string="Sell-through status",
    )

    def _compute_vst_counts(self):
        Allocation = self.env["petspot.vendor.sell.through.allocation"]
        Layer = self.env["petspot.vendor.sell.through.layer"]
        for move in self:
            layers = Layer.search([("vendor_bill_id", "=", move.id)])
            allocs = Allocation.search(
                [("vendor_bill_id", "=", move.id), ("active", "=", True), ("is_return", "=", False)]
            )
            move.vst_sold_count = len(allocs)
            move.vst_receipt_count = len(layers.mapped("incoming_move_id"))
            move.vst_sale_count = len(allocs.mapped("outgoing_picking_id"))

    @api.depends("invoice_line_ids", "invoice_line_ids.product_id", "invoice_line_ids.display_type")
    def _compute_vst_sold_line_ids(self):
        for move in self:
            move.vst_sold_line_ids = move.invoice_line_ids.filtered(
                lambda l: l.display_type not in ("line_section", "line_note") and l.product_id
            )

    @api.depends("vst_layer_ids", "vst_last_recalculation", "state", "move_type")
    def _compute_vst_rebuild_recommended(self):
        for move in self:
            if move.move_type not in ("in_invoice", "in_refund") or move.state != "posted":
                move.vst_rebuild_recommended = False
                continue
            has_storable = any(
                l.product_id and l.product_id.is_storable
                for l in move.invoice_line_ids
                if l.display_type not in ("line_section", "line_note")
            )
            move.vst_rebuild_recommended = bool(has_storable and (not move.vst_layer_ids or not move.vst_last_recalculation))

    @api.depends(
        "amount_total",
        "amount_residual",
        "vst_eligible_amount",
        "vst_suggested_payment",
        "vst_unallocated_qty",
        "invoice_line_ids.vst_tracking_confidence",
        "invoice_line_ids.vst_sold_gross",
        "state",
        "move_type",
    )
    def _compute_vst_dashboard_fields(self):
        from odoo.addons.petspot_vendor_sell_through.services.multi_payment import bill_payment_cap

        for move in self:
            if move.move_type not in ("in_invoice", "in_refund"):
                move.vst_purchased_value = 0.0
                move.vst_net_sold_value = 0.0
                move.vst_payment_cap = 0.0
                move.vst_allocation_confidence = False
                move.vst_blocking_warning = False
                move.vst_sell_through_status = "none"
                continue
            move.vst_purchased_value = move.amount_untaxed
            move.vst_net_sold_value = move.vst_eligible_amount or 0.0
            cap = bill_payment_cap(move) if move.state == "posted" else 0.0
            move.vst_payment_cap = cap
            confs = set(
                move.invoice_line_ids.filtered(lambda l: l.product_id).mapped("vst_tracking_confidence")
            ) - {False, None}
            payable_conf = confs & {"exact_lot", "exact_fifo", "approved_legacy", "approved_invoice"}
            nonpay_conf = confs & {"estimated_legacy", "unallocated"}
            if "blocked_uom" in confs:
                move.vst_allocation_confidence = "blocked_uom"
                move.vst_blocking_warning = "Blocked UoM conversions present"
            elif nonpay_conf and not payable_conf:
                move.vst_allocation_confidence = ",".join(sorted(confs))
                move.vst_blocking_warning = "Only non-payable statuses (estimated/unallocated)"
            elif confs:
                move.vst_allocation_confidence = ",".join(sorted(confs))
                if nonpay_conf and payable_conf:
                    move.vst_blocking_warning = (
                        "Includes estimated/unallocated rows (not payable); payable portion only in suggested amount"
                    )
                else:
                    move.vst_blocking_warning = False
            else:
                move.vst_allocation_confidence = "none"
                move.vst_blocking_warning = "No sell-through allocations" if move.state == "posted" else False

            if move.amount_residual <= 0:
                move.vst_sell_through_status = "paid"
            elif move.vst_blocking_warning and "Blocked" in (move.vst_blocking_warning or ""):
                move.vst_sell_through_status = "blocked"
            elif cap > 0:
                move.vst_sell_through_status = "payable"
            elif nonpay_conf and not payable_conf:
                move.vst_sell_through_status = "legacy_only"
            else:
                move.vst_sell_through_status = "none"

    def action_vst_recompute(self):
        """Open explicit rebuild wizard — never rebuilds on view/open."""
        self.ensure_one()
        if self.move_type not in ("in_invoice", "in_refund"):
            raise UserError("Sell-through applies to Vendor Bills / Refunds only.")
        if not self.env.user.has_group("petspot_vendor_sell_through.group_vst_allocation_manager"):
            raise AccessError("Only Inventory allocation managers may rebuild sell-through allocations.")
        return {
            "type": "ir.actions.act_window",
            "name": "Rebuild Sell-Through Allocations / إعادة بناء تخصيصات المبيعات",
            "res_model": "petspot.vendor.sell.through.rebuild.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_move_id": self.id},
        }

    def _vst_run_rebuild(self, reason):
        """Manager/test entrypoint: explicit rebuild with reason (not used on form open)."""
        self.ensure_one()
        if not self.env.user.has_group("petspot_vendor_sell_through.group_vst_allocation_manager"):
            raise AccessError("Only Inventory allocation managers may rebuild sell-through allocations.")
        if not (reason or "").strip():
            raise UserError("A reason is required to rebuild sell-through allocations.")
        from odoo.addons.petspot_vendor_sell_through.services.allocator import full_rebuild_bill

        before_allocs = self.env["petspot.vendor.sell.through.allocation"].search(
            [("vendor_bill_id", "=", self.id)]
        )
        before_snap = [(a.id, a.status, a.qty_base, a.source_kind) for a in before_allocs]
        full_rebuild_bill(self.env, self)
        after_allocs = self.env["petspot.vendor.sell.through.allocation"].search(
            [("vendor_bill_id", "=", self.id)]
        )
        after_snap = [(a.id, a.status, a.qty_base, a.source_kind) for a in after_allocs]
        self.message_post(
            body=(
                "Sell-through rebuild by %s.<br/>Reason: %s<br/>"
                "Before: %s<br/>After: %s"
                % (self.env.user.display_name, reason, before_snap, after_snap)
            ),
            subtype_xmlid="mail.mt_note",
        )
        return True

    def action_vst_open_allocations(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Sold Items",
            "res_model": "petspot.vendor.sell.through.allocation",
            "view_mode": "list,form",
            "domain": [("vendor_bill_id", "=", self.id), ("active", "=", True)],
            "context": {"default_vendor_bill_id": self.id, "create": False, "edit": False, "delete": False},
        }

    def action_vst_open_receipts(self):
        self.ensure_one()
        picking_ids = self.vst_layer_ids.mapped("incoming_move_id.picking_id").ids
        return {
            "type": "ir.actions.act_window",
            "name": "Source Receipts",
            "res_model": "stock.picking",
            "view_mode": "list,form",
            "domain": [("id", "in", picking_ids)],
        }

    def action_vst_open_sales(self):
        self.ensure_one()
        picking_ids = self.vst_allocation_ids.filtered(lambda a: a.active and not a.is_return).mapped(
            "outgoing_picking_id"
        ).ids
        return {
            "type": "ir.actions.act_window",
            "name": "Customer Sales",
            "res_model": "stock.picking",
            "view_mode": "list,form",
            "domain": [("id", "in", picking_ids)],
        }

    def action_vst_register_payment(self):
        """Open payment review using existing stored metrics — no rebuild/unlink."""
        self.ensure_one()
        if not self.env.user.has_group("petspot_vendor_sell_through.group_vst_payment_manager"):
            raise AccessError("Only Accounting payment managers may register sell-through payments.")
        if self.move_type != "in_invoice" or self.state != "posted":
            raise UserError("Sell-through payment requires a posted Vendor Bill.")
        return {
            "type": "ir.actions.act_window",
            "name": "Register Sell-Through Payment / دفع قيمة المنتجات المباعة",
            "res_model": "petspot.vendor.sell.through.payment.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_move_id": self.id,
                "default_amount": self.vst_suggested_payment,
            },
        }

    def action_vst_register_combined_payment(self):
        """Open combined payment wizard for selected bills — no rebuild on open."""
        if not self.env.user.has_group("petspot_vendor_sell_through.group_vst_payment_manager"):
            raise AccessError("Only Accounting payment managers may register combined sell-through payments.")
        bills = self.filtered(lambda m: m.move_type == "in_invoice" and m.state == "posted")
        if not bills:
            raise UserError("Select one or more posted Vendor Bills.")
        from odoo.addons.petspot_vendor_sell_through.services.multi_payment import validate_bill_selection

        validate_bill_selection(bills)
        return {
            "type": "ir.actions.act_window",
            "name": "Register Combined Sell-Through Payment / تسجيل دفعة مجمعة حسب المنتجات المباعة",
            "res_model": "petspot.vendor.sell.through.multi.payment.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"active_model": "account.move", "active_ids": bills.ids, "active_id": bills[:1].id},
        }

    def action_post(self):
        res = super().action_post()
        self._vst_post_hook()
        return res

    def _vst_post_hook(self):
        """System rebuild after post — service uses sudo; never runs on form read."""
        from odoo.addons.petspot_vendor_sell_through.services.allocator import full_rebuild_bill

        for move in self.filtered(lambda m: m.move_type in ("in_invoice", "in_refund") and m.state == "posted"):
            try:
                with self.env.cr.savepoint():
                    full_rebuild_bill(self.env, move, system_event=True)
            except Exception:
                continue
