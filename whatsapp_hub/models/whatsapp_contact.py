# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models


class WhatsappContact(models.Model):
    _name = "whatsapp.contact"
    _description = "WhatsApp Contact"
    _order = "name, id"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    jid = fields.Char(
        string="WhatsApp JID",
        index=True,
        help="e.g. 201000000000@s.whatsapp.net",
    )
    phone_e164 = fields.Char(string="Phone (E.164-ish)", index=True)
    partner_id = fields.Many2one("res.partner", ondelete="set null", index=True)
    push_name = fields.Char()

    _jid_unique = models.UniqueIndex(
        "(jid) WHERE jid IS NOT NULL",
        "WhatsApp contact JID must be unique when set.",
    )

    @api.model
    def _normalize_phone(self, phone_or_jid):
        raw = (phone_or_jid or "").strip()
        if "@" in raw:
            raw = raw.split("@", 1)[0]
        digits = re.sub(r"\D", "", raw)
        return digits or False

    @api.model
    def get_or_create_from_sender(self, sender_jid=None, phone=None, name=None):
        jid = (sender_jid or "").strip() or False
        phone_e164 = self._normalize_phone(phone or jid)
        contact = self.browse()
        if jid:
            contact = self.search([("jid", "=", jid)], limit=1)
        if not contact and phone_e164:
            contact = self.search([("phone_e164", "=", phone_e164)], limit=1)
        vals = {
            "name": name or jid or phone_e164 or "Unknown",
            "jid": jid,
            "phone_e164": phone_e164,
            "push_name": name or False,
        }
        if contact:
            updates = {k: v for k, v in vals.items() if v and not contact[k]}
            if updates:
                contact.write(updates)
            return contact
        return self.create(vals)
