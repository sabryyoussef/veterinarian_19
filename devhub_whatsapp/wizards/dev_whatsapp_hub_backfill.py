# -*- coding: utf-8 -*-
"""Backfill Hub message history into Dev Hub with filters."""
from __future__ import annotations

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.osv import expression


class DevWhatsappHubBackfillWizard(models.TransientModel):
    _name = "dev.whatsapp.hub.backfill.wizard"
    _description = "Backfill Hub Messages → Dev Hub"

    date_from = fields.Datetime(string="From")
    date_to = fields.Datetime(string="To")
    source_ids = fields.Many2many(
        "dev.whatsapp.source",
        string="DH Sources (groups)",
        domain=[("active", "=", True)],
        help="Limit to these whitelist sources. Empty = all active whitelist groups.",
    )
    group_jid = fields.Char(
        string="Group JID",
        help="Optional exact/partial group JID filter (…@g.us).",
    )
    sender_jid = fields.Char(
        string="Sender",
        help="Filter by sender JID (partial match).",
    )
    mention_text = fields.Char(
        string="Mention / text contains",
        help="Body must contain this text (e.g. @sabry or a keyword).",
    )
    only_with_mention = fields.Boolean(
        string="Only messages with @mention",
        help="Require '@' in the message body (Hub has no structured mention field).",
    )
    include_group_chats = fields.Boolean(
        string="Include group chats",
        default=True,
        help="Messages with a group JID (sent to a group).",
    )
    include_dm_chats = fields.Boolean(
        string="Include 1:1 / DM chats",
        default=False,
        help="Also include messages without a group JID.",
    )
    direction = fields.Selection(
        [
            ("all", "All directions"),
            ("in", "Inbound only"),
            ("out", "Outbound only"),
        ],
        default="in",
        required=True,
    )
    skip_already_linked = fields.Boolean(
        string="Skip already linked to Intake",
        default=True,
    )
    limit = fields.Integer(
        string="Max messages",
        default=200,
        required=True,
        help="Safety cap (1–1000).",
    )
    mode = fields.Selection(
        [
            ("preview", "Preview matching Hub messages"),
            ("intake_per_message", "Create one Intake per message"),
            ("intake_per_group", "One Intake per group (batch)"),
        ],
        default="preview",
        required=True,
    )
    match_count = fields.Integer(string="Matches", readonly=True)
    result_summary = fields.Text(string="Last result", readonly=True)

    @api.onchange(
        "date_from",
        "date_to",
        "source_ids",
        "group_jid",
        "sender_jid",
        "mention_text",
        "only_with_mention",
        "include_group_chats",
        "include_dm_chats",
        "direction",
        "skip_already_linked",
        "limit",
    )
    def _onchange_recount(self):
        try:
            self.match_count = len(self._search_hub_messages())
        except Exception:
            # Never break the wizard form on filter edits.
            self.match_count = 0

    def _whitelist_jids(self):
        Source = self.env["dev.whatsapp.source"].sudo()
        if self.source_ids:
            return [j for j in self.source_ids.mapped("group_jid") if j]
        return [
            j
            for j in Source.search([("active", "=", True)]).mapped("group_jid")
            if j
        ]

    def _build_domain(self):
        self.ensure_one()
        if not self.include_group_chats and not self.include_dm_chats:
            raise UserError("Enable Include group chats and/or Include 1:1 / DM chats.")

        domain = []
        if self.date_from:
            domain.append(("message_timestamp", ">=", self.date_from))
        if self.date_to:
            domain.append(("message_timestamp", "<=", self.date_to))
        if self.direction in ("in", "out"):
            domain.append(("direction", "=", self.direction))
        if self.sender_jid:
            domain.append(("sender_jid", "ilike", self.sender_jid.strip()))
        if self.mention_text:
            domain.append(("body", "ilike", self.mention_text.strip()))
        if self.only_with_mention:
            domain.append(("body", "ilike", "%@%"))

        whitelist = self._whitelist_jids()
        group_jid_filter = (self.group_jid or "").strip()

        group_domain = [("group_jid", "!=", False)]
        if group_jid_filter:
            group_domain.append(("group_jid", "ilike", group_jid_filter))
        elif whitelist:
            group_domain.append(("group_jid", "in", list(whitelist)))

        dm_domain = ["|", ("group_jid", "=", False), ("group_jid", "=", "")]

        if self.include_group_chats and self.include_dm_chats:
            # OR(group_domain, dm_domain) + AND with filters above
            domain = expression.AND(
                [domain, expression.OR([group_domain, dm_domain])]
            )
        elif self.include_group_chats:
            domain = expression.AND([domain, group_domain]) if domain else group_domain
        else:
            domain = expression.AND([domain, dm_domain]) if domain else dm_domain
        return domain

    def _search_hub_messages(self):
        self.ensure_one()
        limit = max(1, min(int(self.limit or 200), 1000))
        Message = self.env["whatsapp.message"].sudo()
        domain = self._build_domain()
        messages = Message.search(
            domain,
            order="message_timestamp asc, id asc",
            limit=limit,
        )
        if self.skip_already_linked and messages:
            Intake = self.env["dev.whatsapp.intake"].sudo()
            linked = Intake.search(
                [("whatsapp_message_id", "in", messages.ids)]
            ).mapped("whatsapp_message_id")
            messages = messages - linked
        return messages

    def action_preview(self):
        self.ensure_one()
        messages = self._search_hub_messages()
        self.write(
            {
                "match_count": len(messages),
                "result_summary": "Preview: %s Hub message(s) match filters."
                % len(messages),
            }
        )
        return {
            "type": "ir.actions.act_window",
            "name": "Hub history (filtered)",
            "res_model": "whatsapp.message",
            "view_mode": "list,form",
            "domain": [("id", "in", messages.ids)] if messages else [("id", "=", 0)],
            "target": "current",
            "context": {"create": False},
        }

    def action_run(self):
        self.ensure_one()
        if self.mode == "preview":
            return self.action_preview()

        messages = self._search_hub_messages()
        if not messages:
            self.write(
                {
                    "match_count": 0,
                    "result_summary": "No matching Hub messages (or all already linked).",
                }
            )
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Hub backfill",
                    "message": "No matching messages to backfill.",
                    "type": "warning",
                    "sticky": False,
                },
            }

        created = 0
        skipped = 0
        opened = self.env["dev.whatsapp.intake"]

        if self.mode == "intake_per_message":
            for msg in messages:
                if not msg.dh_source_id:
                    skipped += 1
                    continue
                try:
                    action = msg._dh_send_to_intake(merge_open=False)
                    created += 1
                    if action.get("res_id"):
                        opened |= self.env["dev.whatsapp.intake"].browse(
                            action["res_id"]
                        )
                except UserError:
                    skipped += 1
        else:
            by_group = {}
            for msg in messages:
                key = msg.group_jid or False
                if not key or not msg.dh_source_id:
                    skipped += 1
                    continue
                by_group.setdefault(key, self.env["whatsapp.message"])
                by_group[key] |= msg
            for _jid, bundle in by_group.items():
                try:
                    action = bundle._dh_send_to_intake(merge_open=False)
                    created += 1
                    if action.get("res_id"):
                        opened |= self.env["dev.whatsapp.intake"].browse(
                            action["res_id"]
                        )
                except UserError:
                    skipped += 1

        summary = (
            "Backfill done: matched=%s, intakes_created=%s, skipped=%s"
            % (len(messages), created, skipped)
        )
        self.write({"match_count": len(messages), "result_summary": summary})

        if len(opened) == 1:
            return {
                "type": "ir.actions.act_window",
                "name": "WhatsApp Intake",
                "res_model": "dev.whatsapp.intake",
                "res_id": opened.id,
                "view_mode": "form",
                "target": "current",
            }
        return {
            "type": "ir.actions.act_window",
            "name": "WhatsApp Intake",
            "res_model": "dev.whatsapp.intake",
            "view_mode": "list,form",
            "domain": [("id", "in", opened.ids)] if opened else [("id", "=", 0)],
            "target": "current",
        }
