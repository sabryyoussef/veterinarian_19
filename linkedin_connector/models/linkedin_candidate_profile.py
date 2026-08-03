# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LinkedinCandidateProfile(models.Model):
    _name = "linkedin.candidate.profile"
    _description = "Job Hunt Candidate Profile (truthful facts only)"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char(required=True, default="Personal candidate profile")
    active = fields.Boolean(default=True)
    account_id = fields.Many2one(
        "linkedin.account",
        string="Personal account",
        required=True,
        ondelete="cascade",
        index=True,
        domain="[('account_type', '=', 'personal')]",
        tracking=True,
    )
    partner_id = fields.Many2one("res.partner", string="Contact reference")
    email = fields.Char(string="Email (optional)")
    phone = fields.Char(string="Phone (optional)")
    years_odoo_experience = fields.Float(string="Years of Odoo experience")
    technical_skills = fields.Text(
        string="Technical skills",
        help="Comma/newline list. Leave blank if unconfirmed.",
    )
    functional_skills = fields.Text(string="Functional skills")
    salary_expectation = fields.Char(
        string="Salary expectation",
        help="Leave unset until Sabry confirms a truthful value.",
    )
    notice_period = fields.Char(
        string="Notice period",
        help="Leave unset until confirmed.",
    )
    uae_relocation = fields.Selection(
        [
            ("unset", "Unset"),
            ("yes", "Yes"),
            ("no", "No"),
            ("negotiable", "Negotiable"),
        ],
        default="unset",
        required=True,
        string="UAE relocation",
    )
    visa_sponsorship = fields.Selection(
        [
            ("unset", "Unset"),
            ("required", "Required"),
            ("not_required", "Not required"),
            ("has_visa", "Already has visa"),
        ],
        default="unset",
        required=True,
        string="Visa sponsorship",
    )
    work_mode_preference = fields.Selection(
        [
            ("unset", "Unset"),
            ("remote", "Remote"),
            ("hybrid", "Hybrid"),
            ("onsite", "On-site"),
            ("any", "Any"),
        ],
        default="unset",
        required=True,
    )
    github_url = fields.Char(string="GitHub URL")
    linkedin_url = fields.Char(string="LinkedIn profile URL")
    portfolio_url = fields.Char(string="Portfolio URL")
    standard_answers_json = fields.Text(
        string="Standard screening answers (JSON)",
        help="Only store answers Sabry has explicitly confirmed. Never invent.",
    )
    notes = fields.Text(string="Internal notes")

    @api.constrains("account_id")
    def _check_personal_account(self):
        for rec in self:
            if rec.account_id.account_type != "personal":
                raise ValidationError(
                    _("Candidate profile must belong to a personal LinkedIn account.")
                )

    def to_sanitized_json(self):
        """Facts for Dify — omit unset sensitive fields rather than inventing."""
        self.ensure_one()
        data = {
            "profile_id": self.id,
            "account_id": self.account_id.id,
            "name": self.name,
            "years_odoo_experience": self.years_odoo_experience or None,
            "technical_skills": self.technical_skills or None,
            "functional_skills": self.functional_skills or None,
            "work_mode_preference": (
                self.work_mode_preference if self.work_mode_preference != "unset" else None
            ),
            "github_url": self.github_url or None,
            "linkedin_url": self.linkedin_url or None,
            "portfolio_url": self.portfolio_url or None,
        }
        # Sensitive: only include when explicitly set
        if self.salary_expectation:
            data["salary_expectation"] = self.salary_expectation
        if self.notice_period:
            data["notice_period"] = self.notice_period
        if self.uae_relocation != "unset":
            data["uae_relocation"] = self.uae_relocation
        if self.visa_sponsorship != "unset":
            data["visa_sponsorship"] = self.visa_sponsorship
        if self.standard_answers_json:
            data["standard_answers_json"] = self.standard_answers_json
        return {k: v for k, v in data.items() if v is not None}
