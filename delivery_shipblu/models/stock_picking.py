# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError

from odoo.addons.delivery_shipblu.services.shipment_service import ShipmentService
from odoo.addons.delivery_shipblu.services.status_mapping import NORMALIZED


class StockPicking(models.Model):
    _inherit = "stock.picking"

    shipblu_shipment_ids = fields.One2many("shipblu.shipment", "picking_id", string="ShipBlu Shipments")
    shipblu_shipment_id = fields.Many2one(
        "shipblu.shipment",
        compute="_compute_shipblu_shipment",
        string="ShipBlu Shipment",
    )
    shipblu_order_id = fields.Char(copy=False, index=True)
    shipblu_shipment_owner = fields.Selection(
        [
            ("legacy_shopify", "Legacy Shopify ShipBlu"),
            ("odoo_shipblu", "Odoo ShipBlu"),
            ("manual_external", "Manual / External"),
            ("imported", "Imported"),
        ],
        copy=False,
    )
    shipblu_raw_status = fields.Char(related="shipblu_shipment_id.raw_status")
    shipblu_normalized_status = fields.Selection(
        related="shipblu_shipment_id.normalized_status",
        selection=NORMALIZED,
    )
    shipblu_business_reference = fields.Char(related="shipblu_shipment_id.business_reference")
    shipblu_tracking_url = fields.Char(related="shipblu_shipment_id.tracking_url")

    def _compute_shipblu_shipment(self):
        for picking in self:
            picking.shipblu_shipment_id = picking.shipblu_shipment_ids[:1]

    def action_shipblu_create_shipment(self):
        service = ShipmentService(self.env)
        for picking in self:
            service.create_from_picking(picking)
        return True

    def action_shipblu_refresh_status(self):
        for picking in self:
            shipment = picking.shipblu_shipment_id
            if not shipment:
                raise UserError(_("No ShipBlu shipment on this transfer."))
            shipment.action_refresh_status()
        return True

    def action_shipblu_request_pickup(self):
        for picking in self:
            shipment = picking.shipblu_shipment_id
            if not shipment:
                raise UserError(_("No ShipBlu shipment on this transfer."))
            shipment.action_request_pickup()
        return True
