# -*- coding: utf-8 -*-
"""Bilingual customer-facing message templates (Phase 15B — mock transport only)."""

from __future__ import annotations

from odoo import api, fields, models
from odoo.exceptions import UserError

TEMPLATE_KEYS = [
    ("supplier_available", "Supplier available"),
    ("revised_product_price", "Revised product price"),
    ("delivery_charge_revision", "Delivery charge revision"),
    ("unavailable", "Unavailable"),
    ("checking", "Checking"),
    ("quotation_ready", "Quotation ready"),
    ("quotation_expired", "Quotation expired"),
    ("payment_received", "Payment received"),
    ("ready_for_pickup", "Ready for pickup"),
    ("tracking_issued", "Tracking issued"),
    ("manual_review_required", "Manual review required"),
]


class PetspotVetutionMessageTemplate(models.Model):
    _name = "petspot.vetution.message.template"
    _description = "Vetution Customer Message Template (bilingual)"
    _order = "key, lang"

    name = fields.Char(compute="_compute_name", store=True)
    key = fields.Selection(TEMPLATE_KEYS, required=True, index=True)
    lang = fields.Selection(
        [("en", "English"), ("ar", "Arabic")], required=True, default="en", index=True
    )
    body_text = fields.Text(
        required=True,
        help="Use {sku} {price} {tracking} {eta} {order} placeholders as needed.",
    )
    channel = fields.Selection(
        [("chatwoot", "Chatwoot")], default="chatwoot", required=True
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "petspot_msg_template_key_lang_channel_uniq",
            "unique(key, lang, channel)",
            "A template already exists for this key/language/channel.",
        ),
    ]

    @api.depends("key", "lang", "channel")
    def _compute_name(self):
        for rec in self:
            rec.name = f"{rec.key}/{rec.lang}/{rec.channel}"

    @api.model
    def render(self, key, lang, context_dict=None):
        """Return rendered body for key/lang (fallback to 'en'). Never raises
        for missing placeholders — unresolved ones are left as-is so gaps are
        visible in the mock transport log instead of silently failing.
        """
        ctx = dict(context_dict or {})
        tmpl = self.search(
            [("key", "=", key), ("lang", "=", lang), ("active", "=", True)], limit=1
        )
        if not tmpl and lang != "en":
            tmpl = self.search(
                [("key", "=", key), ("lang", "=", "en"), ("active", "=", True)], limit=1
            )
        if not tmpl:
            raise UserError(f"No active message template for key={key} lang={lang}.")
        body = tmpl.body_text
        try:
            return body.format(**ctx)
        except (KeyError, IndexError):
            # Missing placeholder — return unformatted body rather than fail
            # a mock send; the gap is visible in the message log payload.
            return body
