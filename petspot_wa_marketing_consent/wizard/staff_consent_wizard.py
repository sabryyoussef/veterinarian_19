# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError

from ..models.wa_marketing_consent import normalize_eg_mobile


class PetspotWaStaffConsentWizard(models.TransientModel):
    _name = "petspot.wa.staff.consent.wizard"
    _description = "Staff Record WhatsApp Marketing Consent"

    partner_id = fields.Many2one("res.partner", required=True)
    mobile_raw = fields.Char(string="Mobile", required=True)
    wording_id = fields.Many2one(
        "petspot.wa.consent.wording",
        string="Wording Version",
        required=True,
        domain=[("route", "in", ("clinic_form", "staff_recorded")), ("active", "=", True)],
    )
    wording_preview = fields.Text(related="wording_id.body_ar", readonly=True)
    customer_explicitly_agreed = fields.Boolean(
        string="I confirm the customer explicitly agreed to this WhatsApp marketing wording",
        required=True,
    )
    evidence_ref = fields.Char(string="Evidence / Reference")
    notes = fields.Text()

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        partner = self.env["res.partner"].browse(res.get("partner_id") or self.env.context.get("default_partner_id"))
        if partner:
            if "mobile_raw" in fields_list and not res.get("mobile_raw"):
                res["mobile_raw"] = partner.phone or partner.phone_sanitized or ""
        if "wording_id" in fields_list and not res.get("wording_id"):
            Wording = self.env["petspot.wa.consent.wording"]
            wording = Wording.search(
                [("version", "=", "staff_v1_1_approved"), ("active", "=", True)],
                limit=1,
            )
            if not wording:
                wording = Wording.search(
                    [("route", "=", "staff_recorded"), ("active", "=", True)],
                    order="id desc",
                    limit=1,
                )
            if not wording:
                wording = Wording.search(
                    [("route", "=", "clinic_form"), ("active", "=", True)],
                    order="id desc",
                    limit=1,
                )
            if wording:
                res["wording_id"] = wording.id
        return res

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        if self.partner_id:
            self.mobile_raw = self.partner_id.phone or self.partner_id.phone_sanitized or ""

    def action_confirm_opt_in(self):
        self.ensure_one()
        if not self.customer_explicitly_agreed:
            raise UserError(
                self.env._("You must confirm the customer explicitly agreed before recording consent.")
            )
        if self.partner_id.is_company:
            raise UserError(self.env._("Record consent on a person contact, not a company."))
        mobile = normalize_eg_mobile(self.mobile_raw)
        if not mobile:
            raise UserError(self.env._("Enter a valid Egyptian mobile number."))

        Consent = self.env["petspot.wa.marketing.consent"]
        existing = Consent.search(
            [
                ("mobile_normalized", "=", mobile),
                ("channel", "=", "whatsapp"),
                ("purpose", "=", "marketing"),
            ],
            limit=1,
        )
        vals = {
            "partner_id": self.partner_id.id,
            "mobile_normalized": mobile,
            "mobile_raw": self.mobile_raw,
            "channel": "whatsapp",
            "purpose": "marketing",
            "status": "opted_in",
            "consent_timestamp": fields.Datetime.now(),
            "consent_source": "staff_recorded",
            "wording_id": self.wording_id.id,
            "wording_version": self.wording_id.version,
            "wording_text": self.wording_id.body_ar,
            "evidence_ref": self.evidence_ref,
            "captured_by": self.env.user.id,
            "staff_explicit_confirm": True,
            "notes": self.notes,
        }
        if existing:
            if existing.status == "opted_out":
                # Staff may re-opt-in only with new explicit agreement (new write)
                pass
            existing.write(vals)
            consent = existing
        else:
            consent = Consent.create(vals)
        return {
            "type": "ir.actions.act_window",
            "res_model": "petspot.wa.marketing.consent",
            "res_id": consent.id,
            "view_mode": "form",
            "target": "current",
        }
