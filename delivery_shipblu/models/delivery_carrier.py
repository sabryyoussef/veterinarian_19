# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError

from odoo.addons.delivery_shipblu.services.shipment_service import ShipmentService
from odoo.addons.petspot_shipblu_base.services.shipblu_client import ShipBluApiError


class DeliveryCarrier(models.Model):
    _inherit = "delivery.carrier"

    delivery_type = fields.Selection(
        selection_add=[("shipblu", "ShipBlu")],
        ondelete={"shipblu": "set default"},
    )
    shipblu_backend_id = fields.Many2one("shipblu.backend", string="ShipBlu Backend")

    def _shipblu_backend(self, company=None):
        self.ensure_one()
        if self.shipblu_backend_id:
            return self.shipblu_backend_id
        return self.env["shipblu.backend"]._get_for_company(company or self.company_id or self.env.company)

    def shipblu_rate_shipment(self, order):
        """Fixed-price fallback until package-size pricing choices are configured."""
        self.ensure_one()
        return {
            "success": True,
            "price": float(self.fixed_price or 0.0),
            "error_message": False,
            "warning_message": _("ShipBlu live pricing needs a configured package size; using fixed price."),
        }

    def shipblu_send_shipping(self, pickings):
        self.ensure_one()
        res = []
        service = ShipmentService(self.env)
        for picking in pickings:
            try:
                shipment = service.create_from_picking(picking)
                res.append(
                    {
                        "exact_price": 0.0,
                        "tracking_number": shipment.tracking_number or "",
                        "tracking_url": shipment.tracking_url or False,
                    }
                )
            except (UserError, ShipBluApiError) as exc:
                raise UserError(str(exc)) from exc
        return res
