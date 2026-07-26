# -*- coding: utf-8 -*-
"""Notify-me / Available-on-request records (supplier-backed, not warehouse qty)."""

from odoo import api, fields, models


class PetspotShopNotify(models.Model):
    _name = "petspot.shop.notify"
    _description = "PetSpot Shop Availability Request"
    _order = "create_date desc"

    name = fields.Char(compute="_compute_name", store=True)
    partner_id = fields.Many2one("res.partner", string="Customer")
    email = fields.Char(required=True)
    product_tmpl_id = fields.Many2one("product.template", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", ondelete="cascade")
    request_type = fields.Selection(
        [
            ("notify", "Notify Me (OOS)"),
            ("request", "Available on Request"),
            ("contact", "Contact for Price"),
        ],
        required=True,
        default="notify",
    )
    note = fields.Text()
    state = fields.Selection(
        [("pending", "Pending"), ("contacted", "Contacted"), ("done", "Done"), ("cancel", "Cancelled")],
        default="pending",
        required=True,
    )
    website_id = fields.Many2one("website")

    @api.depends("partner_id", "email", "product_tmpl_id", "request_type")
    def _compute_name(self):
        for rec in self:
            rec.name = f"{rec.request_type}: {rec.product_tmpl_id.display_name} / {rec.email}"
