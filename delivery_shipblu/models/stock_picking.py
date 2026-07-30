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
    shipblu_canonical_key = fields.Char(copy=False, index=True)
    shipblu_duplicate_guard_status = fields.Selection(
        [
            ("unchecked", "Unchecked"),
            ("checking", "Checking"),
            ("clear", "Clear to create"),
            ("creating", "Creating"),
            ("created", "Created"),
            ("reconciled", "Reconciled existing"),
            ("verification_required", "Verification Required"),
            ("blocked", "Blocked"),
            ("error", "Error"),
        ],
        copy=False,
        index=True,
    )
    shipblu_duplicate_detection_source = fields.Selection(
        [
            ("local_awb", "Local AWB"),
            ("imported_delivery", "Imported delivery"),
            ("shopify_fulfillment", "Shopify fulfillment"),
            ("remote_reference", "Remote merchant reference"),
            ("remote_awb", "Remote AWB"),
            ("verification_required", "Verification required"),
        ],
        copy=False,
    )

    def _compute_shipblu_shipment(self):
        for picking in self:
            picking.shipblu_shipment_id = picking.shipblu_shipment_ids[:1]

    def action_shipblu_create_shipment(self):
        service = ShipmentService(self.env)
        messages = []
        for picking in self:
            shipment = service.create_from_picking(picking)
            if shipment.env.context.get("shipblu_reconciled"):
                messages.append(
                    shipment.env.context.get("shipblu_guard_message")
                    or _("Existing ShipBlu AWB found and linked; no new delivery was created.")
                )
            else:
                messages.append(
                    _("ShipBlu delivery created — AWB %(awb)s")
                    % {"awb": shipment.tracking_number or shipment.shipblu_order_id or shipment.name}
                )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("ShipBlu"),
                "message": "\n".join(messages),
                "type": "warning" if any("Existing" in m for m in messages) else "success",
                "sticky": False,
            },
        }

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
