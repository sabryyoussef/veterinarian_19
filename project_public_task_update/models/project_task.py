# -*- coding: utf-8 -*-
from __future__ import annotations

import html
import logging
import secrets
from datetime import timedelta

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

TOKEN_MIN_SUBMIT_INTERVAL_SECONDS = 60
DEFAULT_TOKEN_VALIDITY_DAYS = 30

PRIORITY_LABELS = {
    "low": "Low / منخفض",
    "normal": "Normal / عادي",
    "high": "High / عالي",
    "urgent": "Urgent / عاجل",
}

PUBLIC_UPDATE_PURPOSE = [
    ("client_update", "Client update / تحديث العميل"),
    ("team_planning", "Team planning / تخطيط الفريق"),
]


class ProjectTask(models.Model):
    _inherit = "project.task"

    public_update_token = fields.Char(
        string="Public Update Token",
        copy=False,
        index=True,
        groups="project.group_project_user",
    )
    public_update_token_expiry = fields.Datetime(
        string="Public Link Expiry",
        copy=False,
        groups="project.group_project_user",
    )
    public_update_token_active = fields.Boolean(
        string="Public Link Active",
        default=False,
        copy=False,
        groups="project.group_project_user",
    )
    public_update_submission_count = fields.Integer(
        string="Public Submissions",
        default=0,
        readonly=True,
        copy=False,
        groups="project.group_project_user",
    )
    public_update_last_submission_at = fields.Datetime(
        string="Last Public Submission",
        readonly=True,
        copy=False,
        groups="project.group_project_user",
    )
    public_update_url = fields.Char(
        string="Public Update URL",
        compute="_compute_public_update_url",
        groups="project.group_project_user",
    )
    public_update_purpose = fields.Selection(
        selection=PUBLIC_UPDATE_PURPOSE,
        string="Link Purpose",
        default="client_update",
        required=True,
        copy=False,
        groups="project.group_project_user",
        help="Client update: missing-data form for external clients. "
             "Team planning: internal colleagues review plan and suggest subtasks.",
    )
    public_update_public_instruction = fields.Text(
        string="Public Form Instruction",
        help="Optional short note shown on the public update form (safe for clients/colleagues).",
        groups="project.group_project_user",
    )
    implementation_plan = fields.Text(
        string="Implementation Plan",
        help="Plan shown on team planning links only. Keep content client/colleague-safe.",
        groups="project.group_project_user",
    )
    missing_data_questions = fields.Text(
        string="Missing Data Questions",
        help="Questions shown on team planning links. One question per line is recommended.",
        groups="project.group_project_user",
    )

    @api.depends("public_update_token", "public_update_token_active", "public_update_token_expiry")
    def _compute_public_update_url(self):
        for task in self:
            task.public_update_url = task.get_public_update_url() or ""

    def get_public_update_url(self) -> str | bool:
        """Return the public Odoo URL for this task, or False if not available."""
        self.ensure_one()
        if not self.public_update_token or not self.public_update_token_active:
            return False
        if self.public_update_token_expiry and self.public_update_token_expiry < fields.Datetime.now():
            return False
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
        if not base:
            return False
        return f"{base}/task/update/{self.public_update_token}"

    def action_generate_public_update_token(self):
        """Generate (or regenerate) a secure public update token."""
        self.ensure_one()
        token = secrets.token_urlsafe(32)
        expiry = fields.Datetime.now() + timedelta(days=DEFAULT_TOKEN_VALIDITY_DAYS)
        self.write({
            "public_update_token": token,
            "public_update_token_expiry": expiry,
            "public_update_token_active": True,
        })
        url = self.get_public_update_url()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Public update link"),
                "message": url or _("Link could not be built — check web.base.url."),
                "type": "success",
                "sticky": True,
            },
        }

    def action_disable_public_update_token(self):
        """Disable the public update link without deleting the token."""
        self.ensure_one()
        self.write({"public_update_token_active": False})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Public link disabled"),
                "message": _("The public update link is no longer valid."),
                "type": "warning",
                "sticky": False,
            },
        }

    def get_whatsapp_message_templates(self) -> dict[str, str]:
        """Return AR/EN message templates with the public link substituted."""
        self.ensure_one()
        link = self.get_public_update_url() or "{odoo_public_link}"
        return {
            "ar_full": (
                "برجاء استكمال بيانات الطلب من الرابط التالي:\n"
                f"{link}\n\n"
                "لا تحتاج إلى حساب OpenProject.\n"
                "الرابط مخصص لهذا الطلب فقط."
            ),
            "en_full": (
                "Please complete the missing task details using this link:\n"
                f"{link}\n\n"
                "No OpenProject login is required.\n"
                "This link is only for this request."
            ),
            "ar_short": f"من فضلك كمّل بيانات الطلب من هنا:\n{link}",
            "en_short": f"Please complete the task details here:\n{link}",
            "ar_team_planning": (
                "من فضلك راجع خطة تنفيذ التاسك وأضف أي بيانات ناقصة أو مهام فرعية مقترحة من الرابط:\n"
                f"{link}\n\n"
                "لا تحتاج إلى حساب OpenProject.\n"
                "الرابط مخصص لهذا التاسك فقط."
            ),
            "en_team_planning": (
                "Please review the task implementation plan and add any missing details "
                f"or suggested subtasks here:\n{link}\n\n"
                "No OpenProject login is required.\n"
                "This link is only for this task."
            ),
        }

    def action_show_whatsapp_template_ar(self):
        self.ensure_one()
        msg = self.get_whatsapp_message_templates()["ar_full"]
        return self._notification_copy_message(_("Arabic WhatsApp message"), msg)

    def action_show_whatsapp_template_en(self):
        self.ensure_one()
        msg = self.get_whatsapp_message_templates()["en_full"]
        return self._notification_copy_message(_("English WhatsApp message"), msg)

    def action_show_team_whatsapp_template_ar(self):
        self.ensure_one()
        msg = self.get_whatsapp_message_templates()["ar_team_planning"]
        return self._notification_copy_message(_("Arabic team planning message"), msg)

    def action_show_team_whatsapp_template_en(self):
        self.ensure_one()
        msg = self.get_whatsapp_message_templates()["en_team_planning"]
        return self._notification_copy_message(_("English team planning message"), msg)

    def _notification_copy_message(self, title: str, message: str):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": "info",
                "sticky": True,
            },
        }

    @api.model
    def _get_task_by_public_update_token(self, token: str):
        """Resolve a task from a public token. Returns empty recordset if invalid."""
        token = (token or "").strip()
        if len(token) < 16:
            return self.browse()
        task = self.sudo().search([
            ("public_update_token", "=", token),
            ("public_update_token_active", "=", True),
        ], limit=1)
        if not task:
            return self.browse()
        if task.public_update_token_expiry and task.public_update_token_expiry < fields.Datetime.now():
            return self.browse()
        return task

    def _public_update_rate_limited(self) -> bool:
        """True if submissions are coming too fast (basic abuse protection)."""
        self.ensure_one()
        last = self.public_update_last_submission_at
        if not last:
            return False
        delta = fields.Datetime.now() - last
        return delta.total_seconds() < TOKEN_MIN_SUBMIT_INTERVAL_SECONDS

    def _is_team_planning_mode(self) -> bool:
        self.ensure_one()
        return self.public_update_purpose == "team_planning"

    def _public_task_title(self) -> str:
        """Safe title for public pages — no internal OP identifiers."""
        self.ensure_one()
        name = (self.name or "").strip()
        return name or _("Task")

    @staticmethod
    def _public_safe_text(value: str) -> str:
        """Return stripped plain text safe for public QWeb display (t-esc)."""
        return (value or "").strip()

    def _public_task_instruction(self) -> str:
        """Optional client-safe instruction for the public form."""
        self.ensure_one()
        custom = self._public_safe_text(self.public_update_public_instruction)
        if custom:
            return custom
        if self._is_team_planning_mode():
            return _(
                "Please review the plan below and add missing details or suggested subtasks. "
                "/ يرجى مراجعة الخطة أدناه وإضافة البيانات الناقصة أو المهام الفرعية المقترحة."
            )
        return _(
            "Please complete the missing information below. "
            "/ يرجى إكمال البيانات الناقصة أدناه."
        )

    def _public_implementation_plan(self) -> str:
        self.ensure_one()
        return self._public_safe_text(self.implementation_plan)

    def _public_missing_data_questions(self) -> str:
        self.ensure_one()
        return self._public_safe_text(self.missing_data_questions)

    def _public_child_tasks_payload(self) -> list[dict]:
        """Return allowlisted direct-child info for the public page.

        Only reads ``child_ids`` of the already token-resolved task.
        Never includes IDs, OpenProject fields, assignees, descriptions, or URLs.
        """
        self.ensure_one()
        children = self.child_ids.sorted(lambda t: (t.sequence, t.id))
        payload = []
        for child in children:
            stage = child.stage_id
            stage_name = ""
            if stage:
                stage_name = self._public_safe_text(stage.display_name or stage.name or "")
            payload.append({
                "name": self._public_safe_text(child.name) or _("Sub-task"),
                "stage_name": stage_name,
                "is_closed": bool(child.is_closed),
            })
        return payload

    @staticmethod
    def _format_priority_label(value: str) -> str:
        value = (value or "").strip().lower()
        if not value:
            return ""
        return PRIORITY_LABELS.get(value, value)

    @staticmethod
    def _parse_subtask_lines(text: str) -> list[str]:
        lines = []
        for line in (text or "").splitlines():
            stripped = line.strip()
            if stripped:
                lines.append(stripped)
        return lines

    @staticmethod
    def _html_block(label: str, value: str, multiline: bool = False) -> str:
        if not value:
            return ""
        escaped = html.escape(value)
        if multiline:
            escaped = escaped.replace("\n", "<br/>")
        return f"<p><strong>{html.escape(label)}</strong><br/>{escaped}</p>"

    def _build_client_update_chatter(
        self,
        *,
        submitter_name: str,
        submitter_contact: str,
        clarification: str,
        priority_suggestion: str,
        due_date_suggestion: str,
        notes: str,
    ) -> Markup:
        parts = [
            "<p><strong>Public task update submitted</strong></p>",
            "<p><strong>Submitter:</strong></p>",
            "<ul>",
            f"<li><strong>Name:</strong> {html.escape(submitter_name)}</li>",
        ]
        if submitter_contact:
            parts.append(f"<li><strong>Contact:</strong> {html.escape(submitter_contact)}</li>")
        parts.append("</ul>")
        parts.append("<p><strong>Submitted details:</strong></p>")
        parts.append(self._html_block("Clarification:", clarification, multiline=True))
        if priority_suggestion:
            parts.append(self._html_block("Priority suggestion:", priority_suggestion))
        if due_date_suggestion:
            parts.append(self._html_block("Due date suggestion:", due_date_suggestion))
        if notes:
            parts.append(self._html_block("Notes:", notes, multiline=True))
        parts.append(
            "<p><strong>Source:</strong><br/>"
            "Submitted through Odoo public task update link.</p>"
        )
        return Markup("".join(parts))

    def _build_team_planning_chatter(
        self,
        *,
        submitter_name: str,
        submitter_contact: str,
        clarification: str,
        notes: str,
        suggested_subtasks: str,
    ) -> Markup:
        parts = [
            "<p><strong>Team planning update submitted</strong></p>",
            "<p><strong>Submitter:</strong></p>",
            "<ul>",
            f"<li><strong>Name:</strong> {html.escape(submitter_name)}</li>",
        ]
        if submitter_contact:
            parts.append(f"<li><strong>Contact:</strong> {html.escape(submitter_contact)}</li>")
        parts.append("</ul>")
        parts.append(self._html_block("Clarification / missing data:", clarification, multiline=True))
        if notes:
            parts.append(self._html_block("Notes:", notes, multiline=True))
        subtask_lines = self._parse_subtask_lines(suggested_subtasks)
        if subtask_lines:
            parts.append("<p><strong>Suggested subtasks:</strong></p><ul>")
            for line in subtask_lines:
                parts.append(f"<li>{html.escape(line)}</li>")
            parts.append("</ul>")
        parts.append(
            "<p><strong>Source:</strong><br/>"
            "Submitted through Odoo team planning link.</p>"
        )
        return Markup("".join(parts))

    def _record_public_update_submission(
        self,
        *,
        submitter_name: str,
        submitter_contact: str,
        clarification: str,
        priority_suggestion: str = "",
        due_date_suggestion: str = "",
        notes: str = "",
        suggested_subtasks: str = "",
    ) -> None:
        """Save submission as internal chatter note; do not mutate task fields."""
        self.ensure_one()
        if self._public_update_rate_limited():
            raise UserError(_("Please wait a moment before submitting again."))

        submitter_name = (submitter_name or "").strip()
        submitter_contact = (submitter_contact or "").strip()
        clarification = (clarification or "").strip()
        priority_suggestion = self._format_priority_label(priority_suggestion)
        due_date_suggestion = (due_date_suggestion or "").strip()
        notes = (notes or "").strip()
        suggested_subtasks = (suggested_subtasks or "").strip()

        if not submitter_name:
            raise UserError(_("Please enter your name."))
        if not clarification:
            raise UserError(_("Please enter details or clarification."))

        if self._is_team_planning_mode():
            body = self._build_team_planning_chatter(
                submitter_name=submitter_name,
                submitter_contact=submitter_contact,
                clarification=clarification,
                notes=notes,
                suggested_subtasks=suggested_subtasks,
            )
        else:
            body = self._build_client_update_chatter(
                submitter_name=submitter_name,
                submitter_contact=submitter_contact,
                clarification=clarification,
                priority_suggestion=priority_suggestion,
                due_date_suggestion=due_date_suggestion,
                notes=notes,
            )

        self.sudo().message_post(
            body=body,
            message_type="comment",
            subtype_xmlid="mail.mt_note",
        )
        self.sudo().write({
            "public_update_submission_count": self.public_update_submission_count + 1,
            "public_update_last_submission_at": fields.Datetime.now(),
        })
        _logger.info(
            "public_task_update submission task_id=%s purpose=%s count=%s",
            self.id,
            self.public_update_purpose,
            self.public_update_submission_count,
        )
