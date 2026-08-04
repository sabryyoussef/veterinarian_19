# -*- coding: utf-8 -*-
"""Verified answer library for personal job applications (account id=2 only)."""

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LinkedinAnswerLibrary(models.Model):
    _name = "linkedin.answer.library"
    _description = "Verified Job Application Answer"
    _inherit = ["mail.thread"]
    _order = "sequence, id"
    _rec_name = "display_name"

    name = fields.Char(string="Fact key", required=True, index=True, tracking=True)
    display_name = fields.Char(compute="_compute_display_name", store=True)
    account_id = fields.Many2one(
        "linkedin.account",
        string="Personal account",
        required=True,
        ondelete="cascade",
        index=True,
        domain="[('account_type', '=', 'personal')]",
        tracking=True,
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    category = fields.Selection(
        [
            ("identity", "Identity"),
            ("contact", "Contact"),
            ("experience", "Experience"),
            ("compensation", "Compensation"),
            ("availability", "Availability"),
            ("authorization", "Work authorization"),
            ("documents", "Documents"),
            ("intro", "Introduction"),
            ("other", "Other"),
        ],
        default="other",
        required=True,
        index=True,
    )
    answer_text = fields.Text(string="Verified answer", required=True, tracking=True)
    question_variants = fields.Text(
        string="Question variants",
        help="One pattern/phrase per line. Used to map employer questions to this fact.",
    )
    is_mandatory_known = fields.Boolean(
        default=True,
        help="When False, matching mandatory questions become missing_fact.",
    )
    notes = fields.Text(string="Internal notes")

    _sql_constraints = [
        (
            "answer_library_account_name_uniq",
            "unique(account_id, name)",
            "Answer fact key must be unique per account.",
        )
    ]

    @api.depends("name", "answer_text")
    def _compute_display_name(self):
        for rec in self:
            snippet = (rec.answer_text or "")[:40]
            rec.display_name = "%s: %s" % (rec.name, snippet)

    @api.constrains("account_id")
    def _check_personal_account(self):
        for rec in self:
            if rec.account_id.account_type != "personal":
                raise ValidationError(
                    _("Answer library entries must belong to a personal account.")
                )
            if rec.account_id.id == 1:
                raise ValidationError(_("Company account id=1 cannot own answer library rows."))

    @api.model
    def get_verified_map(self, account_id):
        """Return {fact_key: answer_text} for mapping — never invents."""
        if int(account_id or 0) == 1:
            raise UserError(_("Refusing answer library for company account id=1."))
        rows = self.search(
            [("account_id", "=", account_id), ("active", "=", True), ("is_mandatory_known", "=", True)]
        )
        return {r.name: r.answer_text for r in rows}

    @api.model
    def get_variant_map(self, account_id):
        """Return list of (variant_phrase_lower, fact_key, answer_text)."""
        if int(account_id or 0) == 1:
            raise UserError(_("Refusing answer library for company account id=1."))
        out = []
        for rec in self.search([("account_id", "=", account_id), ("active", "=", True)]):
            variants = (rec.question_variants or "").splitlines()
            variants = [v.strip() for v in variants if v.strip()]
            if not variants:
                variants = [rec.name.replace("_", " ")]
            for v in variants:
                out.append(
                    {
                        "variant": v.lower(),
                        "fact_key": rec.name,
                        "answer": rec.answer_text if rec.is_mandatory_known else None,
                        "known": bool(rec.is_mandatory_known),
                    }
                )
        return out

    @api.model
    def seed_personal_account_defaults(self, account_id=2):
        """Idempotent seed of verified facts for personal account id=2."""
        account = self.env["linkedin.account"].browse(int(account_id)).exists()
        if not account or account.account_type != "personal" or account.id == 1:
            raise UserError(_("Can only seed answer library for personal account id=2."))
        defaults = [
            ("legal_name", "identity", "Sabry Youssef", "full name\nlegal name\nyour name\napplicant name"),
            ("email", "contact", "vendorah2@gmail.com", "email\ne-mail\nemail address"),
            ("phone", "contact", "+201000059085", "phone\nmobile\ntelephone\nwhatsapp"),
            ("location", "contact", "Egypt", "location\ncity\ncountry\ncurrent location\nbased in"),
            ("years_odoo", "experience", "8+", "years of odoo\nodoo experience\nyears with odoo"),
            ("years_experience", "experience", "8+", "years of experience\nexperience level\ntotal experience"),
            ("skills_python", "experience", "Yes", "python\npython experience"),
            ("skills_postgresql", "experience", "Yes", "postgresql\npostgres\nsql"),
            ("skills_odoo", "experience", "Yes", "odoo\nerp odoo"),
            (
                "current_salary",
                "compensation",
                "USD 900/month",
                "current salary\npresent salary\ncurrent ctc\ncurrent pay",
            ),
            ("salary_expectation", "compensation", "USD 1000/month", "salary\ncompensation\nexpected pay\nctc"),
            ("notice_period", "availability", "1 month", "notice period\navailability\nwhen can you start"),
            ("onsite_available", "availability", "Yes", "onsite\non-site\nwilling to work onsite"),
            ("relocation", "availability", "Yes", "relocation\nrelocate\nwilling to relocate"),
            (
                "eu_work_authorization",
                "authorization",
                "No",
                "eu work authorization\nbelgium work authorization\nright to work in eu\nlegally authorized",
            ),
            (
                "visa_sponsorship_required",
                "authorization",
                "Yes",
                "visa sponsorship\nwork permit\nrequire sponsorship\nneed visa",
            ),
            (
                "professional_intro",
                "intro",
                "Senior Odoo developer with 8+ years of experience in Python, PostgreSQL, "
                "custom modules, integrations, and production-safe delivery.",
                "about yourself\nintroduction\ncover letter\nwhy do you want\nsummary",
            ),
            (
                "cv_verified",
                "documents",
                "default_verified_cv",
                "resume\ncv\ncurriculum vitae\nattach resume",
            ),
        ]
        Answer = self.sudo()
        for seq, (key, cat, text, variants) in enumerate(defaults, start=1):
            existing = Answer.search(
                [("account_id", "=", account.id), ("name", "=", key)], limit=1
            )
            vals = {
                "name": key,
                "account_id": account.id,
                "category": cat,
                "answer_text": text,
                "question_variants": variants,
                "sequence": seq * 10,
                "is_mandatory_known": True,
                "active": True,
            }
            if existing:
                existing.write(vals)
            else:
                Answer.create(vals)
        return True
