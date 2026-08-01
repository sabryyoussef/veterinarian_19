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
            ("approved", "Approved"),
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

    @api.depends("job_id", "job_id.title", "job_id.company")
    def _compute_display_name(self):
        for rec in self:
            title = rec.job_id.title or _("Job")
            company = rec.job_id.company or ""
            rec.display_name = "%s @ %s" % (title, company) if company else title

    @api.constrains("account_id")
    def _check_personal_account(self):
        for rec in self:
            if rec.account_id.account_type != "personal":
                raise ValidationError(
                    _("Applications must use a personal LinkedIn account, never PetSpot/company.")
                )

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
            if rec.state not in ("discovered", "shortlisted", "pack_ready"):
                raise UserError(
                    _("Prepare pack is only available before approval (discovered/shortlisted/pack ready).")
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
                }
            )
            rec.message_post(body=_("Application pack prepared (draft). Review and edit before approving."))
        return True

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
        for rec in self:
            if rec.state != "approved":
                raise UserError(_("Mark Applied only after Approved (and after you submit on LinkedIn)."))
            rec.write({"state": "applied", "applied_at": fields.Datetime.now()})
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
