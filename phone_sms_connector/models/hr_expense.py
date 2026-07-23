# -*- coding: utf-8 -*-
"""Link hr.expense back to the bank SMS transaction that created it."""
from odoo import models, fields


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    bank_sms_transaction_id = fields.Many2one(
        'bank.sms.transaction',
        string='Bank SMS Transaction',
        ondelete='set null',
        index=True,
        copy=False,
        help='Outgoing bank SMS that this expense was created from.',
    )
