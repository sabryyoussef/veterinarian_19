# -*- coding: utf-8 -*-
from odoo import fields, models

from .wa_marketing_consent import normalize_eg_mobile


class ResPartner(models.Model):
    _inherit = "res.partner"

    wa_marketing_consent_ids = fields.One2many(
        "petspot.wa.marketing.consent",
        "partner_id",
        string="WhatsApp Marketing Consents",
    )
    wa_marketing_opt_in = fields.Boolean(
        string="WA Marketing Opt-In (computed)",
        compute="_compute_wa_marketing_opt_in",
        help="True only when an explicit WhatsApp marketing opt-in exists. Never inferred from tags.",
    )

    def _compute_wa_marketing_opt_in(self):
        Consent = self.env["petspot.wa.marketing.consent"]
        for partner in self:
            mobile = normalize_eg_mobile(partner.phone_sanitized or partner.phone)
            if not mobile:
                partner.wa_marketing_opt_in = False
                continue
            consent = Consent.search(
                [
                    ("mobile_normalized", "=", mobile),
                    ("channel", "=", "whatsapp"),
                    ("purpose", "=", "marketing"),
                    ("status", "=", "opted_in"),
                ],
                limit=1,
            )
            partner.wa_marketing_opt_in = bool(consent)

    def action_open_staff_wa_consent_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Record WhatsApp Marketing Consent",
            "res_model": "petspot.wa.staff.consent.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_partner_id": self.id},
        }

    def action_check_wa_marketing_eligibility(self):
        self.ensure_one()
        result = self.env["petspot.wa.marketing.eligibility"].evaluate_partner(self)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "WhatsApp marketing eligibility",
                "message": f"{'ELIGIBLE' if result['eligible'] else 'BLOCKED'}: {result['reason']}",
                "type": "success" if result["eligible"] else "warning",
                "sticky": True,
            },
        }
