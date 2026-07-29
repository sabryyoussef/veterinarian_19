# -*- coding: utf-8 -*-
from odoo import fields, models


class ShipBluGovernorate(models.Model):
    _name = "shipblu.governorate"
    _description = "ShipBlu Governorate"
    _order = "name"

    name = fields.Char(required=True)
    code = fields.Char()
    shipblu_id = fields.Integer(required=True, index=True)
    company_id = fields.Many2one("res.company", required=True, index=True)
    backend_id = fields.Many2one("shipblu.backend", ondelete="cascade")

    _shipblu_gov_uniq = models.Constraint(
        "unique(company_id, shipblu_id)",
        "Governorate already synced.",
    )


class ShipBluCity(models.Model):
    _name = "shipblu.city"
    _description = "ShipBlu City"
    _order = "name"

    name = fields.Char(required=True)
    shipblu_id = fields.Integer(required=True, index=True)
    governorate_shipblu_id = fields.Integer(index=True)
    company_id = fields.Many2one("res.company", required=True, index=True)
    backend_id = fields.Many2one("shipblu.backend", ondelete="cascade")

    _shipblu_city_uniq = models.Constraint(
        "unique(company_id, shipblu_id)",
        "City already synced.",
    )


class ShipBluZone(models.Model):
    _name = "shipblu.zone"
    _description = "ShipBlu Zone"
    _order = "name"

    name = fields.Char(required=True)
    shipblu_id = fields.Integer(required=True, index=True)
    city_shipblu_id = fields.Integer(index=True)
    company_id = fields.Many2one("res.company", required=True, index=True)
    backend_id = fields.Many2one("shipblu.backend", ondelete="cascade")

    _shipblu_zone_uniq = models.Constraint(
        "unique(company_id, shipblu_id)",
        "Zone already synced.",
    )
