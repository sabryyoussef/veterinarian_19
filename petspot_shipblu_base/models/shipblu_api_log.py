# -*- coding: utf-8 -*-
from odoo import fields, models


class ShipBluApiLog(models.Model):
    _name = "shipblu.api.log"
    _description = "ShipBlu API Audit Log"
    _order = "create_date desc, id desc"

    backend_id = fields.Many2one("shipblu.backend", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one("res.company", required=True, index=True)
    method = fields.Char(required=True)
    url = fields.Char(required=True)
    http_status = fields.Integer()
    duration_ms = fields.Integer()
    request_headers = fields.Text()
    request_body = fields.Text()
    response_body = fields.Text()
    error_message = fields.Char()
