# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import AccessError, UserError


class PetspotMarkPaidWizard(models.TransientModel):
    _name = "petspot.mark.paid.wizard"
    _description = "Mark Fulfillment Case Paid (controlled)"

    case_id = fields.Many2one("petspot.fulfillment.case", required=True)
    payment_reference = fields.Char(required=True)
    journal_id = fields.Many2one("account.journal", string="Journal")
    note = fields.Text()

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group("petspot_fulfillment.group_fulfillment_manager"):
            raise AccessError(_("Only fulfillment managers can Mark Paid manually."))
        case = self.case_id
        case.write({
            "payment_status": "manual_paid",
            "payment_reference": self.payment_reference,
        })
        case.message_post(
            body=_(
                "Manually marked paid. Reference: %s. Journal: %s. Note: %s"
            )
            % (
                self.payment_reference,
                self.journal_id.display_name if self.journal_id else "-",
                self.note or "-",
            )
        )
        if case.state in ("payment_pending", "supplier_confirmed", "customer_approval_required", "new"):
            case.action_transition("paid", source="manual_mark_paid", note=self.note)
        return {"type": "ir.actions.act_window_close"}
