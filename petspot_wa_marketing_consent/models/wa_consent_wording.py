# -*- coding: utf-8 -*-
from odoo import fields, models


class PetspotWaConsentWording(models.Model):
    _name = "petspot.wa.consent.wording"
    _description = "WhatsApp Marketing Consent Wording Version"
    _order = "version desc"

    name = fields.Char(required=True)
    version = fields.Char(required=True, index=True)
    route = fields.Selection(
        [
            ("clinic_form", "Clinic Reception"),
            ("shopify", "Shopify"),
            ("qr_landing_page", "QR / Landing Page"),
            ("staff_recorded", "Staff Recorded"),
            ("whatsapp_inbound", "WhatsApp Inbound"),
        ],
        required=True,
    )
    body_ar = fields.Text(string="Arabic Wording", required=True)
    body_en = fields.Text(string="English Wording", required=True)
    active = fields.Boolean(default=True)
    effective_from = fields.Datetime(default=fields.Datetime.now)
