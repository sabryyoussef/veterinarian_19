# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import AccessError


class PetspotSupplierConfirmWizard(models.TransientModel):
    _name = "petspot.supplier.confirm.wizard"
    _description = "Record Supplier Confirmation"

    case_id = fields.Many2one("petspot.fulfillment.case", required=True)
    available = fields.Boolean(default=True)
    supplier_cost = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(related="case_id.currency_id")
    supplier_eta = fields.Date()
    supplier_reference = fields.Char()
    notes = fields.Text()
    price_changed = fields.Boolean(
        help="Tick if customer price/ETA must change → requires customer approval."
    )

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group("petspot_fulfillment.group_fulfillment_purchase"):
            raise AccessError(_("Purchase role required."))
        case = self.case_id
        if not self.available:
            case.supplier_notes = self.notes
            case.action_mark_unavailable()
            return {"type": "ir.actions.act_window_close"}
        case.write({
            "supplier_confirmed": True,
            "supplier_cost": self.supplier_cost,
            "supplier_eta": self.supplier_eta,
            "supplier_reference": self.supplier_reference,
            "supplier_notes": self.notes,
            "customer_approval_required": bool(self.price_changed),
            "customer_approved": False if self.price_changed else case.customer_approved,
        })
        case.message_post(
            body=_(
                "Supplier confirmed. Cost=%s ETA=%s Ref=%s price_changed=%s"
            )
            % (self.supplier_cost, self.supplier_eta, self.supplier_reference, self.price_changed)
        )
        if self.price_changed:
            case.action_transition("customer_approval_required", source="supplier_confirm")
        else:
            case.action_transition("supplier_confirmed", source="supplier_confirm")
        return {"type": "ir.actions.act_window_close"}
