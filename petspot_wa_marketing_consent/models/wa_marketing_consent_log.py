# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


class PetspotWaMarketingConsentLog(models.Model):
    """Append-only audit history for WhatsApp marketing consent."""

    _name = "petspot.wa.marketing.consent.log"
    _description = "WhatsApp Marketing Consent Audit Log"
    _order = "create_date desc, id desc"
    _rec_name = "display_name"

    consent_id = fields.Many2one(
        "petspot.wa.marketing.consent",
        string="Consent Record",
        required=True,
        index=True,
        ondelete="restrict",
    )
    partner_id = fields.Many2one("res.partner", index=True, ondelete="restrict")
    mobile_normalized = fields.Char(index=True)
    channel = fields.Char()
    purpose = fields.Char()
    status = fields.Char(index=True)
    event_type = fields.Selection(
        [("create", "Create"), ("write", "Write"), ("system", "System")],
        default="write",
        required=True,
    )
    consent_source = fields.Char()
    wording_version = fields.Char()
    wording_text = fields.Text()
    evidence_ref = fields.Char()
    captured_by = fields.Many2one("res.users")
    ip_address = fields.Char()
    user_agent = fields.Char()
    revoked_timestamp = fields.Datetime()
    revocation_source = fields.Char()
    notes = fields.Text()
    payload_snapshot = fields.Text()
    display_name = fields.Char(compute="_compute_display_name")

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.mobile_normalized} / {rec.status} @ {rec.create_date}"

    def unlink(self):
        raise UserError(self.env._("Consent audit log entries cannot be deleted."))

    def write(self, vals):
        # Allow only notes correction by admin? Fail closed — no edits.
        raise UserError(self.env._("Consent audit log entries are immutable."))
