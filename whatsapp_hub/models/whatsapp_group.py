# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class WhatsappGroup(models.Model):
    _name = "whatsapp.group"
    _description = "WhatsApp Group"
    _order = "name, id"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    jid = fields.Char(
        string="Group JID",
        required=True,
        index=True,
        help="Stable WhatsApp group id ending with @g.us",
    )
    chatwoot_inbox_id = fields.Integer(index=True)
    chatwoot_label = fields.Char()
    instance_id = fields.Many2one("whatsapp.instance", ondelete="set null")
    conversation_ids = fields.One2many(
        "whatsapp.conversation", "group_id", string="Conversations"
    )
    message_count = fields.Integer(compute="_compute_message_count")
    notes = fields.Text()

    _jid_unique = models.Constraint(
        "unique(jid)",
        "Group JID must be unique.",
    )

    @api.constrains("jid")
    def _check_jid(self):
        for rec in self:
            jid = (rec.jid or "").strip()
            if not jid.endswith("@g.us"):
                raise ValidationError("Group JID must end with @g.us.")

    def _compute_message_count(self):
        Message = self.env["whatsapp.message"]
        for rec in self:
            rec.message_count = Message.search_count([("group_id", "=", rec.id)])

    @api.model
    def get_or_create_by_jid(self, jid, vals=None):
        jid = (jid or "").strip()
        if not jid:
            return self.browse()
        group = self.search([("jid", "=", jid)], limit=1)
        if group:
            if vals:
                group.write({k: v for k, v in (vals or {}).items() if v and not group[k]})
            return group
        create_vals = {"jid": jid, "name": (vals or {}).get("name") or jid}
        if vals:
            create_vals.update({k: v for k, v in vals.items() if k != "jid" and v})
        return self.create(create_vals)
