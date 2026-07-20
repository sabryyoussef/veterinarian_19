# -*- coding: utf-8 -*-
from __future__ import annotations

import html
import logging
import secrets
from datetime import timedelta

from markupsafe import Markup
from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

TOKEN_MIN_SUBMIT_INTERVAL_SECONDS = 60
DEFAULT_TOKEN_VALIDITY_DAYS = 30
TOKEN_GENERATE_MAX_ATTEMPTS = 8
TOKEN_MIN_RESOLVE_LENGTH = 16

# Server-side limits (match or stricter than form maxlength).
MAX_SUBMITTER_NAME = 200
MAX_SUBMITTER_CONTACT = 200
MAX_CLARIFICATION = 5000
MAX_NOTES = 3000
MAX_SUGGESTED_SUBTASKS_TEXT = 5000
MAX_PRIORITY_SUGGESTION = 32
MAX_DUE_DATE_SUGGESTION = 32
MAX_SUGGESTED_SUBTASK_LINES = 50
MAX_SUGGESTED_SUBTASK_LINE_LENGTH = 200
MAX_TOTAL_PUBLIC_TEXT = 12000

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

    # Odoo 19: models.Constraint (legacy _sql_constraints is ignored).
    # PostgreSQL UNIQUE allows multiple NULLs, so unset tokens stay allowed.
    _public_update_token_uniq = models.Constraint(
        "UNIQUE(public_update_token)",
        "Public update token must be unique.",
    )

    public_update_token = fields.Char(
        string="Public Update Token",
        copy=False,
        index=True,
        groups="project.group_project_user",
        help=(
            "High-entropy capability token for the public update URL. "
            "Stored plaintext so authorized users can re-display the reusable "
            "link (accepted risk for 19.0.1.4.0; digest-only is backlog)."
        ),
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

    @api.constrains("public_update_token")
    def _check_public_update_token_not_empty_string(self):
        for task in self:
            if task.public_update_token is not None and task.public_update_token == "":
                raise ValidationError(_("Public update token cannot be an empty string."))

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

    def _generate_unique_public_update_token(self) -> str:
        """Return a unique high-entropy token; never overwrites another task's token."""
        Task = self.env["project.task"]
        for _attempt in range(TOKEN_GENERATE_MAX_ATTEMPTS):
            candidate = secrets.token_urlsafe(32)
            if len(candidate) < TOKEN_MIN_RESOLVE_LENGTH:
                continue
            # Exclude self so regenerate on the same record is allowed.
            clash = Task.sudo().search_count([
                ("public_update_token", "=", candidate),
                ("id", "not in", self.ids or [0]),
            ])
            if not clash:
                return candidate
        _logger.error(
            "public_task_update token_collision_exhausted attempts=%s",
            TOKEN_GENERATE_MAX_ATTEMPTS,
        )
        raise UserError(_("Could not allocate a unique public link. Please try again."))

    def action_generate_public_update_token(self):
        """Generate (or regenerate) a secure public update token."""
        self.ensure_one()
        token = self._generate_unique_public_update_token()
        expiry = fields.Datetime.now() + timedelta(days=DEFAULT_TOKEN_VALIDITY_DAYS)
        try:
            with self.env.cr.savepoint():
                self.write({
                    "public_update_token": token,
                    "public_update_token_expiry": expiry,
                    "public_update_token_active": True,
                })
        except IntegrityError:
            _logger.error("public_task_update token_unique_violation on generate")
            raise UserError(_("Could not allocate a unique public link. Please try again.")) from None
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
        if not token or len(token) < TOKEN_MIN_RESOLVE_LENGTH:
            return self.browse()
        # Prefer active records; archived tasks must not resolve publicly.
        task = self.sudo().with_context(active_test=True).search([
            ("public_update_token", "=", token),
            ("public_update_token_active", "=", True),
        ], limit=1)
        if not task:
            return self.browse()
        if not task.active:
            return self.browse()
        if task.public_update_token_expiry and task.public_update_token_expiry < fields.Datetime.now():
            return self.browse()
        # Authoritative closed-state semantic from project (CLOSED_STATES / is_closed).
        if task.is_closed:
            return self.browse()
        return task

    def _lock_for_public_submission(self):
        """Row-lock this task so throttle + counter updates are concurrent-safe."""
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM project_task WHERE id = %s FOR UPDATE",
            (self.id,),
        )

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
        return PRIORITY_LABELS.get(value, "")

    @staticmethod
    def _parse_subtask_lines(text: str) -> list[str]:
        lines = []
        for line in (text or "").splitlines():
            stripped = line.strip()
            if stripped:
                lines.append(stripped)
        return lines

    @classmethod
    def _validate_public_submission_fields(
        cls,
        *,
        submitter_name: str,
        submitter_contact: str,
        clarification: str,
        priority_suggestion: str,
        due_date_suggestion: str,
        notes: str,
        suggested_subtasks: str,
        team_planning: bool,
    ) -> dict:
        """Normalize and bound public POST fields. Raises UserError on reject."""

        def _as_text(value) -> str:
            if value is None:
                return ""
            if not isinstance(value, str):
                raise UserError(_("Invalid form input."))
            return value

        submitter_name = _as_text(submitter_name).strip()
        submitter_contact = _as_text(submitter_contact).strip()
        clarification = _as_text(clarification).strip()
        priority_raw = _as_text(priority_suggestion).strip()
        due_date_suggestion = _as_text(due_date_suggestion).strip()
        notes = _as_text(notes).strip()
        suggested_subtasks = _as_text(suggested_subtasks).strip()

        if len(submitter_name) > MAX_SUBMITTER_NAME:
            raise UserError(_("Please shorten your name."))
        if len(submitter_contact) > MAX_SUBMITTER_CONTACT:
            raise UserError(_("Please shorten your contact details."))
        if len(clarification) > MAX_CLARIFICATION:
            raise UserError(_("Please shorten the clarification."))
        if len(notes) > MAX_NOTES:
            raise UserError(_("Please shorten the notes."))
        if len(suggested_subtasks) > MAX_SUGGESTED_SUBTASKS_TEXT:
            raise UserError(_("Please shorten the suggested subtasks."))
        if len(priority_raw) > MAX_PRIORITY_SUGGESTION:
            raise UserError(_("Invalid priority suggestion."))
        if len(due_date_suggestion) > MAX_DUE_DATE_SUGGESTION:
            raise UserError(_("Invalid due date suggestion."))

        subtask_lines = cls._parse_subtask_lines(suggested_subtasks)
        if len(subtask_lines) > MAX_SUGGESTED_SUBTASK_LINES:
            raise UserError(_("Too many suggested subtasks."))
        for line in subtask_lines:
            if len(line) > MAX_SUGGESTED_SUBTASK_LINE_LENGTH:
                raise UserError(_("A suggested subtask is too long."))

        total = (
            len(submitter_name)
            + len(submitter_contact)
            + len(clarification)
            + len(notes)
            + len(suggested_subtasks)
            + len(priority_raw)
            + len(due_date_suggestion)
        )
        if total > MAX_TOTAL_PUBLIC_TEXT:
            raise UserError(_("Submission is too large."))

        if not submitter_name:
            raise UserError(_("Please enter your name."))
        if not clarification:
            raise UserError(_("Please enter details or clarification."))

        priority_suggestion = ""
        if not team_planning:
            priority_suggestion = cls._format_priority_label(priority_raw)
            if priority_raw and not priority_suggestion:
                raise UserError(_("Invalid priority suggestion."))
        else:
            # Team planning form must not accept client-only fields as relational input.
            priority_suggestion = ""
            due_date_suggestion = ""

        return {
            "submitter_name": submitter_name,
            "submitter_contact": submitter_contact,
            "clarification": clarification,
            "priority_suggestion": priority_suggestion,
            "due_date_suggestion": due_date_suggestion if not team_planning else "",
            "notes": notes,
            "suggested_subtasks": "\n".join(subtask_lines) if team_planning else "",
        }

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
        # Validate shape/lengths before any lock or sudo mutation side effects beyond resolve.
        cleaned = self._validate_public_submission_fields(
            submitter_name=submitter_name,
            submitter_contact=submitter_contact,
            clarification=clarification,
            priority_suggestion=priority_suggestion,
            due_date_suggestion=due_date_suggestion,
            notes=notes,
            suggested_subtasks=suggested_subtasks,
            team_planning=self._is_team_planning_mode(),
        )

        self._lock_for_public_submission()
        self.invalidate_recordset([
            "public_update_last_submission_at",
            "public_update_submission_count",
        ])
        if self._public_update_rate_limited():
            raise UserError(_("Please wait a moment before submitting again."))

        if self._is_team_planning_mode():
            body = self._build_team_planning_chatter(
                submitter_name=cleaned["submitter_name"],
                submitter_contact=cleaned["submitter_contact"],
                clarification=cleaned["clarification"],
                notes=cleaned["notes"],
                suggested_subtasks=cleaned["suggested_subtasks"],
            )
        else:
            body = self._build_client_update_chatter(
                submitter_name=cleaned["submitter_name"],
                submitter_contact=cleaned["submitter_contact"],
                clarification=cleaned["clarification"],
                priority_suggestion=cleaned["priority_suggestion"],
                due_date_suggestion=cleaned["due_date_suggestion"],
                notes=cleaned["notes"],
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
            "public_task_update submission accepted task_id=%s purpose=%s count=%s",
            self.id,
            self.public_update_purpose,
            self.public_update_submission_count,
        )
