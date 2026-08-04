# -*- coding: utf-8 -*-
import re
from html import unescape

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LinkedinJobApplication(models.Model):
    _name = "linkedin.job.application"
    _description = "LinkedIn Job Application (review-first)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "score desc, id desc"
    _rec_name = "display_name"

    job_id = fields.Many2one(
        "linkedin.job",
        string="Job",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
    )
    account_id = fields.Many2one(
        "linkedin.account",
        string="Personal account",
        required=True,
        ondelete="restrict",
        index=True,
        domain="[('account_type', '=', 'personal')]",
        tracking=True,
    )
    display_name = fields.Char(compute="_compute_display_name", store=True)
    state = fields.Selection(
        [
            ("discovered", "Discovered"),
            ("shortlisted", "Shortlisted"),
            ("pack_ready", "Pack Ready"),
            ("queued", "Queued"),
            ("filling", "Filling"),
            ("drafted", "Drafted"),
            ("submitting", "Submitting"),
            ("approved", "Approved"),
            ("human_required", "Human Required"),
            ("missing_fact", "Missing Fact"),
            ("unsupported_ats", "Unsupported ATS"),
            ("hard_excluded", "Hard Excluded"),
            ("submission_unknown", "Submission Unknown"),
            ("delivery_failed", "Delivery Failed"),
            ("failed", "Failed"),
            ("applied", "Applied"),
            ("interview", "Interview"),
            ("rejected", "Rejected"),
            ("offer", "Offer"),
        ],
        default="discovered",
        required=True,
        index=True,
        tracking=True,
    )
    submission_channel = fields.Selection(
        [
            ("browser", "Browser form"),
            ("email", "Email application"),
            ("manual", "Manual"),
            ("unknown", "Unknown"),
        ],
        default="unknown",
        tracking=True,
    )
    confirmation_url = fields.Char(string="Confirmation URL", copy=False)
    confirmation_reference = fields.Char(string="Confirmation / Message-ID", copy=False)
    evidence_kind = fields.Char(string="Evidence kind", copy=False)
    evidence_json = fields.Text(string="Evidence JSON", copy=False)
    email_provider_message_id = fields.Char(copy=False)
    email_rfc_message_id = fields.Char(copy=False)
    email_recipient = fields.Char(copy=False)
    email_content_hash = fields.Char(copy=False)
    cv_sha256 = fields.Char(string="CV SHA-256", copy=False)
    challenge_token_fingerprint = fields.Char(copy=False)
    challenge_expires_at = fields.Datetime(copy=False)
    filled_summary_json = fields.Text(
        string="Filled values summary (redacted)",
        help="Read-only summary shown before human challenge. No secrets.",
    )
    next_required_action = fields.Char(string="Next required action", copy=False)
    attempt_count = fields.Integer(compute="_compute_attempt_count", store=True)
    last_action_at = fields.Datetime(string="Last action", copy=False)
    score = fields.Float(string="Score", related="job_id.score", store=True, readonly=True)
    cv_version_id = fields.Many2one(
        "linkedin.cv.version",
        string="CV version",
        domain="[('account_id', '=', account_id), ('active', '=', True)]",
    )
    cover_letter = fields.Text(string="Cover letter draft")
    screening_answers = fields.Text(string="Screening answers draft")
    checklist = fields.Text(string="Application checklist")
    notes = fields.Text(string="Notes")
    approved_by = fields.Many2one("res.users", string="Approved by", readonly=True, copy=False)
    approved_at = fields.Datetime(string="Approved at", readonly=True, copy=False)
    applied_at = fields.Datetime(string="Applied at", readonly=True, copy=False)

    job_title = fields.Char(related="job_id.title", store=True, readonly=True)
    job_company = fields.Char(related="job_id.company", store=True, readonly=True)
    job_location = fields.Char(related="job_id.location", store=True, readonly=True)
    apply_url = fields.Char(related="job_id.apply_url", readonly=True)
    apply_platform = fields.Selection(
        related="job_id.apply_platform", store=True, readonly=True
    )

    # Orchestrator pack / correlation fields
    pack_json = fields.Text(string="Dify pack JSON")
    match_decision = fields.Char()
    exclusion_flags = fields.Text()
    missing_facts = fields.Text()
    risk_notes = fields.Text()
    recommended_channel = fields.Char()
    exception_reason = fields.Text()
    receipt_attachment_ids = fields.Many2many(
        "ir.attachment",
        "linkedin_job_application_receipt_rel",
        "application_id",
        "attachment_id",
        string="Receipts",
    )
    n8n_execution_id = fields.Char(index=True)
    dify_run_id = fields.Char(index=True)
    orchestrator_idempotency_key = fields.Char(index=True, copy=False)
    manual_task = fields.Boolean(
        default=False,
        help="True when platform requires manual action (e.g. LinkedIn).",
    )
    attempt_ids = fields.One2many("linkedin.apply.attempt", "application_id", string="Attempts")

    @api.depends("job_id", "job_id.title", "job_id.company")
    def _compute_display_name(self):
        for rec in self:
            title = rec.job_id.title or _("Job")
            company = rec.job_id.company or ""
            rec.display_name = "%s @ %s" % (title, company) if company else title

    @api.depends("attempt_ids")
    def _compute_attempt_count(self):
        for rec in self:
            rec.attempt_count = len(rec.attempt_ids)

    @api.constrains("account_id")
    def _check_personal_account(self):
        for rec in self:
            if rec.account_id.account_type != "personal":
                raise ValidationError(
                    _("Applications must use a personal LinkedIn account, never PetSpot/company.")
                )
            if rec.account_id.id == 1:
                raise ValidationError(_("Company account id=1 cannot own applications."))

    def write_pack_from_orchestrator(self, pack):
        """Apply Dify pack result via signed API — no invented facts written as truth."""
        self.ensure_one()
        if self.account_id.account_type != "personal" or self.account_id.id == 1:
            raise UserError(_("Refusing pack write for non-personal/company account."))
        if self.state not in ("discovered", "shortlisted", "pack_ready"):
            raise UserError(
                _("Unauthorized state transition for pack write (state=%s).") % self.state
            )
        import json

        missing = pack.get("missing_facts") or []
        vals = {
            "pack_json": json.dumps(pack, ensure_ascii=False, sort_keys=True),
            "match_decision": pack.get("match_decision") or "",
            "exclusion_flags": json.dumps(pack.get("exclusion_flags") or []),
            "missing_facts": json.dumps(missing),
            "risk_notes": pack.get("risk_notes") or "",
            "recommended_channel": pack.get("recommended_channel") or "",
            "cover_letter": pack.get("cover_letter") or self.cover_letter,
            "screening_answers": json.dumps(pack.get("screening_qa") or []),
            "checklist": self.checklist
            or "Review Dify pack; confirm missing_facts before approval.",
            "dify_run_id": pack.get("dify_run_id") or self.dify_run_id,
            "n8n_execution_id": pack.get("n8n_execution_id") or self.n8n_execution_id,
            "state": "pack_ready",
        }
        if (self.job_id.apply_platform or "") == "linkedin":
            vals["manual_task"] = True
            vals["recommended_channel"] = vals["recommended_channel"] or "manual_linkedin"
        self.write(vals)
        return True

    def to_orchestrator_payload(self):
        """Scoped payload for n8n — personal applications only."""
        self.ensure_one()
        if self.account_id.account_type != "personal" or self.account_id.id == 1:
            raise UserError(_("Payload refused for company/non-personal account."))
        profile = self.env["linkedin.candidate.profile"].search(
            [("account_id", "=", self.account_id.id), ("active", "=", True)], limit=1
        )
        policy = self.env["linkedin.apply.policy"].get_policy_for_account(self.account_id)
        return {
            "application_id": self.id,
            "state": self.state,
            "score": self.score,
            "account_id": self.account_id.id,
            "job": {
                "id": self.job_id.id,
                "title": self.job_id.title,
                "company": self.job_id.company,
                "location": self.job_id.location,
                "apply_url": self.job_id.apply_url,
                "apply_platform": self.job_id.apply_platform,
                "listed_at": fields.Datetime.to_string(self.job_id.listed_at)
                if self.job_id.listed_at
                else None,
                "description_excerpt": (self._plain_job_description() or "")[:2000],
            },
            "cv_version_id": self.cv_version_id.id if self.cv_version_id else None,
            "candidate_profile": profile.to_sanitized_json() if profile else {},
            "policy": policy.to_public_dict(),
            "manual_task": self.manual_task,
        }

    @api.constrains("cv_version_id", "account_id")
    def _check_cv_account(self):
        for rec in self:
            if rec.cv_version_id and rec.cv_version_id.account_id != rec.account_id:
                raise ValidationError(_("CV version must belong to the same personal account."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("account_id") and vals.get("job_id"):
                job = self.env["linkedin.job"].browse(vals["job_id"])
                if job.account_id and job.account_id.account_type == "personal":
                    vals["account_id"] = job.account_id.id
            if not vals.get("account_id"):
                personal = self.env["linkedin.account"].get_personal_account()
                if not personal:
                    raise UserError(
                        _("Create and classify a personal LinkedIn account before tracking applications.")
                    )
                vals["account_id"] = personal.id
            if not vals.get("cv_version_id"):
                default_cv = self.env["linkedin.cv.version"].search(
                    [
                        ("account_id", "=", vals["account_id"]),
                        ("is_default", "=", True),
                        ("active", "=", True),
                    ],
                    limit=1,
                )
                if default_cv:
                    vals["cv_version_id"] = default_cv.id
        return super().create(vals_list)

    def action_shortlist(self):
        for rec in self:
            if rec.state != "discovered":
                raise UserError(_("Only Discovered applications can be shortlisted."))
            rec.state = "shortlisted"
        return True

    def action_prepare_pack(self):
        for rec in self:
            if rec.state not in (
                "discovered",
                "shortlisted",
                "pack_ready",
                "rejected",
                "human_required",
                "failed",
                "delivery_failed",
                "missing_fact",
            ):
                raise UserError(
                    _(
                        "Prepare pack is available from discovered/shortlisted/pack ready "
                        "(or reopen from rejected/human required)."
                    )
                )
            if not rec.cv_version_id:
                default_cv = self.env["linkedin.cv.version"].search(
                    [
                        ("account_id", "=", rec.account_id.id),
                        ("is_default", "=", True),
                        ("active", "=", True),
                    ],
                    limit=1,
                )
                if default_cv:
                    rec.cv_version_id = default_cv.id
            rec.write(
                {
                    "cover_letter": rec._generate_cover_letter(),
                    "screening_answers": rec._generate_screening_answers(),
                    "checklist": rec._generate_checklist(),
                    "state": "pack_ready",
                    "next_required_action": "review_and_approve",
                }
            )
            rec.message_post(body=_("Application pack prepared (draft). Review and edit before approving."))
        return True

    def action_reopen_for_approval(self):
        """Move rejected / human-required apps back to Pack Ready so Approve is available."""
        if not self.env.user.has_group("linkedin_connector.group_linkedin_job_hunt"):
            raise UserError(_("Only Job Hunt managers can reopen applications."))
        reopenable = (
            "rejected",
            "human_required",
            "failed",
            "delivery_failed",
            "missing_fact",
            "unsupported_ats",
            "hard_excluded",
        )
        for rec in self:
            if rec.account_id.id == 1:
                raise UserError(_("Company account id=1 cannot reopen applications."))
            if rec.state == "applied":
                raise UserError(_("Already applied — no reopen needed."))
            if rec.state not in reopenable and rec.state != "pack_ready":
                raise UserError(
                    _("Cannot reopen from state %s. Use Prepare pack from discovered/shortlisted.")
                    % (rec.state or "")
                )
        return self.action_prepare_pack()

    def action_approve(self):
        if not self.env.user.has_group("linkedin_connector.group_linkedin_job_hunt"):
            raise UserError(_("Only Job Hunt managers can approve applications."))
        for rec in self:
            if rec.state != "pack_ready":
                raise UserError(_("Approve only when state is Pack Ready."))
            if not rec.cover_letter or not rec.checklist:
                raise UserError(_("Cover letter and checklist are required before approval."))
            rec.write(
                {
                    "state": "approved",
                    "approved_by": self.env.user.id,
                    "approved_at": fields.Datetime.now(),
                }
            )
            rec.message_post(body=_("Approved by %s — you may open the apply URL.") % self.env.user.name)
        return True

    def action_open_job_url(self):
        """Open listing/apply URL for review (no submit)."""
        self.ensure_one()
        if not self.apply_url:
            raise UserError(_("This job has no apply URL."))
        return {"type": "ir.actions.act_url", "url": self.apply_url, "target": "new"}

    def action_open_application(self):
        """Open apply URL only after manual approval. Never auto-submit."""
        self.ensure_one()
        if self.state != "approved":
            raise UserError(
                _(
                    "Approval gate: state must be Approved before opening the apply URL. "
                    "Current state: %s. Prepare pack → Approve first. "
                    "No Easy Apply automation is implemented."
                )
                % self.state
            )
        if not self.apply_url:
            raise UserError(_("This job has no apply URL."))
        self.message_post(
            body=_("Apply URL opened for manual submission (no auto-submit).")
        )
        return {"type": "ir.actions.act_url", "url": self.apply_url, "target": "new"}

    def action_mark_applied(self):
        """Mark application as applied (manual or confirmed)."""
        return self.action_mark_confirmed_applied()

    def action_mark_confirmed_applied(self):
        """Set state=applied for personal applications (manual mark allowed)."""
        allowed = (
            "approved",
            "human_required",
            "discovered",
            "shortlisted",
            "pack_ready",
            "queued",
            "filling",
            "drafted",
            "submitting",
            "submission_unknown",
            "delivery_failed",
            "missing_fact",
            "unsupported_ats",
            "failed",
        )
        for rec in self:
            if rec.state == "applied":
                continue
            if rec.account_id.id == 1:
                raise UserError(_("Company account id=1 cannot mark applications applied."))
            if rec.state not in allowed:
                raise UserError(
                    _("Cannot mark applied from state %s.") % (rec.state or "")
                )
            has_evidence = rec._has_verified_submission_evidence()
            vals = {
                "state": "applied",
                "applied_at": fields.Datetime.now(),
                "last_action_at": fields.Datetime.now(),
                "next_required_action": False,
            }
            if not rec.submission_channel or rec.submission_channel == "unknown":
                vals["submission_channel"] = "manual"
            if not has_evidence and not rec.evidence_kind:
                vals["evidence_kind"] = "manual_mark"
            rec.write(vals)
            if rec.job_id and rec.job_id.discovery_class == "human_required":
                rec.job_id.sudo().write({"discovery_blocker": "confirmed_applied"})
            if has_evidence:
                rec.message_post(
                    body=_(
                        "Marked applied with evidence (%s / %s)."
                    )
                    % (
                        rec.evidence_kind or "manual",
                        rec.confirmation_reference or rec.confirmation_url or "—",
                    )
                )
            else:
                rec.message_post(body=_("Marked applied manually (no external evidence)."))
        return True

    def _has_verified_submission_evidence(self):
        self.ensure_one()
        if self.confirmation_url and self.confirmation_url.strip():
            return True
        if self.confirmation_reference and self.confirmation_reference.strip():
            return True
        if self.email_rfc_message_id or self.email_provider_message_id:
            return True
        if self.receipt_attachment_ids:
            return True
        return False

    def action_record_submission_evidence(self, evidence):
        """Persist external evidence and optionally transition to applied.

        evidence keys: kind, confirmation_url, confirmation_reference,
        email_provider_message_id, email_rfc_message_id, email_recipient,
        content_hash, channel, ambiguous, cv_sha256
        """
        self.ensure_one()
        if self.account_id.id == 1:
            raise UserError(_("Refuse evidence write for company account."))
        import json

        ambiguous = bool(evidence.get("ambiguous"))
        ok = bool(evidence.get("ok")) and not ambiguous
        vals = {
            "evidence_kind": (evidence.get("kind") or "")[:120],
            "confirmation_url": (evidence.get("confirmation_url") or "")[:500] or False,
            "confirmation_reference": (evidence.get("confirmation_reference") or "")[:240] or False,
            "email_provider_message_id": (evidence.get("email_provider_message_id") or "")[:240] or False,
            "email_rfc_message_id": (evidence.get("email_rfc_message_id") or "")[:240] or False,
            "email_recipient": (evidence.get("email_recipient") or "")[:200] or False,
            "email_content_hash": (evidence.get("content_hash") or "")[:128] or False,
            "cv_sha256": (evidence.get("cv_sha256") or self.cv_sha256 or "")[:128] or False,
            "evidence_json": json.dumps(evidence, ensure_ascii=False, sort_keys=True)[:8000],
            "last_action_at": fields.Datetime.now(),
        }
        channel = evidence.get("channel")
        if channel in ("browser", "email", "manual"):
            vals["submission_channel"] = channel
        if ambiguous or (not ok and evidence.get("kind") == "ambiguous"):
            vals["state"] = "submission_unknown"
            vals["next_required_action"] = "resolve_submission_unknown"
            self.write(vals)
            self.message_post(
                body=_("Submission ambiguous — set submission_unknown; token consumed; no retry.")
            )
            return {"state": "submission_unknown", "applied": False}
        if ok and self._has_verified_submission_evidence_vals(vals):
            vals["state"] = "applied"
            vals["applied_at"] = fields.Datetime.now()
            vals["next_required_action"] = False
            self.write(vals)
            self.message_post(body=_("Applied after verified external evidence."))
            return {"state": "applied", "applied": True}
        if evidence.get("kind") == "email_send_error" or evidence.get("delivery_failed"):
            vals["state"] = "delivery_failed"
            vals["next_required_action"] = "review_bounce_or_smtp"
            self.write(vals)
            self.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=_("Email application delivery failed"),
                note=_("Provider reported a send/bounce failure. Review mailbox."),
            )
            return {"state": "delivery_failed", "applied": False}
        self.write(vals)
        return {"state": self.state, "applied": False}

    def _has_verified_submission_evidence_vals(self, vals):
        return bool(
            vals.get("confirmation_url")
            or vals.get("confirmation_reference")
            or vals.get("email_rfc_message_id")
            or vals.get("email_provider_message_id")
        )

    def action_resolve_submission_unknown(self):
        """Audited manual resolution — does NOT set applied without new evidence."""
        for rec in self:
            if rec.state != "submission_unknown":
                raise UserError(_("Only submission_unknown records can be resolved this way."))
            rec.write(
                {
                    "next_required_action": "awaiting_manual_evidence",
                    "last_action_at": fields.Datetime.now(),
                    "notes": (rec.notes or "")
                    + "\n[%s] submission_unknown acknowledged; still not applied."
                    % fields.Datetime.now(),
                }
            )
            rec.message_post(
                body=_("Submission unknown acknowledged. Still not applied without evidence.")
            )
        return True

    def action_open_human_challenge(self):
        """Open apply URL for CAPTCHA/OTP-only human step (form already filled)."""
        self.ensure_one()
        if self.state not in ("human_required", "drafted", "approved"):
            raise UserError(_("Human challenge is only for human_required/drafted/approved."))
        if not self.apply_url:
            raise UserError(_("No apply URL."))
        self.write(
            {
                "next_required_action": "solve_challenge_then_auto_resume",
                "last_action_at": fields.Datetime.now(),
            }
        )
        self.message_post(
            body=_(
                "Human challenge opened. Solve CAPTCHA/OTP only — do not re-type form fields. "
                "Worker will auto-resume submit when token is valid."
            )
        )
        return {"type": "ir.actions.act_url", "url": self.apply_url, "target": "new"}

    def action_retry_preflight(self):
        """Re-run ATS preflight only before any submit attempt."""
        self.ensure_one()
        if self.state in ("applied", "submitting", "submission_unknown"):
            raise UserError(_("Retry preflight is blocked after submit/applied/unknown."))
        if self.attempt_ids.filtered(lambda a: a.state in ("submitted", "succeeded")):
            raise UserError(_("A submit attempt already exists — preflight retry blocked."))
        if self.account_id.id != 2:
            raise UserError(_("Preflight retry is limited to personal account id=2."))
        job = self.job_id
        if not job:
            raise UserError(_("Missing job."))
        classification = None
        try:
            from odoo.addons.linkedin_connector.services.ats_preflight import classify_preflight

            classification = classify_preflight(
                apply_url=job.apply_url or "",
                title=job.title or "",
                description=job.description or "",
                location=job.location or "",
                remote=bool(job.remote),
                score=float(job.score or 0.0),
            )
        except Exception as exc:  # noqa: BLE001
            raise UserError(_("Preflight failed: %s") % exc) from exc
        job.sudo().write(
            {
                "discovery_class": classification.get("discovery_class") or job.discovery_class,
                "discovery_blocker": classification.get("blocker")
                or classification.get("discovery_blocker")
                or "",
            }
        )
        self.write({"last_action_at": fields.Datetime.now(), "next_required_action": "review_preflight"})
        self.message_post(body=_("Preflight re-run: %s") % (classification.get("discovery_class") or ""))
        return True

    def action_open_confirmation(self):
        self.ensure_one()
        if not self.confirmation_url:
            raise UserError(_("No confirmation URL stored."))
        return {"type": "ir.actions.act_url", "url": self.confirmation_url, "target": "new"}

    def action_transition(self, new_state, *, reason="", force=False):
        """Idempotent audited state transition for zero-touch workflow."""
        self.ensure_one()
        if self.account_id.id == 1:
            raise UserError(_("Refuse transitions for company account."))
        if self.state == new_state:
            return True
        # Prefer dedicated mark method, but allow forced/manual transitions.
        if new_state == "applied" and not force:
            return self.action_mark_confirmed_applied()
        allowed_from = {
            "queued": ("pack_ready", "approved", "discovered", "shortlisted"),
            "filling": ("queued", "approved", "pack_ready", "human_required"),
            "drafted": ("filling", "queued", "approved"),
            "submitting": ("drafted", "human_required", "approved"),
            "human_required": ("filling", "drafted", "queued", "approved", "pack_ready"),
            "missing_fact": ("filling", "queued", "pack_ready", "approved", "drafted"),
            "unsupported_ats": ("discovered", "pack_ready", "queued", "filling"),
            "hard_excluded": ("discovered", "pack_ready", "queued", "filling", "approved"),
            "failed": ("filling", "drafted", "submitting", "queued"),
            "delivery_failed": ("submitting", "applied"),
            "submission_unknown": ("submitting", "drafted"),
        }
        if new_state in allowed_from and self.state not in allowed_from[new_state] and not force:
            raise UserError(
                _("Illegal transition %s → %s") % (self.state, new_state)
            )
        self.write(
            {
                "state": new_state,
                "last_action_at": fields.Datetime.now(),
                "next_required_action": reason or self.next_required_action,
            }
        )
        self.message_post(body=_("State → %s (%s)") % (new_state, reason or "workflow"))
        return True

    def action_mark_interview(self):
        for rec in self:
            if rec.state not in ("applied", "interview"):
                raise UserError(_("Interview is available after Applied."))
            rec.state = "interview"
        return True

    def action_mark_rejected(self):
        for rec in self:
            if rec.state in ("offer",):
                raise UserError(_("Cannot reject an offer record; update manually if needed."))
            rec.state = "rejected"
        return True

    def action_mark_offer(self):
        for rec in self:
            if rec.state not in ("applied", "interview"):
                raise UserError(_("Offer is available from Applied or Interview."))
            rec.state = "offer"
        return True

    def _plain_job_description(self):
        self.ensure_one()
        html = self.job_id.description or ""
        text = re.sub(r"<[^>]+>", " ", html)
        text = unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:4000]

    def _generate_cover_letter(self):
        self.ensure_one()
        title = self.job_id.title or "Senior Odoo Developer"
        company = self.job_id.company or "your team"
        cv_name = self.cv_version_id.name if self.cv_version_id else "my CV"
        return (
            "Dear Hiring Team at %(company)s,\n\n"
            "I am applying for the %(title)s role. I am a senior Odoo developer with deep "
            "experience in custom modules, multi-company setups, integrations, upgrades, "
            "and production-safe delivery.\n\n"
            "I focus on maintainable Odoo engineering: configuration before custom code, "
            "clear security (ACLs/record rules), and upgrade-aware design.\n\n"
            "Please find my CV (%(cv)s) attached. I would welcome a conversation about how "
            "I can help %(company)s deliver reliable Odoo outcomes.\n\n"
            "Kind regards,\n"
            "Sabry Youssef\n"
            "https://www.linkedin.com/in/sabry-youssef-56a878185/\n"
        ) % {"company": company, "title": title, "cv": cv_name}

    def _generate_screening_answers(self):
        self.ensure_one()
        desc = self._plain_job_description().lower()
        lines = [
            "Years with Odoo: 5+ (customize as needed)",
            "Seniority: Senior / Technical Lead level — architecture, mentoring, delivery ownership",
            "Remote: Open to remote and hybrid (confirm preferred locations)",
            "Notice period: Confirm before submit",
            "Salary expectation: Confirm before submit",
        ]
        if "python" in desc:
            lines.append("Python: Yes — Odoo backend, services, and integrations")
        if "migration" in desc or "upgrade" in desc:
            lines.append("Upgrades/migrations: Yes — planning, cleanup, and cutover discipline")
        if "shopify" in desc or "ecommerce" in desc:
            lines.append("Ecommerce/integrations: Yes — Shopify and third-party connectors")
        return "\n".join("- %s" % line for line in lines)

    def _generate_checklist(self):
        self.ensure_one()
        cv = self.cv_version_id.name if self.cv_version_id else "(select CV version)"
        return (
            "- [ ] Confirm role is senior Odoo (not junior / unrelated stack)\n"
            "- [ ] Review job description and tailor cover letter\n"
            "- [ ] Attach CV version: %s\n"
            "- [ ] Fill screening answers accurately\n"
            "- [ ] Approve in Odoo (Job Hunt manager)\n"
            "- [ ] Open apply URL and submit manually on LinkedIn\n"
            "- [ ] Mark Applied in Odoo after submission\n"
            "- Easy Apply automation: NOT used (manual only)\n"
        ) % cv
