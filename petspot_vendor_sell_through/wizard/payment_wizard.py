# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare


class PetspotVendorSellThroughPaymentWizard(models.TransientModel):
    _name = "petspot.vendor.sell.through.payment.wizard"
    _description = "Register Sell-Through Payment Review Wizard"

    move_id = fields.Many2one("account.move", required=True, readonly=True)
    currency_id = fields.Many2one(related="move_id.currency_id")
    eligible_amount = fields.Monetary(related="move_id.vst_eligible_amount", readonly=True)
    already_paid = fields.Monetary(related="move_id.vst_already_paid", readonly=True)
    residual = fields.Monetary(related="move_id.amount_residual", readonly=True)
    suggested_amount = fields.Monetary(related="move_id.vst_suggested_payment", readonly=True)
    amount = fields.Monetary(string="Payment amount to register", required=True, currency_field="currency_id")
    journal_id = fields.Many2one(
        "account.journal",
        string="Payment journal",
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
    )
    company_id = fields.Many2one(related="move_id.company_id")
    rebuild_recommended = fields.Boolean(related="move_id.vst_rebuild_recommended", readonly=True)
    last_recalculation = fields.Datetime(related="move_id.vst_last_recalculation", readonly=True)
    confirm_post = fields.Boolean(
        string="Post payment now (TEST automation only)",
        default=False,
        help="Manual UAT must leave this unchecked. Automated tests may enable inside rollback transactions.",
    )

    @api.onchange("move_id")
    def _onchange_move(self):
        if self.move_id:
            self.amount = self.move_id.vst_suggested_payment

    def action_open_standard_payment(self):
        """Open Odoo standard payment register with the reviewed amount. Does not rebuild or auto-post."""
        self.ensure_one()
        if not self.env.user.has_group("petspot_vendor_sell_through.group_vst_payment_manager"):
            raise AccessError("Only Accounting payment managers may launch sell-through payment.")
        self._validate_amount()
        ctx = {
            "active_model": "account.move",
            "active_ids": [self.move_id.id],
            "active_id": self.move_id.id,
            "default_amount": self.amount,
        }
        action = {
            "type": "ir.actions.act_window",
            "name": "Register Payment",
            "res_model": "account.payment.register",
            "view_mode": "form",
            "target": "new",
            "context": ctx,
        }
        if self.confirm_post:
            pay = (
                self.env["account.payment.register"]
                .with_context(**ctx)
                .create(
                    {
                        "amount": self.amount,
                        "journal_id": self.journal_id.id if self.journal_id else False,
                    }
                )
            )
            pay.action_create_payments()
            return {"type": "ir.actions.act_window_close"}
        return action

    def _validate_amount(self):
        bill = self.move_id
        currency = bill.currency_id
        if float_compare(self.amount, 0.0, precision_rounding=currency.rounding) <= 0:
            raise UserError("Payment amount must be positive.")
        if float_compare(self.amount, bill.amount_residual, precision_rounding=currency.rounding) > 0:
            raise UserError("Payment cannot exceed bill residual.")
        max_eligible = max(0.0, bill.vst_eligible_amount - bill.vst_already_paid)
        if float_compare(self.amount, max_eligible, precision_rounding=currency.rounding) > 0:
            raise UserError("Payment cannot exceed remaining sell-through eligible amount.")
        if float_compare(self.amount, bill.vst_suggested_payment, precision_rounding=currency.rounding) > 0:
            raise UserError("Payment cannot exceed the suggested sell-through amount.")
