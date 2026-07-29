# -*- coding: utf-8 -*-
from odoo import fields, models


class ShipBluReturnOrder(models.Model):
    _name = "shipblu.return.order"
    _description = "ShipBlu Return Order"
    _order = "id desc"

    name = fields.Char(required=True)
    backend_id = fields.Many2one("shipblu.backend", required=True, ondelete="cascade")
    company_id = fields.Many2one("res.company", required=True, index=True)
    shipblu_return_id = fields.Char(required=True, index=True)
    tracking_number = fields.Char(index=True)
    raw_status = fields.Char()
    payload_json = fields.Text()

    _shipblu_return_uniq = models.Constraint(
        "unique(shipblu_return_id)",
        "Return already imported.",
    )


class ShipBluExchangeOrder(models.Model):
    _name = "shipblu.exchange.order"
    _description = "ShipBlu Exchange Order"
    _order = "id desc"

    name = fields.Char(required=True)
    backend_id = fields.Many2one("shipblu.backend", required=True, ondelete="cascade")
    company_id = fields.Many2one("res.company", required=True, index=True)
    shipblu_exchange_id = fields.Char(required=True, index=True)
    tracking_number = fields.Char(index=True)
    raw_status = fields.Char()
    payload_json = fields.Text()

    _shipblu_exchange_uniq = models.Constraint(
        "unique(shipblu_exchange_id)",
        "Exchange already imported.",
    )


class ShipBluCashCollection(models.Model):
    _name = "shipblu.cash.collection"
    _description = "ShipBlu Cash Collection"
    _order = "id desc"

    name = fields.Char(required=True)
    backend_id = fields.Many2one("shipblu.backend", required=True, ondelete="cascade")
    company_id = fields.Many2one("res.company", required=True, index=True)
    shipblu_cc_id = fields.Char(required=True, index=True)
    tracking_number = fields.Char(index=True)
    raw_status = fields.Char()
    payload_json = fields.Text()

    _shipblu_cc_uniq = models.Constraint(
        "unique(shipblu_cc_id)",
        "Cash collection already imported.",
    )
