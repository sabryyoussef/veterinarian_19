# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models

from .wa_marketing_consent import normalize_eg_mobile

# Tags that permanently exclude marketing eligibility (by name; resolved at runtime).
EXCLUDED_TAG_NAMES = (
    "WorldPosta Contact",
    "Palm Hills",
    "New Giza",
    "Marketing Lead",
    "Employee",
)


class PetspotWaMarketingEligibility(models.TransientModel):
    """Fail-closed eligibility engine for WhatsApp marketing (TEST/UAT helper)."""

    _name = "petspot.wa.marketing.eligibility"
    _description = "WhatsApp Marketing Eligibility Check"

    partner_id = fields.Many2one("res.partner", required=True)
    eligible = fields.Boolean(readonly=True)
    reason = fields.Text(readonly=True)
    mobile_normalized = fields.Char(readonly=True)

    @api.model
    def evaluate_partner(self, partner):
        """Return dict: eligible, reason, mobile_normalized. Fail closed on ambiguity.

        ``partner`` may be a res.partner recordset or an integer id (XML-RPC friendly).
        """
        if isinstance(partner, int):
            partner = self.env["res.partner"].browse(partner)
        partner = partner.sudo()
        reasons = []

        if not partner or not partner.exists():
            return {"eligible": False, "reason": "missing_partner", "mobile_normalized": ""}

        if partner.is_company:
            return {"eligible": False, "reason": "company_only", "mobile_normalized": ""}

        if getattr(partner, "employee", False):
            return {"eligible": False, "reason": "employee", "mobile_normalized": ""}

        tag_names = set(partner.category_id.mapped("name"))
        hit = [n for n in EXCLUDED_TAG_NAMES if n in tag_names]
        if hit:
            return {
                "eligible": False,
                "reason": f"excluded_tags:{','.join(hit)}",
                "mobile_normalized": "",
            }

        mobile = normalize_eg_mobile(partner.phone_sanitized or partner.phone)
        if not mobile:
            return {"eligible": False, "reason": "invalid_or_missing_eg_mobile", "mobile_normalized": ""}

        # Duplicate phone across partners → ambiguous → fail closed
        Partner = self.env["res.partner"].sudo()
        local = "0" + mobile[3:]
        candidates = Partner.search(
            ["|", ("phone", "ilike", local[-9:]), ("phone_sanitized", "ilike", local[-9:])],
            limit=40,
        )
        owners = [
            p.id
            for p in candidates
            if normalize_eg_mobile(p.phone_sanitized or p.phone) == mobile
        ]
        if len(set(owners)) > 1:
            return {
                "eligible": False,
                "reason": f"duplicate_mobile_ambiguous:{sorted(set(owners))}",
                "mobile_normalized": mobile,
            }

        Consent = self.env["petspot.wa.marketing.consent"].sudo()
        consent = Consent.search(
            [
                ("mobile_normalized", "=", mobile),
                ("channel", "=", "whatsapp"),
                ("purpose", "=", "marketing"),
            ],
            limit=1,
        )
        if not consent:
            return {"eligible": False, "reason": "no_consent_record", "mobile_normalized": mobile}
        if consent.status == "opted_out":
            return {"eligible": False, "reason": "opted_out", "mobile_normalized": mobile}
        if consent.status == "wrong_number":
            return {"eligible": False, "reason": "wrong_number", "mobile_normalized": mobile}
        if consent.status == "revoked":
            return {"eligible": False, "reason": "revoked", "mobile_normalized": mobile}
        if consent.status == "pending":
            return {"eligible": False, "reason": "consent_pending", "mobile_normalized": mobile}
        if consent.status != "opted_in":
            return {
                "eligible": False,
                "reason": f"consent_status:{consent.status}",
                "mobile_normalized": mobile,
            }
        # Explicit opted_in required — no inference
        if not consent.consent_source or not (consent.wording_text or consent.wording_id):
            return {
                "eligible": False,
                "reason": "opt_in_missing_source_or_wording",
                "mobile_normalized": mobile,
            }

        if consent.last_marketing_contact_at:
            delta = fields.Datetime.now() - consent.last_marketing_contact_at
            if delta < timedelta(days=14):
                return {
                    "eligible": False,
                    "reason": "contacted_within_14_days",
                    "mobile_normalized": mobile,
                }

        if partner.is_blacklisted or partner.phone_blacklisted:
            return {"eligible": False, "reason": "blacklisted", "mobile_normalized": mobile}

        return {
            "eligible": True,
            "reason": "explicit_whatsapp_marketing_opt_in",
            "mobile_normalized": mobile,
            "consent_id": consent.id,
        }

    @api.model
    def action_evaluate(self, partner_id):
        partner = self.env["res.partner"].browse(partner_id)
        result = self.evaluate_partner(partner)
        return self.create(
            {
                "partner_id": partner.id,
                "eligible": result["eligible"],
                "reason": result["reason"],
                "mobile_normalized": result.get("mobile_normalized") or "",
            }
        )
