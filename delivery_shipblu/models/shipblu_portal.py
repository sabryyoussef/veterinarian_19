# -*- coding: utf-8 -*-
"""ShipBlu portal mirrors — pickup points, return points, drop-off hubs."""

from odoo import fields, models


class ShipBluPickupPoint(models.Model):
    _name = "shipblu.pickup.point"
    _description = "ShipBlu Pickup Point"
    _order = "is_default desc, id"

    name = fields.Char(required=True)
    backend_id = fields.Many2one("shipblu.backend", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one("res.company", required=True, index=True)
    shipblu_id = fields.Integer(required=True, index=True)
    is_default = fields.Boolean(default=False, index=True)
    nickname = fields.Char()
    line_1 = fields.Char()
    line_2 = fields.Char()
    zone_id = fields.Integer(string="ShipBlu Zone ID")
    zone_name = fields.Char()
    what3words = fields.Char()
    payload_json = fields.Text()

    _shipblu_pickup_uniq = models.Constraint(
        "unique(backend_id, shipblu_id)",
        "Pickup point already synced.",
    )


class ShipBluReturnPoint(models.Model):
    _name = "shipblu.return.point"
    _description = "ShipBlu Return Point"
    _order = "is_default desc, id"

    name = fields.Char(required=True)
    backend_id = fields.Many2one("shipblu.backend", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one("res.company", required=True, index=True)
    shipblu_id = fields.Integer(required=True, index=True)
    is_default = fields.Boolean(default=False, index=True)
    nickname = fields.Char()
    line_1 = fields.Char()
    line_2 = fields.Char()
    zone_id = fields.Integer(string="ShipBlu Zone ID")
    payload_json = fields.Text()

    _shipblu_return_point_uniq = models.Constraint(
        "unique(backend_id, shipblu_id)",
        "Return point already synced.",
    )


class ShipBluWarehouse(models.Model):
    _name = "shipblu.warehouse"
    _description = "ShipBlu Hub / Drop-off Location"
    _order = "name"

    name = fields.Char(required=True)
    backend_id = fields.Many2one("shipblu.backend", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one("res.company", required=True, index=True)
    shipblu_id = fields.Integer(required=True, index=True)
    code = fields.Char()
    address = fields.Char()
    latitude = fields.Float(digits=(10, 6))
    longitude = fields.Float(digits=(10, 6))
    is_virtual = fields.Boolean()
    payload_json = fields.Text()

    _shipblu_warehouse_uniq = models.Constraint(
        "unique(backend_id, shipblu_id)",
        "Warehouse already synced.",
    )
