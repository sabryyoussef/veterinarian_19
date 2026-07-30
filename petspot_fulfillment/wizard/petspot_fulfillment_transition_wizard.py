# -*- coding: utf-8 -*-
from odoo import fields, models


class PetspotFulfillmentTransitionWizard(models.TransientModel):
    _name = "petspot.fulfillment.transition.wizard"
    _description = "Manual Fulfillment Transition"

    case_id = fields.Many2one("petspot.fulfillment.case", required=True)
    target_state = fields.Selection(
        selection=lambda self: self.env["petspot.fulfillment.case"]._fields["state"].selection,
        string="New State",
        required=True,
    )
    note = fields.Text()

    def action_apply(self):
        self.ensure_one()
        self.case_id.action_transition(
            self.target_state, source="manual_wizard", note=self.note
        )
        return {"type": "ir.actions.act_window_close"}
