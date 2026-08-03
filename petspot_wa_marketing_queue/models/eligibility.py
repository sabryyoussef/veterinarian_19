# -*- coding: utf-8 -*-
from odoo import api, models

from odoo.addons.petspot_wa_marketing_consent.models.wa_marketing_consent import (
    normalize_eg_mobile,
)

EXCLUDE_NAME_MARKERS = (
    "DO NOT CONTACT",
    "DO NOT MARKET",
    "PHASE1",
    "PHASE2",
    "SYNTHETIC",
    "SABRY WIFE",
    "WA TEST",
    "INTERNAL TEST",
)


class PetspotWaMarketingQueueEligibility(models.AbstractModel):
    _name = "petspot.wa.marketing.queue.eligibility"
    _description = "Marketing Queue Eligibility Wrapper"

    @api.model
    def evaluate(
        self,
        partner,
        campaign=None,
        template=None,
        check_pause=True,
        check_instance=True,
        exclude_item=None,
    ):
        """Fail-closed eligibility for queue enqueue and pre-dispatch."""
        Settings = self.env["petspot.wa.marketing.settings"].sudo()
        settings = Settings.get_settings()

        if check_pause and settings.global_pause:
            return {"eligible": False, "reason": "global_pause_on", "mobile_normalized": ""}

        if campaign and campaign.state in ("paused", "cancelled"):
            return {"eligible": False, "reason": f"campaign_{campaign.state}", "mobile_normalized": ""}

        if isinstance(partner, int):
            partner = self.env["res.partner"].browse(partner)
        partner = partner.sudo()
        if not partner or not partner.exists():
            return {"eligible": False, "reason": "missing_partner", "mobile_normalized": ""}

        name_u = (partner.name or "").upper()
        if any(m in name_u for m in EXCLUDE_NAME_MARKERS):
            return {"eligible": False, "reason": "excluded_internal_or_donotcontact", "mobile_normalized": ""}

        base = self.env["petspot.wa.marketing.eligibility"].evaluate_partner(partner)
        if not base.get("eligible"):
            return base

        mobile = base.get("mobile_normalized") or ""
        if not mobile:
            return {"eligible": False, "reason": "invalid_or_missing_eg_mobile", "mobile_normalized": ""}

        # Campaign/template uniqueness (exclude the item currently being dispatched)
        if campaign and template:
            Item = self.env["petspot.wa.marketing.queue.item"].sudo()
            domain = [
                ("campaign_id", "=", campaign.id),
                ("template_version", "=", template.version),
                ("mobile_normalized", "=", mobile),
                ("state", "in", ("pending", "reserved", "sent", "uncertain")),
            ]
            if exclude_item:
                domain.append(("id", "!=", exclude_item.id if hasattr(exclude_item, "id") else int(exclude_item)))
            exists = Item.search_count(domain)
            if exists:
                return {
                    "eligible": False,
                    "reason": "already_queued_or_sent_this_campaign_template",
                    "mobile_normalized": mobile,
                }

        if check_instance:
            inst = (settings.evolution_instance or "").strip()
            if inst != "petspot-marketing":
                return {"eligible": False, "reason": "forbidden_or_missing_instance", "mobile_normalized": mobile}
            if not settings.mock_send:
                health = self.env["petspot.wa.marketing.evolution.client"].connection_state()
                if health.get("state") != "open":
                    return {
                        "eligible": False,
                        "reason": f"evolution_not_open:{health.get('state')}",
                        "mobile_normalized": mobile,
                    }

        return {
            "eligible": True,
            "reason": "eligible",
            "mobile_normalized": mobile,
            "consent_id": base.get("consent_id"),
        }

    @api.model
    def normalize_mobile(self, raw):
        return normalize_eg_mobile(raw)
