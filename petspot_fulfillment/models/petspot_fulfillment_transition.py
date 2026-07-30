# -*- coding: utf-8 -*-
from odoo import fields, models

from .petspot_fulfillment_constants import ORCH_STATES


class PetspotFulfillmentTransition(models.Model):
    _name = "petspot.fulfillment.transition"
    _description = "PetSpot Fulfillment Transition Log"
    _order = "id desc"

    case_id = fields.Many2one(
        "petspot.fulfillment.case",
        required=True,
        ondelete="cascade",
        index=True,
    )
    from_state = fields.Selection(ORCH_STATES, required=True)
    to_state = fields.Selection(ORCH_STATES, required=True)
    source = fields.Char(required=True, help="manual / webhook / rfq_action / cron / …")
    user_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user)
    note = fields.Text()
    create_date = fields.Datetime(readonly=True)
