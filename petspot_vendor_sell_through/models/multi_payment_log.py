# -*- coding: utf-8 -*-
from odoo import fields, models


class PetspotVendorSellThroughMultiPaymentLog(models.Model):
    _name = "petspot.vendor.sell.through.multi.payment.log"
    _description = "Combined Sell-Through Payment Audit Log"
    _order = "id desc"

    name = fields.Char(required=True, index=True)
    user_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user)
    timestamp = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    partner_id = fields.Many2one("res.partner", required=True, index=True)
    company_id = fields.Many2one("res.company", required=True, index=True)
    currency_id = fields.Many2one("res.currency", required=True)
    bill_ids = fields.Many2many("account.move", string="Selected bills")
    eligibility_snapshot = fields.Text()
    allocation_snapshot = fields.Text()
    payment_amount = fields.Monetary(currency_field="currency_id")
    payment_id = fields.Many2one("account.payment", index=True)
    reconciliation_result = fields.Text()
    drift_rejected = fields.Boolean(default=False)
    idempotency_key = fields.Char(index=True)
    reason = fields.Text()

    _sql_constraints = [
        (
            "vst_multi_pay_idempotency_unique",
            "unique(idempotency_key)",
            "Duplicate combined sell-through payment confirmation blocked by idempotency key.",
        ),
    ]
