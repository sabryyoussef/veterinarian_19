# -*- coding: utf-8 -*-

from odoo import fields, models

LEAD_FIELD_SELECTION = [
    ("email_from", "Email filled in"),
    ("phone", "Phone filled in"),
    ("partner_name", "Company name filled in"),
    ("description", "Description / notes filled in"),
    ("street", "Address filled in"),
    ("country_id", "Country filled in"),
]

CHANNEL_SELECTION = [
    ("form", "Web Form"),
    ("ads", "Paid Ads"),
    ("email", "Email"),
    ("api", "API / Webhook"),
    ("other", "Other"),
]


class LeadEngineCampaignTemplate(models.Model):
    _name = "lead.engine.campaign.template"
    _description = "Lead Engine Campaign Template"
    _order = "sequence, name"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    channel = fields.Selection(selection=CHANNEL_SELECTION, default="form")
    description = fields.Text(help="Default source description — user can customise.")
    assign_min_score = fields.Integer(
        string="Min. score to assign",
        default=50,
        help="Leads that reach this score get routed to the default team / user.",
    )
    playbook_name = fields.Char(help="Suggested playbook name pre-filled in the wizard.")
    lead_name_prefix = fields.Char(
        string="Lead name prefix",
        default="New enquiry",
        help="Used as the lead subject when contacts are bulk-converted to leads. "
             "The contact name is appended automatically.",
    )
    default_email_template_id = fields.Many2one(
        comodel_name="mail.template",
        string="Default email template",
        domain="[('model_id.model', '=', 'crm.lead')]",
        help="Optional template suggested in the campaign wizard to send an initial email after creating leads.",
    )
    score_line_ids = fields.One2many(
        comodel_name="lead.engine.campaign.template.score.line",
        inverse_name="template_id",
        string="Score rules",
    )
    step_line_ids = fields.One2many(
        comodel_name="lead.engine.campaign.template.step.line",
        inverse_name="template_id",
        string="Playbook steps",
    )

    # ── Contact group ──────────────────────────────────────────────────────────
    contact_source = fields.Selection(
        selection=[
            ("none", "No contacts — leads arrive via form / API / CRM"),
            ("all", "All active contacts"),
            ("by_tag", "Contacts filtered by tag"),
            ("manual", "Manually selected contacts"),
        ],
        string="Contact source",
        default="none",
        required=True,
        help="Controls how the wizard pre-fills the contact list for this template.",
    )
    partner_category_ids = fields.Many2many(
        comodel_name="res.partner.category",
        relation="lead_engine_tpl_partner_category_rel",
        column1="template_id",
        column2="category_id",
        string="Filter by tags",
        help="All active contacts that carry ANY of these tags will be included.",
    )
    partner_ids = fields.Many2many(
        comodel_name="res.partner",
        relation="lead_engine_tpl_partner_rel",
        column1="template_id",
        column2="partner_id",
        string="Selected contacts",
        help="Fixed list of contacts included when this template is used.",
    )

    @property
    def has_contact_group(self):
        return self.contact_source != "none"

    note = fields.Text(string="Internal note")


class LeadEngineCampaignTemplateScoreLine(models.Model):
    _name = "lead.engine.campaign.template.score.line"
    _description = "Campaign Template Score Rule Line"
    _order = "template_id, sequence"

    template_id = fields.Many2one(
        comodel_name="lead.engine.campaign.template",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True, help="Short label for this rule.")
    lead_field = fields.Selection(
        selection=LEAD_FIELD_SELECTION,
        string="Lead field",
        help="Leave empty to create an 'Always' rule (base score for every lead).",
    )
    score_delta = fields.Integer(string="Points", default=10, required=True)


class LeadEngineCampaignTemplateStepLine(models.Model):
    _name = "lead.engine.campaign.template.step.line"
    _description = "Campaign Template Playbook Step Line"
    _order = "template_id, sequence"

    template_id = fields.Many2one(
        comodel_name="lead.engine.campaign.template",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    step_type = fields.Selection(
        selection=[
            ("create_activity", "Create activity"),
            ("send_email_template", "Send email"),
        ],
        required=True,
        default="create_activity",
    )
    delay_unit = fields.Selection(
        selection=[
            ("immediate", "Immediate"),
            ("hours", "Hours"),
            ("days", "Days"),
        ],
        required=True,
        default="immediate",
    )
    delay_amount = fields.Integer(default=0)
    activity_type_id = fields.Many2one(
        comodel_name="mail.activity.type",
        string="Activity type",
    )
    activity_summary = fields.Char(string="Activity summary")
    activity_note = fields.Html(string="Activity note / instructions")
    mail_template_id = fields.Many2one(
        comodel_name="mail.template",
        string="Email template",
        domain=[("model", "=", "crm.lead")],
    )
