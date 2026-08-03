# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LinkedinApplyAttempt(models.Model):
    _name = "linkedin.apply.attempt"
    _description = "Job Apply Attempt / Receipt"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char(compute="_compute_name", store=True)
    application_id = fields.Many2one(
        "linkedin.job.application",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
    )
    account_id = fields.Many2one(
        related="application_id.account_id",
        store=True,
        index=True,
        readonly=True,
    )
    job_id = fields.Many2one(related="application_id.job_id", store=True, readonly=True)
    company_name = fields.Char(related="job_id.company", store=True, readonly=True)
    platform = fields.Selection(
        related="job_id.apply_platform",
        store=True,
        readonly=True,
    )
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("drafted", "Drafted (dry-run)"),
            ("awaiting_approval", "Awaiting approval"),
            ("submitted", "Submitted"),
            ("succeeded", "Succeeded"),
            ("submission_unknown", "Submission Unknown"),
            ("human_required", "Human Required"),
            ("stopped", "Stopped"),
            ("failed", "Failed"),
            ("rejected_policy", "Rejected by policy"),
        ],
        default="pending",
        required=True,
        index=True,
        tracking=True,
    )
    dry_run = fields.Boolean(default=True, tracking=True)
    idempotency_key = fields.Char(index=True, copy=False)
    stop_reason = fields.Selection(
        [
            ("none", "None"),
            ("captcha", "CAPTCHA"),
            ("otp", "OTP"),
            ("login_wall", "Login wall"),
            ("consent", "Consent / ToS"),
            ("unknown_question", "Unknown question"),
            ("linkedin_blocked", "LinkedIn blocked"),
            ("submit_disabled", "Submit disabled"),
            ("policy", "Policy"),
            ("worker_error", "Worker error"),
            ("other", "Other"),
        ],
        default="none",
        tracking=True,
    )
    stop_detail = fields.Text()
    final_url = fields.Char()
    screenshot_attachment_ids = fields.Many2many(
        "ir.attachment",
        "linkedin_apply_attempt_screenshot_rel",
        "attempt_id",
        "attachment_id",
        string="Screenshots / receipts",
    )
    worker_attempt_id = fields.Char(string="Browser worker attempt id", index=True)
    n8n_execution_id = fields.Char(index=True)
    dify_run_id = fields.Char(index=True)
    request_payload_json = fields.Text()
    response_payload_json = fields.Text()

    _idempotency_key_uniq = models.Constraint(
        "unique(idempotency_key)",
        "Idempotency key must be unique.",
    )

    @api.depends("application_id", "state", "dry_run")
    def _compute_name(self):
        for rec in self:
            app = rec.application_id.display_name or _("Application")
            mode = "dry-run" if rec.dry_run else "live"
            rec.name = "%s [%s/%s]" % (app, rec.state, mode)

    @api.constrains("account_id")
    def _check_personal(self):
        for rec in self:
            if rec.account_id and rec.account_id.account_type != "personal":
                raise ValidationError(_("Attempts must use a personal account."))
            if rec.account_id and rec.account_id.id == 1:
                raise ValidationError(_("Company account id=1 is forbidden for apply attempts."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("idempotency_key"):
                existing = self.search([("idempotency_key", "=", vals["idempotency_key"])], limit=1)
                if existing:
                    return existing
        return super().create(vals_list)

    def write_status_from_worker(self, vals):
        """Restricted write path used by signed orchestrator API."""
        allowed = {
            "state",
            "stop_reason",
            "stop_detail",
            "final_url",
            "worker_attempt_id",
            "n8n_execution_id",
            "dify_run_id",
            "response_payload_json",
            "dry_run",
        }
        clean = {k: v for k, v in vals.items() if k in allowed}
        if clean.get("state") in ("submitted", "succeeded") and any(self.mapped("dry_run")):
            # During UAT foundation, refuse live success states on dry-run attempts
            if clean.get("dry_run", True):
                raise UserError(_("Cannot mark submitted/succeeded while dry_run=True."))
        return self.write(clean)
