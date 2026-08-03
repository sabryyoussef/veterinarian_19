# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


def normalize_eg_mobile(raw):
    """Return E.164 +20… Egyptian mobile or empty string. Never guess incomplete numbers."""
    if not raw:
        return ""
    digits = re.sub(r"\D", "", str(raw))
    if digits.startswith("0020"):
        digits = digits[4:]
    elif digits.startswith("20") and len(digits) >= 11:
        digits = digits[2:]
    if len(digits) == 10 and digits.startswith("1"):
        digits = "0" + digits
    if len(digits) == 11 and digits.startswith("01") and digits[2] in "0125":
        return "+20" + digits[1:]
    return ""


class PetspotWaMarketingConsent(models.Model):
    """Current consent state per normalized mobile + channel + purpose.

    History is preserved in petspot.wa.marketing.consent.log (append-only).
    Tags / transactions / operational messages never create consent.
    """

    _name = "petspot.wa.marketing.consent"
    _description = "WhatsApp Marketing Consent"
    _order = "write_date desc, id desc"
    _rec_name = "display_name"

    partner_id = fields.Many2one(
        "res.partner",
        string="Partner",
        required=True,
        index=True,
        ondelete="restrict",
    )
    mobile_normalized = fields.Char(
        string="Normalized Mobile",
        required=True,
        index=True,
        help="E.164 Egyptian mobile (+20…).",
    )
    mobile_raw = fields.Char(string="Original Mobile")
    channel = fields.Selection(
        [("whatsapp", "WhatsApp")],
        string="Channel",
        required=True,
        default="whatsapp",
        index=True,
    )
    purpose = fields.Selection(
        [("marketing", "Marketing")],
        string="Purpose",
        required=True,
        default="marketing",
        index=True,
    )
    status = fields.Selection(
        [
            ("pending", "Pending"),
            ("opted_in", "Opted In"),
            ("opted_out", "Opted Out"),
            ("wrong_number", "Wrong Number"),
            ("revoked", "Revoked"),
        ],
        string="Status",
        required=True,
        default="pending",
        index=True,
    )
    consent_timestamp = fields.Datetime(string="Consent Timestamp", index=True)
    consent_source = fields.Selection(
        [
            ("clinic_form", "Clinic Form"),
            ("shopify", "Shopify"),
            ("qr_landing_page", "QR / Landing Page"),
            ("staff_recorded", "Staff Recorded"),
            ("whatsapp_inbound", "WhatsApp Inbound"),
            ("import_with_evidence", "Import With Evidence"),
        ],
        string="Consent Source",
    )
    wording_id = fields.Many2one(
        "petspot.wa.consent.wording",
        string="Consent Wording Version",
        ondelete="restrict",
    )
    wording_version = fields.Char(string="Wording Version", index=True)
    wording_text = fields.Text(string="Exact Consent Wording")
    evidence_ref = fields.Char(string="Evidence / Reference")
    captured_by = fields.Many2one("res.users", string="Captured By", default=lambda self: self.env.user)
    ip_address = fields.Char(string="IP Address")
    user_agent = fields.Char(string="User Agent")
    revoked_timestamp = fields.Datetime(string="Revoked Timestamp")
    revocation_source = fields.Char(string="Revocation Source")
    notes = fields.Text(string="Notes")
    staff_explicit_confirm = fields.Boolean(
        string="Staff Confirmed Explicit Agreement",
        help="Required for staff_recorded source: customer explicitly agreed.",
    )
    last_marketing_contact_at = fields.Datetime(
        string="Last Marketing Contact At",
        help="Filled by future marketing queue only — not operational messages.",
    )
    active_for_eligibility = fields.Boolean(
        string="Active Opt-In",
        compute="_compute_active_for_eligibility",
        store=True,
        index=True,
    )
    log_ids = fields.One2many(
        "petspot.wa.marketing.consent.log",
        "consent_id",
        string="Audit Log",
        readonly=True,
    )
    display_name = fields.Char(compute="_compute_display_name", store=True)

    _sql_constraints = [
        (
            "uniq_mobile_channel_purpose",
            "unique(mobile_normalized, channel, purpose)",
            "Only one consent state record is allowed per mobile, channel and purpose.",
        ),
    ]

    @api.depends("partner_id", "mobile_normalized", "status")
    def _compute_display_name(self):
        for rec in self:
            name = rec.partner_id.display_name or "Partner"
            rec.display_name = f"{name} / {rec.mobile_normalized or '?'} / {rec.status}"

    @api.depends("status")
    def _compute_active_for_eligibility(self):
        for rec in self:
            rec.active_for_eligibility = rec.status == "opted_in"

    @api.model
    def normalize_mobile(self, raw):
        return normalize_eg_mobile(raw)

    @api.constrains("mobile_normalized")
    def _check_mobile_normalized(self):
        for rec in self:
            if not rec.mobile_normalized or not rec.mobile_normalized.startswith("+20"):
                raise ValidationError(
                    self.env._("Normalized mobile must be a valid Egyptian E.164 number (+20…).")
                )
            if normalize_eg_mobile(rec.mobile_normalized) != rec.mobile_normalized:
                raise ValidationError(self.env._("Invalid Egyptian mobile format."))

    @api.constrains("status", "consent_source", "staff_explicit_confirm", "wording_text")
    def _check_opt_in_requirements(self):
        for rec in self:
            if rec.status != "opted_in":
                continue
            if not rec.consent_source:
                raise ValidationError(self.env._("Opt-in requires a consent source."))
            if not rec.wording_text and not rec.wording_id:
                raise ValidationError(self.env._("Opt-in requires exact consent wording."))
            if rec.consent_source == "staff_recorded" and not rec.staff_explicit_confirm:
                raise ValidationError(
                    self.env._(
                        "Staff-recorded consent requires confirmation that the customer explicitly agreed."
                    )
                )
            if not rec.consent_timestamp:
                raise ValidationError(self.env._("Opt-in requires a consent timestamp."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            raw = vals.get("mobile_raw") or vals.get("mobile_normalized")
            if raw and not vals.get("mobile_normalized"):
                vals["mobile_normalized"] = normalize_eg_mobile(raw)
            if vals.get("status") == "opted_in" and not vals.get("consent_timestamp"):
                vals["consent_timestamp"] = fields.Datetime.now()
            if vals.get("wording_id") and not vals.get("wording_text"):
                wording = self.env["petspot.wa.consent.wording"].browse(vals["wording_id"])
                vals["wording_version"] = wording.version
                vals["wording_text"] = wording.body_ar or wording.body_en
        records = super().create(vals_list)
        for rec in records:
            rec._append_log("create", note="Consent record created")
        return records

    def write(self, vals):
        # Opt-out / wrong_number / revoked immediately clear eligibility
        if vals.get("status") in ("opted_out", "wrong_number", "revoked"):
            vals.setdefault("revoked_timestamp", fields.Datetime.now())
            if vals["status"] == "opted_out" and not vals.get("revocation_source"):
                vals["revocation_source"] = vals.get("revocation_source") or "unspecified"
        if vals.get("status") == "opted_in" and "consent_timestamp" not in vals:
            vals["consent_timestamp"] = fields.Datetime.now()
        before = {rec.id: rec.status for rec in self}
        res = super().write(vals)
        for rec in self:
            rec._append_log(
                "write",
                note=f"Status {before.get(rec.id)} → {rec.status}",
                extra=vals,
            )
        return res

    def unlink(self):
        raise UserError(
            self.env._(
                "Consent audit records cannot be deleted. Change status to revoked/opted_out instead."
            )
        )

    def _append_log(self, event_type, note="", extra=None):
        Log = self.env["petspot.wa.marketing.consent.log"].sudo()
        for rec in self:
            Log.create(
                {
                    "consent_id": rec.id,
                    "partner_id": rec.partner_id.id,
                    "mobile_normalized": rec.mobile_normalized,
                    "channel": rec.channel,
                    "purpose": rec.purpose,
                    "status": rec.status,
                    "event_type": event_type,
                    "consent_source": rec.consent_source,
                    "wording_version": rec.wording_version,
                    "wording_text": rec.wording_text,
                    "evidence_ref": rec.evidence_ref,
                    "captured_by": rec.captured_by.id if rec.captured_by else False,
                    "ip_address": rec.ip_address,
                    "user_agent": rec.user_agent,
                    "revoked_timestamp": rec.revoked_timestamp,
                    "revocation_source": rec.revocation_source,
                    "notes": note or rec.notes,
                    "payload_snapshot": str(extra or {})[:2000],
                }
            )

    def action_opt_out(self, source="manual", notes=""):
        for rec in self:
            rec.write(
                {
                    "status": "opted_out",
                    "revocation_source": source,
                    "revoked_timestamp": fields.Datetime.now(),
                    "notes": notes or rec.notes,
                }
            )
        return True

    def action_mark_wrong_number(self, source="manual", notes=""):
        for rec in self:
            rec.write(
                {
                    "status": "wrong_number",
                    "revocation_source": source,
                    "revoked_timestamp": fields.Datetime.now(),
                    "notes": notes or rec.notes,
                }
            )
        return True

    @api.model
    def register_inbound_opt_out_keyword(self, mobile_raw, keyword, partner=None):
        """Handle وقف / stop / unsubscribe / إلغاء — fail-closed, immediate."""
        mobile = normalize_eg_mobile(mobile_raw)
        if not mobile:
            raise UserError(self.env._("Cannot process opt-out: invalid Egyptian mobile."))
        consent = self.search(
            [
                ("mobile_normalized", "=", mobile),
                ("channel", "=", "whatsapp"),
                ("purpose", "=", "marketing"),
            ],
            limit=1,
        )
        vals = {
            "status": "opted_out",
            "revocation_source": f"whatsapp_inbound:{keyword}",
            "revoked_timestamp": fields.Datetime.now(),
            "notes": f"Inbound keyword opt-out: {keyword}",
            "mobile_normalized": mobile,
            "mobile_raw": mobile_raw,
            "channel": "whatsapp",
            "purpose": "marketing",
            "partner_id": partner.id if partner else (consent.partner_id.id if consent else False),
        }
        if not vals["partner_id"]:
            # Create placeholder partner only if none — prefer existing by phone
            partner = self.env["res.partner"].search(
                ["|", ("phone", "ilike", mobile[-9:]), ("phone_sanitized", "ilike", mobile[-9:])],
                limit=1,
            )
            if not partner:
                raise UserError(
                    self.env._(
                        "Opt-out keyword received but no partner matched. Create/link partner first."
                    )
                )
            vals["partner_id"] = partner.id
        if consent:
            consent.write(vals)
            return consent
        return self.create(vals)
