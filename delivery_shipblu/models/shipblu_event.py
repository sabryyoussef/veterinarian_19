# -*- coding: utf-8 -*-
from odoo import fields, models


class ShipBluShipmentEvent(models.Model):
    _name = "shipblu.shipment.event"
    _description = "ShipBlu Tracking Event"
    _order = "event_at desc, id desc"

    shipment_id = fields.Many2one("shipblu.shipment", required=True, ondelete="cascade", index=True)
    event_code = fields.Char(index=True)
    event_label = fields.Char()
    event_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    payload_json = fields.Text()
