# -*- coding: utf-8 -*-
"""WhatsApp Work Inbox triage, context window, and audit events."""
from __future__ import annotations

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

INBOX_STATES = [
    ("untriaged", "Not in Inbox"),
    ("new", "New"),
    ("pending", "Pending"),
    ("ignored", "Ignored"),
    ("actioned", "Actioned"),
]

ACTIVE_INBOX = ("new", "pending")
MEANINGFUL_RESTORE = ("new", "pending", "actioned")


class DevWhatsappInboxEvent(models.Model):
    _name = "dev.whatsapp.inbox.event"
    _description = "WhatsApp Work Inbox Event"
    _order = "id desc"

    message_id = fields.Many2one(
        "whatsapp.message", required=True, ondelete="cascade", index=True
    )
    event_type = fields.Selection(
        [
            ("add_to_inbox", "Add to Inbox"),
            ("ignore", "Ignore"),
            ("restore", "Restore"),
            ("pending", "Pending"),
            ("actioned", "Actioned"),
            ("set_new", "Set New"),
            ("work_created", "Work Created"),
            ("work_linked", "Work Linked"),
            ("additional_work", "Additional Work Created"),
            ("ai_ignore", "AI Ignore Applied"),
            ("ai_work_created", "AI Work Created"),
            ("ai_work_attached", "AI Work Attached"),
        ],
        required=True,
        index=True,
    )
    from_state = fields.Char()
    to_state = fields.Char()
    note = fields.Char()
    user_id = fields.Many2one("res.users", default=lambda self: self.env.user, required=True)
    work_item_id = fields.Many2one("dev.work.item", ondelete="set null")


class WhatsappMessageWorkInbox(models.Model):
    _inherit = "whatsapp.message"

    inbox_state = fields.Selection(
        INBOX_STATES,
        default="untriaged",
        required=True,
        index=True,
        copy=False,
    )
    previous_inbox_state = fields.Selection(INBOX_STATES, copy=False)
    work_item_ids = fields.Many2many(
        "dev.work.item",
        string="Linked Work Items",
        compute="_compute_work_links",
        search="_search_work_item_ids",
    )
    work_item_count = fields.Integer(compute="_compute_work_links")
    has_work_item = fields.Boolean(compute="_compute_work_links")
    primary_work_item_id = fields.Many2one(
        "dev.work.item", compute="_compute_work_links", string="Primary Work Item"
    )
    primary_work_phase = fields.Char(compute="_compute_work_links")

    def _compute_work_links(self):
        Source = self.env["dev.work.source.message"].sudo()
        by_msg = {mid: self.env["dev.work.item"] for mid in self.ids}
        if self.ids:
            for src in Source.search([("whatsapp_message_id", "in", self.ids)]):
                by_msg[src.whatsapp_message_id.id] |= src.work_item_ids
        for rec in self:
            works = by_msg.get(rec.id, self.env["dev.work.item"])
            # Also include intake-linked work for legacy rows without FK yet
            if "dh_work_item_id" in rec._fields and rec.dh_work_item_id:
                works |= rec.dh_work_item_id
            rec.work_item_ids = works
            rec.work_item_count = len(works)
            rec.has_work_item = bool(works)
            primary = works[:1]
            rec.primary_work_item_id = primary
            rec.primary_work_phase = primary.current_phase if primary else False

    def _search_work_item_ids(self, operator, value):
        Source = self.env["dev.work.source.message"].sudo()
        if operator in ("=", "in") and value:
            works = self.env["dev.work.item"].browse(
                value if isinstance(value, list) else [value]
            ).exists()
            msg_ids = Source.search(
                [("work_item_ids", "in", works.ids)]
            ).mapped("whatsapp_message_id").ids
            return [("id", "in", msg_ids)]
        if operator in ("!=",) and not value:
            linked = Source.search(
                [("whatsapp_message_id", "!=", False)]
            ).mapped("whatsapp_message_id").ids
            return [("id", "not in", linked)] if linked else []
        return [("id", "=", 0)]

    @api.model_create_multi
    def create(self, vals_list):
        admit = bool(self.env.context.get("whatsapp_inbox_admit_new"))
        for vals in vals_list:
            if "inbox_state" not in vals:
                vals["inbox_state"] = "new" if admit else "untriaged"
        return super().create(vals_list)

    @api.model
    def service_ingest_normalized(self, payload):
        """Admit only newly created Hub rows into Inbox as new; never reset triage on dedupe."""
        return super(
            WhatsappMessageWorkInbox, self.with_context(whatsapp_inbox_admit_new=True)
        ).service_ingest_normalized(payload)

    def _inbox_require_triage_user(self):
        """Work Inbox is a Dev Hub triage surface over Chatwoot/Hub messages.

        Operators only need Dev Hub User/Manager — not WhatsApp Hub User.
        Message read already comes from ``access_whatsapp_message_dh_*``.
        """
        if not (
            self.env.user.has_group("devhub_core.group_dev_hub_user")
            or self.env.user.has_group("devhub_core.group_dev_hub_manager")
            or self.env.user.has_group(
                "devhub_whatsapp.group_dev_hub_wa_analysis_service"
            )
        ):
            raise AccessError("Dev Hub user rights are required for Work Inbox triage.")

    def _inbox_log(self, event_type, from_state, to_state, note="", work=False):
        Event = self.env["dev.whatsapp.inbox.event"].sudo()
        for rec in self:
            Event.create(
                {
                    "message_id": rec.id,
                    "event_type": event_type,
                    "from_state": from_state or False,
                    "to_state": to_state or False,
                    "note": (note or "")[:200] or False,
                    "work_item_id": work.id if work else False,
                }
            )

    def _inbox_set_state(self, new_state, *, event_type, remember_previous=True, note=""):
        self._inbox_require_triage_user()
        if new_state not in dict(INBOX_STATES):
            raise ValidationError("Invalid inbox state: %s" % new_state)
        for rec in self:
            old = rec.inbox_state
            if old == new_state:
                continue
            vals = {"inbox_state": new_state}
            if remember_previous and old in MEANINGFUL_RESTORE:
                vals["previous_inbox_state"] = old
            if new_state == "ignored" and old in MEANINGFUL_RESTORE:
                vals["previous_inbox_state"] = old
            # Use sudo only for inbox field write after ACL gate (message ACL may be read-only for DH users).
            rec.sudo().write(vals)
            rec._inbox_log(event_type, old, new_state, note=note)
        return True

    def action_inbox_add(self):
        """Admit untriaged/historical messages into the Work Inbox as New."""
        self._inbox_require_triage_user()
        for rec in self:
            if rec.inbox_state == "untriaged":
                rec._inbox_set_state("new", event_type="add_to_inbox", remember_previous=False)
            elif rec.inbox_state == "ignored":
                rec.action_inbox_restore()
        return True

    def action_inbox_set_new(self):
        return self._inbox_set_state("new", event_type="set_new")

    def action_inbox_set_pending(self):
        return self._inbox_set_state("pending", event_type="pending")

    def action_inbox_set_actioned(self):
        return self._inbox_set_state("actioned", event_type="actioned")

    def action_inbox_ignore(self):
        return self._inbox_set_state("ignored", event_type="ignore")

    def action_inbox_restore(self):
        self._inbox_require_triage_user()
        for rec in self:
            if rec.inbox_state != "ignored":
                continue
            target = rec.previous_inbox_state or "new"
            if target not in MEANINGFUL_RESTORE:
                target = "new"
            old = rec.inbox_state
            rec.sudo().write({"inbox_state": target})
            rec._inbox_log("restore", old, target)
        return True

    def action_inbox_bulk_ignore(self):
        return self.action_inbox_ignore()

    def action_inbox_bulk_pending(self):
        return self.action_inbox_set_pending()

    def action_inbox_bulk_actioned(self):
        return self.action_inbox_set_actioned()

    def action_open_work_inbox(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "devhub_whatsapp_work_inbox",
            "name": "WhatsApp Work Inbox",
            "params": {
                "focus_message_id": self.id,
                "conversation_id": self.conversation_id.id,
                "highlight_message_ids": [self.id],
            },
        }

    def action_open_primary_work_item(self):
        self.ensure_one()
        work = self.primary_work_item_id
        if not work:
            raise UserError("No linked Work Item.")
        # Enforce normal record rules (no sudo browse for open)
        work = self.env["dev.work.item"].browse(work.id)
        work.check_access("read")
        return {
            "type": "ir.actions.act_window",
            "name": "Work Item",
            "res_model": "dev.work.item",
            "res_id": work.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    # ------------------------------------------------------------------
    # Work Inbox RPCs
    # ------------------------------------------------------------------

    @api.model
    def get_work_inbox_conversations(self, filters=None, limit=100):
        """Parent tree nodes: one row per WhatsApp group (or DM conversation)."""
        self._inbox_require_triage_user()
        filters = filters or {}
        limit = max(1, min(int(limit or 100), 100))
        domain = self._inbox_domain_from_filters(filters)
        messages = self.search(
            domain, order="message_timestamp desc, id desc", limit=5000
        )
        by_key = {}
        for msg in messages:
            cid = msg.conversation_id.id
            if not cid:
                continue
            # Collapse duplicate Hub conversations for the same @g.us group.
            # Prefer message.group_jid; fall back to conversation.remote_jid for groups.
            remote = (msg.conversation_id.remote_jid or "").strip()
            group_key = (msg.group_jid or "").strip()
            if not group_key and remote.endswith("@g.us"):
                group_key = remote
            key = group_key or ("dm:%s" % cid)
            bucket = by_key.get(key)
            if not bucket:
                by_key[key] = {
                    "key": key,
                    "conversation_id": cid,
                    "conversation_ids": {cid},
                    "group_jid": group_key,
                    "msg_count": 1,
                    "new_count": 1 if msg.inbox_state == "new" else 0,
                    "pending_count": 1 if msg.inbox_state == "pending" else 0,
                    "last_ts": msg.message_timestamp,
                    "last_id": msg.id,
                    "preview_msg": msg,
                }
                continue
            bucket["conversation_ids"].add(cid)
            bucket["msg_count"] += 1
            if msg.inbox_state == "new":
                bucket["new_count"] += 1
            elif msg.inbox_state == "pending":
                bucket["pending_count"] += 1
            if not bucket["group_jid"] and group_key:
                bucket["group_jid"] = group_key
        nodes = sorted(
            by_key.values(),
            key=lambda b: (
                b["last_ts"] or fields.Datetime.from_string("1970-01-01 00:00:00"),
                b["last_id"],
            ),
            reverse=True,
        )[:limit]
        rows = []
        for node in nodes:
            msg = node["preview_msg"]
            conv = msg.conversation_id
            group_name = (
                msg.group_id.name
                if msg.group_id
                else (conv.name if conv else msg.group_jid or "Conversation")
            )
            rows.append(
                {
                    "conversation_id": node["conversation_id"],
                    "conversation_ids": list(node["conversation_ids"]),
                    "name": group_name,
                    "conversation_type": conv.conversation_type if conv else "",
                    "group_jid": node["group_jid"],
                    "msg_count": node["msg_count"],
                    "new_count": node["new_count"],
                    "pending_count": node["pending_count"],
                    "last_message_timestamp": fields.Datetime.to_string(node["last_ts"])
                    if node["last_ts"]
                    else False,
                    "last_preview": (
                        (msg.body or "").replace("\n", " ")[:120] or "(empty)"
                    ),
                    "last_media_kind": msg.media_kind,
                    "last_message_id": node["last_id"],
                    "ai_state": False,
                    "ai_label": False,
                    "ai_analysis_id": False,
                }
            )
        # Enrich with latest AI analysis badges (group-level).
        jids = [r["group_jid"] for r in rows if r.get("group_jid")]
        if jids and "dev.whatsapp.analysis" in self.env:
            badges = self.env["dev.whatsapp.analysis"].get_ai_badges_for_groups(jids)
            for row in rows:
                info = badges.get(row.get("group_jid") or "", {})
                if info:
                    row["ai_state"] = info.get("ai_state") or False
                    row["ai_label"] = info.get("ai_label") or False
                    row["ai_analysis_id"] = info.get("ai_analysis_id") or False
        return {
            "conversations": rows,
            "counters": self.get_work_inbox_counters(filters),
        }

    @api.model
    def get_work_inbox_rows(self, filters=None, cursor=None, limit=50):
        self._inbox_require_triage_user()
        filters = filters or {}
        limit = max(1, min(int(limit or 50), 50))
        domain = self._inbox_domain_from_filters(filters)
        if cursor:
            # cursor = (timestamp_iso, id) load older than this (desc inbox)
            ts, mid = cursor
            domain = domain + [
                "|",
                ("message_timestamp", "<", ts),
                "&",
                ("message_timestamp", "=", ts),
                ("id", "<", int(mid)),
            ]
        rows = self.search(domain, order="message_timestamp desc, id desc", limit=limit)
        return {
            "rows": [self._inbox_row_payload(m) for m in rows],
            "next_cursor": (
                [
                    fields.Datetime.to_string(rows[-1].message_timestamp),
                    rows[-1].id,
                ]
                if len(rows) == limit
                else False
            ),
            "counters": self.get_work_inbox_counters(filters),
        }

    @api.model
    def get_work_inbox_counters(self, filters=None):
        self._inbox_require_triage_user()
        filters = dict(filters or {})
        # Counters follow date range only (not inbox_state), so chips stay meaningful.
        date_filters = {
            k: filters[k]
            for k in ("date_from", "date_to")
            if filters.get(k)
        }
        base = []
        if date_filters.get("date_from"):
            base.append(("message_timestamp", ">=", date_filters["date_from"]))
        if date_filters.get("date_to"):
            base.append(("message_timestamp", "<=", date_filters["date_to"]))
        Message = self
        return {
            "new": Message.search_count(base + [("inbox_state", "=", "new")]),
            "pending": Message.search_count(base + [("inbox_state", "=", "pending")]),
            "ignored": Message.search_count(base + [("inbox_state", "=", "ignored")]),
            "actioned": Message.search_count(base + [("inbox_state", "=", "actioned")]),
            "untriaged": Message.search_count(
                base + [("inbox_state", "=", "untriaged")]
            ),
            "default": Message.search_count(
                base + [("inbox_state", "in", list(ACTIVE_INBOX))]
            ),
        }

    @api.model
    def _inbox_domain_from_filters(self, filters):
        state = filters.get("inbox_state") or "default"
        if state == "default":
            domain = [("inbox_state", "in", list(ACTIVE_INBOX))]
        elif state == "all":
            domain = []
        else:
            domain = [("inbox_state", "=", state)]
        if filters.get("has_media") is True:
            domain.append(("has_media", "=", True))
        if filters.get("has_media") is False:
            domain.append(("has_media", "=", False))
        if filters.get("conversation_type") == "group":
            domain.append(("group_jid", "!=", False))
        if filters.get("conversation_type") == "dm":
            domain += ["|", ("group_jid", "=", False), ("group_jid", "=", "")]
        if filters.get("conversation_id"):
            domain.append(("conversation_id", "=", int(filters["conversation_id"])))
        if filters.get("conversation_ids"):
            ids = [int(x) for x in filters["conversation_ids"] if x]
            if ids:
                domain.append(("conversation_id", "in", ids))
        if filters.get("group_jid"):
            domain.append(("group_jid", "=", filters["group_jid"]))
        if filters.get("sender_jid"):
            domain.append(("sender_jid", "ilike", filters["sender_jid"]))
        if filters.get("date_from"):
            domain.append(("message_timestamp", ">=", filters["date_from"]))
        if filters.get("date_to"):
            domain.append(("message_timestamp", "<=", filters["date_to"]))
        if filters.get("search"):
            domain.append(("body", "ilike", filters["search"]))
        return domain

    def _inbox_row_payload(self, msg):
        group_name = msg.group_id.name if msg.group_id else (msg.group_jid or "")
        # Prefer human sender label for tree children (avoid repeating group name).
        sender_label = msg.sender_jid or (
            "me" if msg.direction == "out" else (group_name or "unknown")
        )
        return {
            "id": msg.id,
            "body_preview": ((msg.body or "").replace("\n", " ")[:220] or "(empty)"),
            "message_timestamp": fields.Datetime.to_string(msg.message_timestamp)
            if msg.message_timestamp
            else False,
            "direction": msg.direction,
            "sender_jid": msg.sender_jid or "",
            "sender_label": sender_label,
            "group_jid": msg.group_jid or "",
            "group_name": group_name,
            "conversation_id": msg.conversation_id.id,
            "conversation_type": msg.conversation_id.conversation_type
            if msg.conversation_id
            else "",
            "inbox_state": msg.inbox_state,
            "media_kind": msg.media_kind,
            "has_media": msg.has_media,
            "has_work_item": msg.has_work_item,
            "work_item_count": msg.work_item_count,
            "primary_work_item_id": msg.primary_work_item_id.id or False,
            "primary_work_name": msg.primary_work_item_id.name
            if msg.primary_work_item_id
            else False,
            "primary_work_phase": msg.primary_work_phase or False,
        }

    @api.model
    def get_inbox_context(self, message_id, before=20, after=20):
        """Bounded window: before + focus + after (same conversation)."""
        self._inbox_require_triage_user()
        before = max(0, min(int(before or 20), 20))
        after = max(0, min(int(after or 20), 20))
        focus = self.browse(int(message_id)).exists()
        if not focus:
            raise UserError("Message not found.")
        focus.check_access("read")
        conv = focus.conversation_id
        ts = focus.message_timestamp or fields.Datetime.now()
        older = self.search(
            [
                ("conversation_id", "=", conv.id),
                "|",
                ("message_timestamp", "<", ts),
                "&",
                ("message_timestamp", "=", ts),
                ("id", "<", focus.id),
            ],
            order="message_timestamp desc, id desc",
            limit=before,
        )
        newer = self.search(
            [
                ("conversation_id", "=", conv.id),
                "|",
                ("message_timestamp", ">", ts),
                "&",
                ("message_timestamp", "=", ts),
                ("id", ">", focus.id),
            ],
            order="message_timestamp asc, id asc",
            limit=after,
        )
        # chronological: older(reversed) + focus + newer
        ordered = list(reversed(list(older))) + [focus] + list(newer)
        return {
            "focus_message_id": focus.id,
            "conversation_id": conv.id,
            "conversation_name": conv.name,
            "conversation_type": conv.conversation_type,
            "messages": [self._context_bubble(m) for m in ordered],
            "has_older": len(older) == before,
            "has_newer": len(newer) == after,
            "older_cursor": (
                [
                    fields.Datetime.to_string(older[-1].message_timestamp),
                    older[-1].id,
                ]
                if older
                else False
            ),
            "newer_cursor": (
                [
                    fields.Datetime.to_string(newer[-1].message_timestamp),
                    newer[-1].id,
                ]
                if newer
                else False
            ),
        }

    @api.model
    def load_inbox_context_older(self, conversation_id, cursor, limit=20):
        self._inbox_require_triage_user()
        limit = max(1, min(int(limit or 20), 20))
        ts, mid = cursor
        rows = self.search(
            [
                ("conversation_id", "=", int(conversation_id)),
                "|",
                ("message_timestamp", "<", ts),
                "&",
                ("message_timestamp", "=", ts),
                ("id", "<", int(mid)),
            ],
            order="message_timestamp desc, id desc",
            limit=limit,
        )
        ordered = list(reversed(list(rows)))
        return {
            "messages": [self._context_bubble(m) for m in ordered],
            "has_older": len(rows) == limit,
            "older_cursor": (
                [
                    fields.Datetime.to_string(rows[-1].message_timestamp),
                    rows[-1].id,
                ]
                if rows
                else False
            ),
        }

    @api.model
    def load_inbox_context_newer(self, conversation_id, cursor, limit=20):
        self._inbox_require_triage_user()
        limit = max(1, min(int(limit or 20), 20))
        ts, mid = cursor
        rows = self.search(
            [
                ("conversation_id", "=", int(conversation_id)),
                "|",
                ("message_timestamp", ">", ts),
                "&",
                ("message_timestamp", "=", ts),
                ("id", ">", int(mid)),
            ],
            order="message_timestamp asc, id asc",
            limit=limit,
        )
        return {
            "messages": [self._context_bubble(m) for m in rows],
            "has_newer": len(rows) == limit,
            "newer_cursor": (
                [
                    fields.Datetime.to_string(rows[-1].message_timestamp),
                    rows[-1].id,
                ]
                if rows
                else False
            ),
        }

    def _context_bubble(self, msg):
        return {
            "id": msg.id,
            "direction": msg.direction,
            "body": msg.body or "",
            "message_timestamp": fields.Datetime.to_string(msg.message_timestamp)
            if msg.message_timestamp
            else False,
            "sender_jid": msg.sender_jid or "",
            "group_jid": msg.group_jid or "",
            "inbox_state": msg.inbox_state,
            "media_kind": msg.media_kind,
            "has_media": msg.has_media,
            "attachment_references": (msg.attachment_references or "")[:300],
            "has_work_item": msg.has_work_item,
            "work_item_count": msg.work_item_count,
            "primary_work_item_id": msg.primary_work_item_id.id or False,
            "primary_work_name": msg.primary_work_item_id.name
            if msg.primary_work_item_id
            else False,
            "primary_work_phase": msg.primary_work_phase or False,
        }

    def action_open_create_work_wizard(self):
        """Open review wizard for selected Hub message(s)."""
        self._inbox_require_triage_user()
        if not self:
            raise UserError("Select at least one message.")
        conv_ids = set(self.mapped("conversation_id").ids)
        if len(conv_ids) != 1:
            raise UserError(
                "Select messages from the same conversation only."
            )
        return {
            "type": "ir.actions.act_window",
            "name": "Create Dev Hub Work",
            "res_model": "dev.whatsapp.create.work.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_message_ids": [(6, 0, self.ids)],
                "default_primary_message_id": self.sorted(
                    lambda m: (m.message_timestamp or fields.Datetime.now(), m.id)
                )[:1].id,
            },
        }
