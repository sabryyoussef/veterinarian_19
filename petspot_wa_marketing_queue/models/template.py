# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from .settings import OPT_OUT_PHRASE

ALLOWED_PLACEHOLDERS = ("{first_name}", "{url}")


class PetspotWaMarketingTemplate(models.Model):
    _name = "petspot.wa.marketing.template"
    _description = "WhatsApp Marketing Message Template"
    _order = "id desc"

    name = fields.Char(required=True)
    version = fields.Char(required=True, index=True)
    state = fields.Selection(
        [("draft", "Draft"), ("approved", "Approved"), ("retired", "Retired")],
        default="draft",
        required=True,
        index=True,
    )
    body_ar = fields.Text(string="Arabic Body", required=True)
    url = fields.Char(string="Optional CTA URL")
    approved_by = fields.Many2one("res.users", readonly=True)
    approved_at = fields.Datetime(readonly=True)
    active = fields.Boolean(default=True)

    @api.constrains("body_ar")
    def _check_body(self):
        for rec in self:
            body = rec.body_ar or ""
            if OPT_OUT_PHRASE not in body:
                raise ValidationError(
                    self.env._("Template must include exact opt-out phrase: %s") % OPT_OUT_PHRASE
                )
            # Controlled placeholders only
            found = set(re.findall(r"\{[a-z_]+\}", body))
            bad = found - set(ALLOWED_PLACEHOLDERS)
            if bad:
                raise ValidationError(
                    self.env._("Unsupported placeholders: %s") % ", ".join(sorted(bad))
                )
            # crude medical/drug claim blocklist
            lowered = body.lower()
            banned = (
                "دواء",
                "prescription",
                "apoquel",
                "simparica",
                "antibiotics",
                "مضاد حيوي",
            )
            if any(b in lowered or b in body for b in banned):
                raise ValidationError(
                    self.env._("Template must not promote prescription medicines or veterinary drugs.")
                )

    def action_approve(self):
        for rec in self:
            if rec.state == "retired":
                raise UserError(self.env._("Cannot approve a retired template."))
            rec.write(
                {
                    "state": "approved",
                    "approved_by": self.env.user.id,
                    "approved_at": fields.Datetime.now(),
                }
            )

    def action_retire(self):
        self.write({"state": "retired", "active": False})

    @api.model
    def _safe_first_name(self, partner):
        """Return a personal first name, or False when unreliable (use أهلاً بيك fallback)."""
        if not partner or not partner.exists():
            return False
        raw = (partner.name or "").strip()
        if not raw:
            return False
        first = raw.split()[0].strip()
        if len(first) < 2:
            return False
        if re.search(r"\d", first):
            return False
        upper = first.upper()
        blocked = (
            "UAT",
            "SYNTH",
            "TEST",
            "CUSTOMER",
            "PARTNER",
            "UNKNOWN",
            "CLIENT",
            "USER",
            "ADMIN",
            "DO-NOT",
            "DONOT",
        )
        if any(b in upper for b in blocked):
            return False
        return first

    def render_body(self, partner):
        self.ensure_one()
        first = self._safe_first_name(partner)
        # Unreliable → "بيك" so "أهلاً {first_name} 👋" becomes "أهلاً بيك 👋"
        greeting_name = first if first else "بيك"
        body = self.body_ar or ""
        body = body.replace("{first_name}", greeting_name)
        body = body.replace("{url}", self.url or "")
        return body
