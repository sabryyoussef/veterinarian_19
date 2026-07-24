# -*- coding: utf-8 -*-
"""Review wizard: create Dev Hub Work Item from WhatsApp Work Inbox selection."""
from __future__ import annotations

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class DevWhatsappCreateWorkWizard(models.TransientModel):
    _name = "dev.whatsapp.create.work.wizard"
    _description = "Create Dev Hub Work from WhatsApp"

    message_ids = fields.Many2many("whatsapp.message", required=True)
    primary_message_id = fields.Many2one(
        "whatsapp.message",
        required=True,
        domain="[('id', 'in', message_ids)]",
    )
    title = fields.Char(required=True)
    summary = fields.Text(required=True)
    include_context_before = fields.Integer(default=0)
    include_context_after = fields.Integer(default=0)
    post_create_inbox_state = fields.Selection(
        [("actioned", "Actioned"), ("pending", "Pending")],
        default="actioned",
        required=True,
    )
    allow_additional_work = fields.Boolean(
        string="Create an additional Work Item from these messages",
        help="Managers only. Allowed when messages already link to a Work Item.",
    )
    existing_work_item_id = fields.Many2one("dev.work.item", readonly=True)
    existing_work_warning = fields.Char(readonly=True)

    source_id = fields.Many2one("dev.whatsapp.source", readonly=True)
    dev_project_id = fields.Many2one("dev.project", required=True)
    odoo_project_id = fields.Many2one("project.project", required=True)
    preferred_environment_id = fields.Many2one("dev.environment")
    preferred_repository_id = fields.Many2one("dev.repository")
    responsible_user_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user
    )
    priority_cache = fields.Selection(
        [
            ("0", "Normal"),
            ("1", "Low"),
            ("2", "High"),
            ("3", "Very High"),
        ],
        default="0",
        required=True,
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        msgs = self.env["whatsapp.message"].browse(
            self.env.context.get("default_message_ids")
            and self.env.context["default_message_ids"][0][2]
            or []
        )
        if not msgs and self.env.context.get("active_model") == "whatsapp.message":
            msgs = self.env["whatsapp.message"].browse(
                self.env.context.get("active_ids") or []
            )
        if msgs:
            msgs = msgs.sorted(
                lambda m: (m.message_timestamp or fields.Datetime.now(), m.id)
            )
            primary = msgs[:1]
            if self.env.context.get("default_primary_message_id"):
                primary = msgs.browse(self.env.context["default_primary_message_id"]) & msgs or primary
            source = msgs.mapped("dh_source_id")[:1]
            res.update(
                {
                    "message_ids": [(6, 0, msgs.ids)],
                    "primary_message_id": primary.id,
                    "title": msgs._dh_title("WA"),
                    "summary": self._build_summary(msgs, primary),
                    "source_id": source.id if source else False,
                    "dev_project_id": source.dev_project_id.id if source else False,
                    "odoo_project_id": source.odoo_project_id.id if source else False,
                    "preferred_environment_id": source.default_environment_id.id
                    if source
                    else False,
                    "preferred_repository_id": source.default_repository_id.id
                    if source
                    else False,
                }
            )
            linked = msgs.mapped("work_item_ids")
            if linked:
                res["existing_work_item_id"] = linked[:1].id
                res["existing_work_warning"] = (
                    "These messages already link to Work Item(s). "
                    "Open existing Work or enable additional Work (managers)."
                )
        return res

    @api.model
    def _build_summary(self, messages, primary):
        lines = ["WhatsApp Request", ""]
        conv = primary.conversation_id
        source = primary.dh_source_id
        lines.append(
            "Conversation: %s"
            % (source.name if source else (conv.name if conv else primary.group_jid or "DM"))
        )
        lines.append("Sender: %s" % (primary.sender_jid or "unknown"))
        if primary.message_timestamp:
            lines.append(
                "Received: %s" % fields.Datetime.to_string(primary.message_timestamp)
            )
        lines.append("")
        lines.append("Selected messages:")
        for msg in messages.sorted(
            lambda m: (m.message_timestamp or fields.Datetime.now(), m.id)
        ):
            stamp = (
                fields.Datetime.to_string(msg.message_timestamp)[11:16]
                if msg.message_timestamp
                else "????"
            )
            body = (msg.body or "").strip() or "[%s]" % (msg.media_kind or "empty")
            lines.append("[%s] %s" % (stamp, body.replace("\n", " ")[:300]))
        lines.append("")
        lines.append("Source:")
        lines.append("Open WhatsApp Context")
        return "\n".join(lines)[:6000]

    @api.onchange("message_ids", "primary_message_id", "include_context_before", "include_context_after")
    def _onchange_rebuild_summary(self):
        if self.message_ids and self.primary_message_id:
            msgs = self.message_ids
            if self.include_context_before or self.include_context_after:
                ctx = self.env["whatsapp.message"].get_inbox_context(
                    self.primary_message_id.id,
                    before=self.include_context_before or 0,
                    after=self.include_context_after or 0,
                )
                extra_ids = [m["id"] for m in ctx.get("messages") or []]
                msgs = self.env["whatsapp.message"].browse(
                    list(dict.fromkeys(list(msgs.ids) + extra_ids))
                )
            self.summary = self._build_summary(msgs, self.primary_message_id)

    def action_open_existing_work(self):
        self.ensure_one()
        if not self.existing_work_item_id:
            raise UserError("No existing Work Item.")
        work = self.env["dev.work.item"].browse(self.existing_work_item_id.id)
        work.check_access("read")
        return {
            "type": "ir.actions.act_window",
            "res_model": "dev.work.item",
            "res_id": work.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    def action_create_work(self):
        self.ensure_one()
        if not (
            self.env.user.has_group("devhub_core.group_dev_hub_user")
            or self.env.user.has_group("devhub_core.group_dev_hub_manager")
        ):
            raise AccessError("Dev Hub user rights required.")

        messages = self.message_ids
        if not messages:
            raise UserError("Select at least one message.")
        if len(messages.mapped("conversation_id")) != 1:
            raise ValidationError("All selected messages must share the same conversation.")
        if self.primary_message_id not in messages:
            raise ValidationError("Primary message must be in the selected set.")

        # Project access: must be able to read the project without sudo
        project = self.env["dev.project"].browse(self.dev_project_id.id)
        project.check_access("read")
        odoo_project = self.env["project.project"].browse(self.odoo_project_id.id)
        odoo_project.check_access("read")

        linked = messages.mapped("work_item_ids")
        if linked and not self.allow_additional_work:
            raise UserError(
                "These messages already link to a Work Item. "
                "Open it, or enable 'Create an additional Work Item' (managers)."
            )
        if self.allow_additional_work and not self.env.user.has_group(
            "devhub_core.group_dev_hub_manager"
        ):
            raise AccessError("Only Dev Hub managers may create additional Work Items.")

        # Expand with optional context neighbors (same conversation)
        create_msgs = messages
        if self.include_context_before or self.include_context_after:
            ctx = self.env["whatsapp.message"].get_inbox_context(
                self.primary_message_id.id,
                before=min(self.include_context_before or 0, 20),
                after=min(self.include_context_after or 0, 20),
            )
            extra = self.env["whatsapp.message"].browse(
                [m["id"] for m in ctx.get("messages") or []]
            )
            create_msgs = (messages | extra).sorted(
                lambda m: (m.message_timestamp or fields.Datetime.now(), m.id)
            )

        source_msgs = create_msgs._dh_ensure_source_messages()
        # Ensure primary snapshot text matches wizard summary start — update primary snapshot
        primary_src = source_msgs.filtered(
            lambda s: s.whatsapp_message_id == self.primary_message_id
        )[:1]
        if primary_src:
            # Keep sanitization path: write allowed via text_snapshot rules
            try:
                primary_src.write({"text_snapshot": (self.summary or "")[:6000]})
            except Exception:
                pass

        Work = self.env["dev.work.item"]
        work = Work.create(
            {
                "name": (self.title or "")[:300],
                "dev_project_id": project.id,
                "odoo_project_id": odoo_project.id,
                "preferred_environment_id": self.preferred_environment_id.id or False,
                "preferred_repository_id": self.preferred_repository_id.id or False,
                "responsible_user_id": self.responsible_user_id.id,
                "priority_cache": self.priority_cache,
                "source_message_ids": [(6, 0, source_msgs.ids)],
                "source_type": "whatsapp",
            }
        )

        event_type = "additional_work" if linked else "work_created"
        for msg in messages:
            msg._inbox_set_state(
                self.post_create_inbox_state,
                event_type="actioned"
                if self.post_create_inbox_state == "actioned"
                else "pending",
                note="work_item_id=%s" % work.id,
            )
            msg._inbox_log(
                event_type,
                msg.inbox_state,
                msg.inbox_state,
                note="linked work %s" % work.id,
                work=work,
            )

        # Link intake if open
        Intake = self.env["dev.whatsapp.intake"]
        source = self.source_id or messages.mapped("dh_source_id")[:1]
        if source:
            intake = Intake.search(
                [
                    ("source_id", "=", source.id),
                    ("whatsapp_message_id", "in", messages.ids),
                    ("work_item_id", "=", False),
                    ("state", "not in", ["rejected", "abandoned", "merged"]),
                ],
                limit=1,
            )
            if intake:
                intake.write(
                    {
                        "work_item_id": work.id,
                        "state": "confirmed",
                        "whatsapp_message_id": self.primary_message_id.id,
                        "source_message_ids": [(4, mid) for mid in source_msgs.ids],
                    }
                )

        return {
            "type": "ir.actions.act_window",
            "name": "Work Item",
            "res_model": "dev.work.item",
            "res_id": work.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }


class DevWorkItemWhatsappContext(models.Model):
    _inherit = "dev.work.item"

    def action_open_whatsapp_context(self):
        self.ensure_one()
        self.check_access("read")
        Source = self.env["dev.work.source.message"]
        sources = self.source_message_ids.filtered("whatsapp_message_id")
        msg_ids = sources.mapped("whatsapp_message_id").ids
        if not msg_ids:
            # Legacy: intake reverse
            Intake = self.env["dev.whatsapp.intake"].sudo()
            intakes = Intake.search([("work_item_id", "=", self.id)])
            msg_ids = intakes.mapped("whatsapp_message_id").ids
        if not msg_ids:
            raise UserError("No linked WhatsApp Hub messages on this Work Item.")
        messages = self.env["whatsapp.message"].browse(msg_ids).exists()
        messages.check_access("read")
        primary = messages.sorted(
            lambda m: (m.message_timestamp or fields.Datetime.now(), m.id)
        )[:1]
        return {
            "type": "ir.actions.client",
            "tag": "devhub_whatsapp_work_inbox",
            "name": "WhatsApp Work Inbox",
            "params": {
                "focus_message_id": primary.id,
                "highlight_message_ids": messages.ids,
                "conversation_id": primary.conversation_id.id,
            },
        }


class WhatsappConversationWorkInbox(models.Model):
    _inherit = "whatsapp.conversation"

    def action_open_work_inbox_from_conversation(self):
        self.ensure_one()
        self.check_access("read")
        msg = self.env["whatsapp.message"].search(
            [("conversation_id", "=", self.id)],
            order="message_timestamp desc, id desc",
            limit=1,
        )
        if not msg:
            raise UserError("No messages in this conversation.")
        return msg.action_open_work_inbox()
