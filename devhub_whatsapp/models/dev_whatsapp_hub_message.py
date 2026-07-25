# -*- coding: utf-8 -*-
"""Browse WhatsApp Hub messages from DH WhatsApp + send to next Dev Hub steps."""
from __future__ import annotations

import json

from odoo import api, fields, models
from odoo.exceptions import UserError


class WhatsappMessageDevHub(models.Model):
    _inherit = "whatsapp.message"

    dh_attachment_ids = fields.Many2many(
        "ir.attachment",
        string="Attachments",
        compute="_compute_dh_attachments",
        help="Files linked to this Hub message (and refs listed in attachment_references).",
    )
    dh_has_attachment = fields.Boolean(compute="_compute_dh_attachments")
    dh_source_id = fields.Many2one(
        "dev.whatsapp.source",
        string="DH Whitelist Source",
        compute="_compute_dh_source",
        search="_search_dh_source",
        store=True,
        index=True,
    )
    dh_intake_id = fields.Many2one(
        "dev.whatsapp.intake",
        string="DH Intake",
        compute="_compute_dh_links",
        search="_search_dh_intake",
    )
    dh_work_item_id = fields.Many2one(
        "dev.work.item",
        string="DH Work Item",
        compute="_compute_dh_links",
    )

    @api.depends("attachment_references")
    def _compute_dh_attachments(self):
        Attachment = self.env["ir.attachment"].sudo()
        for rec in self:
            atts = Attachment.search(
                [("res_model", "=", "whatsapp.message"), ("res_id", "=", rec.id)]
            )
            extra_ids = []
            raw = (rec.attachment_references or "").strip()
            if raw:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        for item in parsed:
                            if isinstance(item, int):
                                extra_ids.append(item)
                            elif isinstance(item, dict):
                                aid = item.get("attachment_id") or item.get("id")
                                if aid:
                                    extra_ids.append(int(aid))
                            elif isinstance(item, str) and item.isdigit():
                                extra_ids.append(int(item))
                except (json.JSONDecodeError, TypeError, ValueError):
                    for part in raw.replace(";", ",").split(","):
                        part = part.strip()
                        if part.isdigit():
                            extra_ids.append(int(part))
            if extra_ids:
                atts |= Attachment.browse(extra_ids).exists()
            rec.dh_attachment_ids = atts
            rec.dh_has_attachment = bool(atts) or bool(raw)

    @api.depends("group_jid")
    def _compute_dh_source(self):
        Source = self.env["dev.whatsapp.source"].sudo()
        by_jid = {
            s.group_jid: s
            for s in Source.search([("active", "=", True), ("group_jid", "!=", False)])
        }
        for rec in self:
            rec.dh_source_id = by_jid.get(rec.group_jid) if rec.group_jid else False

    def _search_dh_source(self, operator, value):
        Source = self.env["dev.whatsapp.source"].sudo()
        if operator in ("=", "in") and value:
            ids = (
                list(value)
                if operator == "in" and not isinstance(value, (str, int))
                else [value]
            )
            sources = Source.browse(ids).exists()
            jids = sources.mapped("group_jid")
            return [("group_jid", "in", jids)]
        if operator in ("!=", "not in") and not value:
            jids = Source.search([("active", "=", True)]).mapped("group_jid")
            return [("group_jid", "in", jids)] if jids else [("id", "=", 0)]
        if operator == "!=" and value:
            ids = list(value) if not isinstance(value, (str, int)) else [value]
            sources = Source.browse(ids).exists()
            jids = sources.mapped("group_jid")
            return ["!", ("group_jid", "in", jids)] if jids else []
        return [("id", "=", 0)]

    def _search_dh_intake(self, operator, value):
        Intake = self.env["dev.whatsapp.intake"].sudo()
        if operator in ("!=",) and not value:
            ids = Intake.search([("whatsapp_message_id", "!=", False)]).mapped(
                "whatsapp_message_id"
            ).ids
            return [("id", "in", ids)] if ids else [("id", "=", 0)]
        if operator in ("=",) and not value:
            ids = Intake.search([("whatsapp_message_id", "!=", False)]).mapped(
                "whatsapp_message_id"
            ).ids
            return [("id", "not in", ids)] if ids else []
        return [("id", "=", 0)]

    def _compute_dh_links(self):
        Intake = self.env["dev.whatsapp.intake"].sudo()
        SourceMsg = self.env["dev.work.source.message"].sudo()
        for rec in self:
            intake = Intake.search([("whatsapp_message_id", "=", rec.id)], limit=1)
            if not intake and rec.group_jid:
                intake = Intake.search(
                    [
                        ("group_jid", "=", rec.group_jid),
                        ("state", "not in", ["rejected", "abandoned"]),
                    ],
                    order="id desc",
                    limit=1,
                )
            rec.dh_intake_id = intake
            work = intake.work_item_id if intake else self.env["dev.work.item"]
            if not work:
                sm = SourceMsg.browse()
                if rec.evolution_message_id:
                    sm = SourceMsg.search(
                        [("evolution_message_id", "=", rec.evolution_message_id)], limit=1
                    )
                if not sm and rec.chatwoot_message_id:
                    sm = SourceMsg.search(
                        [("chatwoot_message_id", "=", rec.chatwoot_message_id)], limit=1
                    )
                if sm and sm.work_item_ids:
                    work = sm.work_item_ids[:1]
            rec.dh_work_item_id = work

    def _dh_require_source(self):
        missing = self.filtered(lambda m: not m.dh_source_id)
        if missing:
            raise UserError(
                "These messages are not on a DH whitelist source. "
                "Open DH WhatsApp → Sync whitelist from Hub, then retry.\n%s"
                % ", ".join((m.group_jid or str(m.id)) for m in missing[:8])
            )
        sources = self.mapped("dh_source_id")
        if len(sources) > 1:
            raise UserError(
                "Select messages from one WhatsApp group/source only "
                "(found %s sources)." % len(sources)
            )
        return sources

    def _dh_combined_text(self):
        parts = []
        for msg in self.sorted(lambda m: (m.message_timestamp or fields.Datetime.now(), m.id)):
            stamp = fields.Datetime.to_string(msg.message_timestamp) if msg.message_timestamp else ""
            who = msg.sender_jid or ("me" if msg.direction == "out" else "unknown")
            body = (msg.body or "").strip() or (
                "[attachment]" if msg.dh_has_attachment else "[empty]"
            )
            parts.append("[%s] %s: %s" % (stamp, who, body))
        return "\n\n".join(parts)

    def _dh_ensure_source_messages(self):
        """Map Hub messages → immutable dev.work.source.message rows."""
        SourceMsg = self.env["dev.work.source.message"].sudo()
        result = SourceMsg.browse()
        for msg in self.sorted(lambda m: (m.message_timestamp or fields.Datetime.now(), m.id)):
            text = (msg.body or "").strip()
            if not text:
                text = "[attachment]" if msg.dh_has_attachment else "[empty message]"
            if msg.chatwoot_message_id:
                provider = "chatwoot"
                provider_message_id = str(msg.chatwoot_message_id)
            elif msg.evolution_message_id or msg.provider_message_id:
                provider = "evolution"
                provider_message_id = str(
                    msg.evolution_message_id or msg.provider_message_id
                )
            else:
                provider = "manual"
                provider_message_id = "hub:%s" % msg.id
            domain = [
                ("provider", "=", provider),
                ("provider_message_id", "=", provider_message_id),
                ("extracted_item_index", "=", 0),
            ]
            if provider == "evolution" and msg.instance_reference:
                domain.append(("instance_reference", "=", msg.instance_reference))
            existing = SourceMsg.search(domain, limit=1)
            if existing:
                write_vals = {}
                if not existing.whatsapp_message_id:
                    write_vals["whatsapp_message_id"] = msg.id
                if not existing.source_url:
                    write_vals["source_url"] = (
                        "odoo://wa-work-inbox?focus_message_id=%s" % msg.id
                    )
                if write_vals:
                    existing.write(write_vals)
                result |= existing
                continue
            result |= SourceMsg.create(
                {
                    "provider": provider,
                    "instance_reference": msg.instance_reference or False,
                    "provider_message_id": provider_message_id,
                    "evolution_message_id": msg.evolution_message_id or False,
                    "group_jid": msg.group_jid or False,
                    "sender_jid": msg.sender_jid or False,
                    "chatwoot_account_id": msg.chatwoot_account_id or False,
                    "chatwoot_inbox_id": msg.chatwoot_inbox_id or False,
                    "chatwoot_conversation_id": msg.chatwoot_conversation_id or False,
                    "chatwoot_message_id": msg.chatwoot_message_id or False,
                    "message_timestamp": msg.message_timestamp or fields.Datetime.now(),
                    "text_snapshot": text[:6000],
                    "attachment_references": (msg.attachment_references or "")[:4000]
                    or False,
                    "whatsapp_message_id": msg.id,
                    "source_url": "odoo://wa-work-inbox?focus_message_id=%s" % msg.id,
                }
            )
        return result

    def _dh_title(self, prefix="WhatsApp"):
        source = self.mapped("dh_source_id")[:1]
        group_name = source.name if source else (self[:1].group_jid or "group")
        first = next(
            ((m.body or "").strip() for m in self if (m.body or "").strip()),
            "",
        )
        if first:
            snippet = first.replace("\n", " ")[:80]
            return ("%s · %s: %s" % (prefix, group_name, snippet))[:200]
        return ("%s · %s (%s msgs)" % (prefix, group_name, len(self)))[:200]

    def _dh_open(self, model, res_id, name):
        return {
            "type": "ir.actions.act_window",
            "name": name,
            "res_model": model,
            "res_id": res_id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    def action_dh_send_to_intake(self):
        """Create / extend a DH intake candidate from one or many Hub messages."""
        return self._dh_send_to_intake(merge_open=True)

    def _dh_send_to_intake(self, merge_open=True):
        """Create DH intake from Hub messages. merge_open=False → always new intake."""
        if not self:
            raise UserError("Select at least one message.")
        source = self._dh_require_source()
        source_msgs = self._dh_ensure_source_messages()
        Intake = self.env["dev.whatsapp.intake"].sudo()
        primary = self.sorted(
            lambda m: (m.message_timestamp or fields.Datetime.now(), m.id), reverse=True
        )[:1]
        intake = Intake.browse()
        if merge_open:
            intake = Intake.search(
                [
                    ("source_id", "=", source.id),
                    (
                        "state",
                        "in",
                        ["received", "collecting", "draft_ready", "awaiting_confirm"],
                    ),
                    ("group_jid", "=", source.group_jid),
                ],
                order="id desc",
                limit=1,
            )
        combined = self._dh_combined_text()
        vals = {
            "name": self._dh_title("Intake"),
            "source_id": source.id,
            "state": "draft_ready",
            "classification": "new_dev_request",
            "group_jid": source.group_jid,
            "primary_sender_jid": primary.sender_jid or False,
            "draft_summary": combined[:4000],
            "draft_problem": combined[:4000],
            "source_message_ids": [(6, 0, source_msgs.ids)],
            "whatsapp_message_id": primary.id,
            "last_message_at": primary.message_timestamp or fields.Datetime.now(),
            "chatwoot_conversation_id": primary.chatwoot_conversation_id or False,
            "chatwoot_inbox_id": primary.chatwoot_inbox_id or source.chatwoot_inbox_id or False,
            "chatwoot_account_id": primary.chatwoot_account_id or False,
        }
        if intake:
            intake.write(
                {
                    "source_message_ids": [(4, mid) for mid in source_msgs.ids],
                    "draft_summary": combined[:4000],
                    "draft_problem": combined[:4000],
                    "whatsapp_message_id": primary.id,
                    "last_message_at": primary.message_timestamp or fields.Datetime.now(),
                    "state": "draft_ready" if intake.state == "received" else intake.state,
                }
            )
            intake._audit("hub_messages_appended", "hub_ids=%s" % self.ids)
        else:
            intake = Intake.create(vals)
            intake._audit("created_from_hub", "hub_ids=%s" % self.ids)
        return self._dh_open("dev.whatsapp.intake", intake.id, "WhatsApp Intake")

    def action_dh_create_work_item(self):
        """Create a Dev Hub work item from selected Hub message(s)."""
        if not self:
            raise UserError("Select at least one message.")
        source = self._dh_require_source()
        if not source.odoo_project_id:
            raise UserError(
                "Configure an Odoo Project on WhatsApp source '%s' first." % source.name
            )
        source_msgs = self._dh_ensure_source_messages()
        Work = self.env["dev.work.item"]
        work = Work.create(
            {
                "name": self._dh_title("WA"),
                "dev_project_id": source.dev_project_id.id,
                "odoo_project_id": source.odoo_project_id.id,
                "preferred_environment_id": source.default_environment_id.id or False,
                "preferred_repository_id": source.default_repository_id.id or False,
                "source_message_ids": [(6, 0, source_msgs.ids)],
            }
        )
        # Link open intake if any
        Intake = self.env["dev.whatsapp.intake"].sudo()
        primary = self[:1]
        intake = Intake.search(
            [
                ("source_id", "=", source.id),
                ("whatsapp_message_id", "in", self.ids),
                ("work_item_id", "=", False),
                ("state", "not in", ["rejected", "abandoned", "merged"]),
            ],
            limit=1,
        )
        if not intake:
            intake = Intake.search(
                [
                    ("source_id", "=", source.id),
                    ("state", "in", ["received", "collecting", "draft_ready", "awaiting_confirm"]),
                ],
                order="id desc",
                limit=1,
            )
        if intake and not intake.work_item_id:
            intake.write(
                {
                    "work_item_id": work.id,
                    "state": "confirmed",
                    "source_message_ids": [(4, mid) for mid in source_msgs.ids],
                    "whatsapp_message_id": primary.id,
                }
            )
            intake._audit("confirmed_from_hub", "work_item_id=%s" % work.id)
        return self._dh_open("dev.work.item", work.id, "Work Item")

    def action_dh_send_to_analysis(self):
        """Create work item + seed a draft analysis from selected Hub message(s)."""
        if "dev.work.analysis" not in self.env:
            raise UserError("Install Dev Hub Analysis (devhub_analysis) first.")
        action = self.action_dh_create_work_item()
        work = self.env["dev.work.item"].browse(action["res_id"])
        # Advance as far as governance allows (OP-backed registration may block).
        try:
            if work.current_phase == "received":
                work.action_triage()
        except UserError:
            pass
        try:
            if work.current_phase == "triage" and work.odoo_task_id:
                work.action_register()
            if work.current_phase == "registered":
                work.action_start_analysis()
        except UserError:
            # Keep work item usable; analysis draft is still created below.
            pass
        combined = self._dh_combined_text()
        summary = (combined[:1500] or self._dh_title("Analysis")).strip()
        Analysis = self.env["dev.work.analysis"].sudo()
        analysis = Analysis.search(
            [("work_item_id", "=", work.id)], order="revision desc", limit=1
        )
        if not analysis:
            analysis = Analysis.create(
                {
                    "work_item_id": work.id,
                    "status": "draft",
                    "origin": "manual",
                    "problem_summary": summary,
                    "original_request_summary": combined[:4000] or summary,
                    "evidence_references": "Hub message ids: %s" % ", ".join(map(str, self.ids)),
                    "repository_id": work.preferred_repository_id.id or False,
                }
            )
        return self._dh_open("dev.work.analysis", analysis.id, "Analysis")
