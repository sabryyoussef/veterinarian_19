# -*- coding: utf-8 -*-
import logging
import re
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PetspotCampaign(models.Model):
    _name = "petspot.campaign"
    _description = "PetSpot Marketing Campaign"
    _order = "date_start desc, id desc"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("active", "Active"),
            ("done", "Done"),
        ],
        default="draft",
        required=True,
    )
    date_start = fields.Date()
    date_end = fields.Date()
    pass_score_min = fields.Float(default=80.0, string="Minimum Pass Score (%)")
    discount_validity_days = fields.Integer(default=30, string="Code Validity (days)")
    loyalty_program_10_id = fields.Many2one(
        "loyalty.program",
        string="10% Reward Program",
        ondelete="restrict",
    )
    loyalty_program_15_id = fields.Many2one(
        "loyalty.program",
        string="15% Reward Program",
        ondelete="restrict",
    )
    slide_channel_id = fields.Many2one("slide.channel", string="eLearning Course", ondelete="set null")
    step_ids = fields.One2many("petspot.campaign.step", "campaign_id", string="Steps")
    step_count = fields.Integer(compute="_compute_stats")
    participant_count = fields.Integer(compute="_compute_stats")
    passed_count = fields.Integer(compute="_compute_stats")
    codes_issued_count = fields.Integer(compute="_compute_stats")
    codes_redeemed_count = fields.Integer(compute="_compute_stats")
    public_url = fields.Char(compute="_compute_public_url")

    _code_unique = models.Constraint("UNIQUE(code)", "Campaign code must be unique.")

    @api.depends("code")
    def _compute_public_url(self):
        base = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("web.base.url", "")
            .rstrip("/")
        )
        for rec in self:
            rec.public_url = f"{base}/campaign/{rec.code}" if rec.code else False

    @api.depends("step_ids", "step_ids.survey_id")
    def _compute_stats(self):
        UserInput = self.env["survey.user_input"]
        Card = self.env["loyalty.card"]
        for rec in self:
            rec.step_count = len(rec.step_ids)
            inputs = UserInput.search([("petspot_campaign_id", "=", rec.id)])
            rec.participant_count = len(inputs)
            rec.passed_count = len(inputs.filtered("scoring_success"))
            cards = Card.search([("petspot_campaign_id", "=", rec.id)])
            rec.codes_issued_count = len(cards)
            rec.codes_redeemed_count = len(cards.filtered(lambda c: c.use_count > 0))

    def action_activate(self):
        self.write({"state": "active"})

    def action_done(self):
        self.write({"state": "done"})

    def action_reset_draft(self):
        self.write({"state": "draft"})

    def action_open_surveys(self):
        self.ensure_one()
        survey_ids = self.step_ids.mapped("survey_id").ids
        return {
            "type": "ir.actions.act_window",
            "name": _("Campaign Surveys"),
            "res_model": "survey.survey",
            "view_mode": "list,form",
            "domain": [("id", "in", survey_ids)],
        }

    def action_open_loyalty_programs(self):
        self.ensure_one()
        program_ids = [
            pid
            for pid in (
                self.loyalty_program_10_id.id,
                self.loyalty_program_15_id.id,
            )
            if pid
        ]
        return {
            "type": "ir.actions.act_window",
            "name": _("Reward Programs"),
            "res_model": "loyalty.program",
            "view_mode": "list,form",
            "domain": [("id", "in", program_ids)],
        }

    def action_generate_facebook_posts(self):
        self.ensure_one()
        if not self.step_ids:
            raise UserError(_("Add campaign steps before generating Facebook posts."))
        Post = self.env["social.media.post"]
        page = Post._resolve_page_for_remote_account(
            int(
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("social_media_connector.default_remote_account_id", "9")
                or 0
            )
        )
        if not page:
            raise UserError(_("Configure default Facebook page in Social Media Connector settings."))

        steps = self.step_ids.sorted("sequence")
        slots = Post._compute_campaign_schedule_datetimes(len(steps))
        created = Post.browse()
        prefix = Post._get_campaign_prefix()

        for index, step in enumerate(steps):
            body = step.facebook_message_template or step.title
            link = step.public_url or ""
            utm = (
                f"?utm_source=facebook&utm_campaign={self.code}"
                f"&utm_content=step_{step.sequence}"
            )
            if link and "?" not in link:
                link = f"{link}{utm}"
            elif link:
                link = f"{link}&{utm.lstrip('?')}"

            message = f"{body}\n\n👉 {link}\n\n{Post._build_campaign_footer()}"
            title = f"{self.name} — Step {step.sequence}"
            if prefix:
                title = f"{prefix} {title}"

            post = Post.create(
                {
                    "title": title[:128],
                    "page_id": page.id,
                    "message": message,
                    "post_method": "scheduled",
                    "scheduled_date": slots[index] if index < len(slots) else False,
                    "state": "draft",
                }
            )
            step.facebook_post_id = post.id
            created |= post

        return {
            "type": "ir.actions.act_window",
            "name": _("Campaign Facebook Posts"),
            "res_model": "social.media.post",
            "view_mode": "list,form",
            "domain": [("id", "in", created.ids)],
            "target": "current",
        }

    @api.model
    def _normalize_phone(self, phone):
        digits = re.sub(r"\D", "", phone or "")
        if digits.startswith("0"):
            digits = "20" + digits[1:]
        elif digits and not digits.startswith("20"):
            digits = "20" + digits
        return digits

    def _get_reward_program_for_step(self, step):
        self.ensure_one()
        if step.reward_discount_percent >= 15 and self.loyalty_program_15_id:
            return self.loyalty_program_15_id
        if step.reward_discount_percent >= 10 and self.loyalty_program_10_id:
            return self.loyalty_program_10_id
        if step.reward_program_id:
            return step.reward_program_id
        return self.env["loyalty.program"]
