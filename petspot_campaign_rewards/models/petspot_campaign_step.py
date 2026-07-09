# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PetspotCampaignStep(models.Model):
    _name = "petspot.campaign.step"
    _description = "PetSpot Campaign Step"
    _order = "campaign_id, sequence, id"

    campaign_id = fields.Many2one(
        "petspot.campaign",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    title = fields.Char(required=True, translate=True)
    title_ar = fields.Char(string="Title (Arabic)")
    content_type = fields.Selection(
        [
            ("knowledge", "Knowledge Article"),
            ("slide", "eLearning Slide"),
            ("survey", "Survey / Quiz"),
            ("combined", "Article + Quiz"),
        ],
        default="combined",
        required=True,
    )
    knowledge_article_id = fields.Many2one("knowledge.article", ondelete="set null")
    slide_id = fields.Many2one("slide.slide", ondelete="set null")
    survey_id = fields.Many2one("survey.survey", ondelete="set null")
    unlock_after_step_id = fields.Many2one(
        "petspot.campaign.step",
        string="Unlock After Step",
        ondelete="set null",
        domain="[('campaign_id', '=', campaign_id), ('id', '!=', id)]",
    )
    issue_reward = fields.Boolean(
        string="Issue Discount on Pass",
        help="When enabled, a unique discount code is generated after a successful quiz.",
    )
    reward_discount_percent = fields.Integer(
        string="Reward Discount %",
        default=0,
        help="10 for grand quiz, 15 for bonus step.",
    )
    reward_program_id = fields.Many2one("loyalty.program", ondelete="set null")
    facebook_message_template = fields.Text(
        string="Facebook Teaser",
        translate=True,
        help="Short teaser text for the scheduled Facebook post.",
    )
    facebook_post_id = fields.Many2one("social.media.post", readonly=True, copy=False)
    public_url = fields.Char(compute="_compute_public_url")
    survey_start_url = fields.Char(compute="_compute_step_content")
    quiz_question_count = fields.Integer(compute="_compute_step_content")
    intro_summary = fields.Char(compute="_compute_step_content")
    intro_body = fields.Html(compute="_compute_step_content", sanitize=False)
    intro_body_ar = fields.Html(compute="_compute_step_content", sanitize=False)

    @api.depends("campaign_id.code", "sequence")
    def _compute_public_url(self):
        base = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("web.base.url", "")
            .rstrip("/")
        )
        for rec in self:
            if rec.campaign_id.code:
                rec.public_url = f"{base}/campaign/{rec.campaign_id.code}/step/{rec.sequence}"
            else:
                rec.public_url = False

    @api.depends("survey_id", "sequence", "knowledge_article_id")
    def _compute_step_content(self):
        from odoo.addons.petspot_campaign_rewards.hooks import EPISODES_BY_SEQUENCE, _intro_snippet

        for rec in self:
            ep = EPISODES_BY_SEQUENCE.get(rec.sequence, {})
            rec.intro_summary = _intro_snippet(ep, 100)
            rec.intro_body = ep.get("article_html") or False
            rec.intro_body_ar = ep.get("intro_ar_html") or False
            if rec.survey_id:
                rec.quiz_question_count = len(
                    rec.survey_id.question_and_page_ids.filtered(lambda q: not q.is_page)
                )
                rec.survey_start_url = rec.survey_id.get_start_url()
            else:
                rec.quiz_question_count = 0
                rec.survey_start_url = False

    def get_redirect_url(self):
        self.ensure_one()
        if self.survey_id:
            return self.survey_id.get_start_url()
        if self.slide_id:
            return self.slide_id.website_url
        if self.knowledge_article_id:
            return f"/knowledge/article/{self.knowledge_article_id.id}"
        return self.public_url or "/"
