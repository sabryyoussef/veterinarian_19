# -*- coding: utf-8 -*-

import re

from odoo import api, fields, models
from odoo.exceptions import UserError

from .lead_engine_campaign_template import LEAD_FIELD_SELECTION, CHANNEL_SELECTION

_SCENARIO_SCORES = {
    # base score (points) + per-field rules
    "basic_contact": [
        {"name": "Base score",            "lead_field": False,            "score_delta": 10},
        {"name": "Email provided",        "lead_field": "email_from",     "score_delta": 20},
        {"name": "Phone provided",        "lead_field": "phone",          "score_delta": 15},
    ],
    "b2b_profile": [
        {"name": "Base score",            "lead_field": False,            "score_delta": 10},
        {"name": "Email provided",        "lead_field": "email_from",     "score_delta": 20},
        {"name": "Phone provided",        "lead_field": "phone",          "score_delta": 15},
        {"name": "Company name known",    "lead_field": "partner_name",   "score_delta": 15},
        {"name": "Country filled in",     "lead_field": "country_id",     "score_delta": 10},
    ],
    "full_profile": [
        {"name": "Base score",            "lead_field": False,            "score_delta": 10},
        {"name": "Email provided",        "lead_field": "email_from",     "score_delta": 20},
        {"name": "Phone provided",        "lead_field": "phone",          "score_delta": 15},
        {"name": "Company name known",    "lead_field": "partner_name",   "score_delta": 15},
        {"name": "Address filled in",     "lead_field": "street",         "score_delta": 10},
        {"name": "Country filled in",     "lead_field": "country_id",     "score_delta": 10},
        {"name": "Description / notes",   "lead_field": "description",    "score_delta": 10},
    ],
    "email_only": [
        {"name": "Base score",            "lead_field": False,            "score_delta": 20},
        {"name": "Email provided",        "lead_field": "email_from",     "score_delta": 30},
    ],
    "strict_qualify": [
        {"name": "Base score",            "lead_field": False,            "score_delta": 5},
        {"name": "Email provided",        "lead_field": "email_from",     "score_delta": 25},
        {"name": "Phone provided",        "lead_field": "phone",          "score_delta": 20},
        {"name": "Company name known",    "lead_field": "partner_name",   "score_delta": 20},
        {"name": "Description given",     "lead_field": "description",    "score_delta": 15},
        {"name": "Address filled in",     "lead_field": "street",         "score_delta": 10},
        {"name": "Country filled in",     "lead_field": "country_id",     "score_delta": 5},
    ],
}

_SCENARIO_STEPS = {
    # ── Quick Response ───────────────────────────────────────────────────────
    "quick_response": [
        {"name": "Call to introduce yourself",      "step_type": "create_activity", "delay_unit": "immediate", "delay_amount": 0, "activity_summary": "First contact call — qualify interest and gather basic info."},
        {"name": "Send intro email",                "step_type": "send_email_template", "delay_unit": "days",      "delay_amount": 1},
        {"name": "Follow-up call",                  "step_type": "create_activity", "delay_unit": "days",      "delay_amount": 3, "activity_summary": "Check if they received the email and answer any questions."},
    ],
    # ── Lead Nurture ─────────────────────────────────────────────────────────
    "nurture": [
        {"name": "Send welcome email",              "step_type": "send_email_template", "delay_unit": "immediate", "delay_amount": 0},
        {"name": "Discovery call",                  "step_type": "create_activity", "delay_unit": "days",      "delay_amount": 3, "activity_summary": "30-min call to understand their pain points and timeline."},
        {"name": "Send case study",                 "step_type": "send_email_template", "delay_unit": "days",      "delay_amount": 7},
        {"name": "Product demo / meeting",          "step_type": "create_activity", "delay_unit": "days",      "delay_amount": 14, "activity_summary": "Schedule and run a live demo tailored to their needs."},
        {"name": "Final check-in call",             "step_type": "create_activity", "delay_unit": "days",      "delay_amount": 30, "activity_summary": "Confirm next steps, handle objections, and push towards decision."},
    ],
    # ── Trade Show Follow-up ─────────────────────────────────────────────────
    "trade_show": [
        {"name": "Send thank-you email",            "step_type": "send_email_template", "delay_unit": "immediate", "delay_amount": 0},
        {"name": "Qualification call",              "step_type": "create_activity", "delay_unit": "days",      "delay_amount": 2, "activity_summary": "Confirm their interest, gather budget and timeline info."},
        {"name": "Send tailored proposal",          "step_type": "send_email_template", "delay_unit": "days",      "delay_amount": 7},
        {"name": "Follow-up call — decision?",      "step_type": "create_activity", "delay_unit": "days",      "delay_amount": 14, "activity_summary": "Close the loop — are they ready to move forward?"},
    ],
    # ── Cold Email Outreach ──────────────────────────────────────────────────
    "cold_email": [
        {"name": "Send cold outreach email #1",     "step_type": "send_email_template", "delay_unit": "immediate", "delay_amount": 0},
        {"name": "Send follow-up email #2",         "step_type": "send_email_template", "delay_unit": "days",      "delay_amount": 3},
        {"name": "Cold call",                       "step_type": "create_activity", "delay_unit": "days",      "delay_amount": 7, "activity_summary": "First voice contact — reference the emails, qualify quickly."},
        {"name": "Final break-up email",            "step_type": "send_email_template", "delay_unit": "days",      "delay_amount": 14},
    ],
    # ── Enterprise / High-Value ──────────────────────────────────────────────
    "enterprise": [
        {"name": "Executive intro call",            "step_type": "create_activity", "delay_unit": "immediate", "delay_amount": 0, "activity_summary": "C-level introduction — understand strategic priorities."},
        {"name": "Schedule discovery workshop",     "step_type": "create_activity", "delay_unit": "days",      "delay_amount": 1, "activity_summary": "Book a 90-min workshop with their key stakeholders."},
        {"name": "Send detailed proposal / RFP",    "step_type": "send_email_template", "delay_unit": "days",      "delay_amount": 7},
        {"name": "Negotiation call",                "step_type": "create_activity", "delay_unit": "days",      "delay_amount": 14, "activity_summary": "Discuss pricing, SLAs, and contract terms."},
        {"name": "Legal / contract review",         "step_type": "create_activity", "delay_unit": "days",      "delay_amount": 21, "activity_summary": "Coordinate with their legal team, handle redlines."},
        {"name": "Closing call & sign-off",         "step_type": "create_activity", "delay_unit": "days",      "delay_amount": 30, "activity_summary": "Final sign-off, kick-off date, and onboarding scheduling."},
    ],
}

_DEFAULT_EMAIL_TEMPLATE_BY_STEP_NAME = {
    "Send intro email": "Follow-up - Checking In",
    "Send welcome email": "Follow-up - Checking In",
    "Send case study": "Project Demo Invitation",
    "Send thank-you email": "Follow-up - Checking In",
    "Send tailored proposal": "Module Presentation",
    "Send cold outreach email #1": "Idea Discussion - Discovery Call",
    "Send follow-up email #2": "Follow-up - Checking In",
    "Final break-up email": "Product Walkthrough Video",
    "Send detailed proposal / RFP": "Module Presentation",
}

_WIZARD_STEPS = [
    ("step_campaign", "Campaign"),
    ("step_scoring", "Scoring"),
    ("step_assignment", "Assignment"),
    ("step_playbook", "Playbook"),
    ("step_contacts", "Contacts"),
    ("step_review", "Review"),
]
_STEP_ORDER = [s[0] for s in _WIZARD_STEPS]


def _slugify(text):
    """Convert a human label to an UPPER_SNAKE_CASE code (max 24 chars)."""
    code = re.sub(r"[^A-Za-z0-9]+", "_", text or "").upper().strip("_")
    return code[:24].rstrip("_") or "CAMPAIGN"


class LeadEngineCampaignWizard(models.TransientModel):
    _name = "lead.engine.campaign.wizard"
    _description = "Lead Engine Campaign Setup Wizard"

    def init(self):
        # Keep existing wizard rows compatible when required fields are tightened.
        self.env.cr.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'lead_engine_campaign_wizard'
                      AND column_name = 'assignment_mode'
                ) THEN
                    UPDATE lead_engine_campaign_wizard
                    SET assignment_mode = 'auto_score'
                    WHERE assignment_mode IS NULL;

                    ALTER TABLE lead_engine_campaign_wizard
                    ALTER COLUMN assignment_mode SET NOT NULL;
                END IF;
            EXCEPTION
                WHEN undefined_table THEN
                    NULL;
            END
            $$;
            """
        )

    # ── Progress ──────────────────────────────────────────────────────────────
    state = fields.Selection(
        selection=_WIZARD_STEPS,
        default="step_campaign",
        required=True,
    )

    # ── Step 1 — Campaign ─────────────────────────────────────────────────────
    template_id = fields.Many2one(
        comodel_name="lead.engine.campaign.template",
        string="Start from template",
        help="Pick a template to pre-fill scoring rules and playbook steps.",
    )
    campaign_name = fields.Char(string="Campaign name", required=True)
    channel = fields.Selection(selection=CHANNEL_SELECTION, default="form", required=True)
    source_code = fields.Char(
        string="Source code",
        help="Auto-generated from the campaign name. Must be unique per company.",
    )
    default_team_id = fields.Many2one(comodel_name="crm.team", string="Default sales team")
    default_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Default salesperson",
        domain="[('share', '=', False)]",
    )
    description = fields.Text(string="Source description")

    # ── Step 2 — Scoring ──────────────────────────────────────────────────────
    score_scenario = fields.Selection(
        selection=[
            ("basic_contact", "Basic Contact - email + phone (45 pts total)"),
            ("b2b_profile",   "B2B Profile - email + phone + company + country (70 pts)"),
            ("full_profile",  "Full Profile - all fields (90 pts)"),
            ("email_only",    "Email Only - simple inbound (50 pts)"),
            ("strict_qualify","Strict Qualification - high threshold (100 pts)"),
        ],
        string="Load a scoring scenario",
        help="Pick a preset to instantly fill the rules below. You can edit afterwards.",
    )
    score_line_ids = fields.One2many(
        comodel_name="lead.engine.campaign.wizard.score.line",
        inverse_name="wizard_id",
        string="Score rules",
    )

    # ── Step 3 — Assignment ───────────────────────────────────────────────────
    assignment_mode = fields.Selection(
        selection=[
            ("auto_score", "Auto assign by score"),
            ("manual", "Manual assign all leads"),
            ("none", "No special assignment"),
        ],
        string="Assignment mode",
        default="auto_score",
        required=True,
        help="Choose whether leads are routed by score threshold, assigned directly to one owner, or left with only the default source owner.",
    )
    assign_min_score = fields.Integer(
        string="Minimum score to assign",
        default=50,
        help="Leads that reach or exceed this score will be routed automatically.",
    )
    assign_team_id = fields.Many2one(comodel_name="crm.team", string="Assign to team")
    assign_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Assign to salesperson",
        domain="[('share', '=', False)]",
    )

    # ── Step 4 — Playbook ─────────────────────────────────────────────────────
    playbook_scenario = fields.Selection(
        selection=[
            ("quick_response", "Quick Response - 3 steps (call - email - follow-up)"),
            ("nurture", "Lead Nurture — 5 steps over 30 days"),
            ("trade_show", "Trade Show Follow-up — 4 steps"),
            ("cold_email", "Cold Email Outreach — 4 email + call steps"),
            ("enterprise", "Enterprise / High-Value — 6 steps over 30 days"),
        ],
        string="Load a scenario",
        help="Pick a ready-made step sequence. It will overwrite any steps already in the list.",
    )
    playbook_choice = fields.Selection(
        selection=[
            ("new", "Create a new playbook"),
            ("existing", "Use an existing playbook"),
            ("none", "No playbook for now"),
        ],
        default="new",
        required=True,
        string="Playbook",
    )
    playbook_id = fields.Many2one(
        comodel_name="lead.engine.playbook",
        string="Existing playbook",
        domain="[('active', '=', True)]",
    )
    existing_playbook_step_ids = fields.One2many(
        comodel_name="lead.engine.playbook.step",
        related="playbook_id.step_ids",
        string="Existing playbook steps",
        readonly=False,
    )
    playbook_name = fields.Char(string="New playbook name")
    playbook_auto_start = fields.Boolean(
        string="Auto-start after qualification",
        default=True,
        help="The playbook runs automatically when a new lead is qualified via this source.",
    )
    step_line_ids = fields.One2many(
        comodel_name="lead.engine.campaign.wizard.step.line",
        inverse_name="wizard_id",
        string="Playbook steps",
    )

    # ── Step 5 — Contacts ─────────────────────────────────────────────────────
    create_leads_from_contacts = fields.Boolean(
        string="Create leads from a contact list",
        default=False,
        help="Select contacts below to bulk-create CRM leads for this campaign.",
    )
    target_partner_ids = fields.Many2many(
        comodel_name="res.partner",
        relation="lead_engine_campaign_wizard_partner_rel",
        column1="wizard_id",
        column2="partner_id",
        string="Target contacts",
        help="A lead will be created for each contact and the full qualification "
             "pipeline (scoring, assignment, playbook) will run automatically.",
    )
    send_initial_email = fields.Boolean(
        string="Send initial email after lead creation",
        default=False,
        help="If enabled, sends the selected email template once to each newly created lead.",
    )
    email_template_id = fields.Many2one(
        comodel_name="mail.template",
        string="Email template",
        domain="[('model_id.model', '=', 'crm.lead')]",
        help="Template used for initial outreach emails to leads created from selected contacts.",
    )
    lead_name_prefix = fields.Char(
        string="Lead name / subject",
        default="New enquiry",
        help="Used as the lead subject. The contact name is appended automatically.",
    )

    # ── Step 6 — Review (read-only summary computed at launch step) ───────────
    review_source_code = fields.Char(string="Generated code", readonly=True)
    review_score_rules = fields.Integer(string="Rules to create", readonly=True)
    review_playbook = fields.Char(string="Playbook name", readonly=True)
    review_steps = fields.Integer(string="Steps to create", readonly=True)
    review_contacts = fields.Integer(string="Leads to create", readonly=True)

    def _apply_score_scenario_rules(self, scenario_key):
        """Fill score lines from a built-in scoring preset."""
        self.ensure_one()
        rules = _SCENARIO_SCORES.get(scenario_key, [])
        self.score_scenario = scenario_key
        self.score_line_ids = [(5, 0, 0)] + [(0, 0, rule) for rule in rules]

    def _ensure_default_score_rules(self):
        """Guarantee Step 2 never opens empty when no template scoring exists."""
        self.ensure_one()
        if self.score_line_ids:
            return
        # Balanced default for B2B outreach: email, phone, company, country.
        self._apply_score_scenario_rules("b2b_profile")

    # ── Template application ──────────────────────────────────────────────────
    @api.onchange("template_id")
    def _onchange_template_id(self):
        tpl = self.template_id
        if not tpl:
            return
        base_campaign_name = self.campaign_name or tpl.name or "Campaign"
        self.channel = tpl.channel
        self.description = tpl.description
        self.assign_min_score = tpl.assign_min_score
        self.playbook_name = tpl.playbook_name or (base_campaign_name + " Playbook")
        self.lead_name_prefix = tpl.lead_name_prefix or self.lead_name_prefix
        self.email_template_id = tpl.default_email_template_id
        self.send_initial_email = bool(tpl.default_email_template_id)
        if tpl.score_line_ids:
            self.score_scenario = False
            self.score_line_ids = [(5, 0, 0)] + [
                (0, 0, {
                    "name": line.name,
                    "lead_field": line.lead_field,
                    "score_delta": line.score_delta,
                })
                for line in tpl.score_line_ids
            ]
        else:
            self._ensure_default_score_rules()
        self.step_line_ids = [(5, 0, 0)] + [
            (0, 0, {
                "sequence": line.sequence,
                "name": line.name,
                "step_type": line.step_type,
                "delay_unit": line.delay_unit,
                "delay_amount": line.delay_amount,
                "activity_type_id": line.activity_type_id.id,
                "activity_summary": line.activity_summary,
                "activity_note": line.activity_note,
                "mail_template_id": line.mail_template_id.id,
            })
            for line in tpl.step_line_ids
        ]

        # ── Contact group ─────────────────────────────────────────────────────
        src = tpl.contact_source
        if src == "none":
            self.create_leads_from_contacts = False
            self.target_partner_ids = [(5, 0, 0)]
        elif src == "all":
            self.create_leads_from_contacts = True
            all_partners = self.env["res.partner"].search([
                ("active", "=", True), ("is_company", "=", False),
            ])
            self.target_partner_ids = [(6, 0, all_partners.ids)]
        elif src == "by_tag":
            self.create_leads_from_contacts = True
            tagged = self.env["res.partner"].search([
                ("category_id", "in", tpl.partner_category_ids.ids),
                ("active", "=", True),
            ]) if tpl.partner_category_ids else self.env["res.partner"]
            self.target_partner_ids = [(6, 0, tagged.ids)]
        elif src == "manual":
            self.create_leads_from_contacts = bool(tpl.partner_ids)
            self.target_partner_ids = [(6, 0, tpl.partner_ids.ids)]

    @api.onchange("campaign_name")
    def _onchange_campaign_name(self):
        if self.campaign_name and not self.source_code:
            self.source_code = _slugify(self.campaign_name)
        if self.campaign_name and not self.playbook_name:
            self.playbook_name = self.campaign_name

    @api.onchange("source_code")
    def _onchange_source_code(self):
        if self.source_code:
            self.source_code = _slugify(self.source_code)

    @api.onchange("score_scenario")
    def _onchange_score_scenario(self):
        if not self.score_scenario:
            return
        self._apply_score_scenario_rules(self.score_scenario)

    @api.onchange("playbook_scenario")
    def _onchange_playbook_scenario(self):
        if not self.playbook_scenario:
            return
        self.playbook_choice = "new"
        steps = _SCENARIO_STEPS.get(self.playbook_scenario, [])
        template_name_to_id = {}
        needed_template_names = {
            _DEFAULT_EMAIL_TEMPLATE_BY_STEP_NAME.get(s.get("name"))
            for s in steps
            if s.get("step_type") == "send_email_template"
        } - {None}
        if needed_template_names:
            templates = self.env["mail.template"].search([
                ("model", "=", "crm.lead"),
                ("name", "in", list(needed_template_names)),
            ])
            template_name_to_id = {tpl.name: tpl.id for tpl in templates}
        self.step_line_ids = [(5, 0, 0)] + [
            (
                0,
                0,
                dict(
                    s,
                    sequence=(i + 1) * 10,
                    mail_template_id=template_name_to_id.get(
                        _DEFAULT_EMAIL_TEMPLATE_BY_STEP_NAME.get(s.get("name"))
                    ) if s.get("step_type") == "send_email_template" else False,
                ),
            )
            for i, s in enumerate(steps)
        ]

    # ── Navigation ────────────────────────────────────────────────────────────
    def action_next(self):
        self._validate_current_step()
        idx = _STEP_ORDER.index(self.state)
        if idx < len(_STEP_ORDER) - 1:
            next_state = _STEP_ORDER[idx + 1]
            if next_state == "step_scoring":
                self._ensure_default_score_rules()
            if next_state == "step_review":
                self._compute_review()
            self.state = next_state
        return self._reload()

    def action_back(self):
        idx = _STEP_ORDER.index(self.state)
        if idx > 0:
            self.state = _STEP_ORDER[idx - 1]
        return self._reload()

    def _reload(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
            "context": dict(self.env.context),
        }

    def _compute_review(self):
        code = self.source_code or _slugify(self.campaign_name)
        self.review_source_code = code
        self.review_score_rules = len(self.score_line_ids)
        if self.playbook_choice == "new":
            self.review_playbook = self.playbook_name or "(unnamed)"
            self.review_steps = len(self.step_line_ids)
        elif self.playbook_choice == "existing":
            self.review_playbook = self.playbook_id.name if self.playbook_id else "—"
            self.review_steps = len(self.playbook_id.step_ids) if self.playbook_id else 0
        else:
            self.review_playbook = "None"
            self.review_steps = 0
        self.review_contacts = len(self.target_partner_ids) if self.create_leads_from_contacts else 0

    # ── Validation ────────────────────────────────────────────────────────────
    def _validate_current_step(self):
        if self.state == "step_campaign":
            if not self.campaign_name:
                raise UserError(self.env._("Please enter a campaign name."))
            if not self.source_code:
                raise UserError(self.env._("Please provide a source code."))
            existing = self.env["lead.engine.source"].search([
                ("code", "=", self.source_code),
                ("company_id", "=", self.env.company.id),
            ], limit=1)
            if existing:
                raise UserError(
                    self.env._("Source code '%s' is already in use. Choose a different one.")
                    % self.source_code
                )

        if self.state == "step_assignment":
            if self.assignment_mode == "manual" and not (self.assign_team_id or self.assign_user_id):
                raise UserError(
                    self.env._("Choose a team or salesperson for manual assignment.")
                )
            if self.assignment_mode == "auto_score" and (self.assign_team_id or self.assign_user_id) and self.assign_min_score < 0:
                raise UserError(self.env._("Minimum score to assign cannot be negative."))

        if self.state == "step_playbook" and self.playbook_choice == "new":
            if not self.playbook_name:
                raise UserError(self.env._("Please enter a playbook name."))

    # ── Launch ────────────────────────────────────────────────────────────────
    def action_launch(self):
        self.ensure_one()

        # 1 — Source
        source = self.env["lead.engine.source"].create({
            "name": self.campaign_name,
            "code": self.source_code or _slugify(self.campaign_name),
            "channel": self.channel,
            "description": self.description,
            "default_team_id": self.default_team_id.id or False,
            "default_user_id": self.default_user_id.id or False,
            "auto_score": True,
            "auto_assign": self.assignment_mode != "none",
        })

        # 2 — Score rules
        for seq, line in enumerate(self.score_line_ids, start=10):
            rule_type = "always" if not line.lead_field else "field"
            self.env["lead.engine.score.rule"].create({
                "name": "[%s] %s" % (source.code, line.name),
                "sequence": seq,
                "rule_type": rule_type,
                "field_name": line.lead_field or False,
                "operator": "set" if rule_type == "field" else False,
                "score_delta": line.score_delta,
                "source_id": source.id,
            })

        # 3 — Assignment rule
        if self.assignment_mode == "auto_score" and (self.assign_team_id or self.assign_user_id):
            self.env["lead.engine.assignment.rule"].create({
                "name": "[%s] Auto-assign" % source.code,
                "source_id": source.id,
                "min_score": self.assign_min_score,
                "team_id": self.assign_team_id.id or False,
                "user_id": self.assign_user_id.id or False,
            })
        # Manual mode uses the assignment target as the source default owner.
        if self.assignment_mode == "manual":
            source.write({
                "default_team_id": (self.assign_team_id or self.default_team_id).id or False,
                "default_user_id": (self.assign_user_id or self.default_user_id).id or False,
            })

        # 4 — Playbook
        playbook = self.env["lead.engine.playbook"]
        if self.playbook_choice == "new" and self.playbook_name:
            pb_code = _slugify(self.playbook_name)
            # Ensure uniqueness
            existing_pb = self.env["lead.engine.playbook"].search([
                ("code", "=", pb_code), ("company_id", "=", self.env.company.id)
            ], limit=1)
            if existing_pb:
                pb_code = pb_code[:20] + "_" + source.code[:3]
            playbook = self.env["lead.engine.playbook"].create({
                "name": self.playbook_name,
                "code": pb_code,
                "description": "Auto-created for campaign: %s" % self.campaign_name,
            })
            for line in self.step_line_ids.sorted("sequence"):
                vals = {
                    "playbook_id": playbook.id,
                    "sequence": line.sequence,
                    "name": line.name,
                    "step_type": line.step_type,
                    "delay_unit": line.delay_unit,
                    "delay_amount": line.delay_amount,
                }
                if line.step_type == "create_activity":
                    vals.update({
                        "activity_type_id": line.activity_type_id.id,
                        "activity_summary": line.activity_summary,
                        "activity_note": line.activity_note,
                    })
                elif line.step_type == "send_email_template":
                    vals["mail_template_id"] = line.mail_template_id.id
                self.env["lead.engine.playbook.step"].create(vals)
        elif self.playbook_choice == "existing":
            playbook = self.playbook_id

        # 5 — Link playbook to source
        if playbook:
            source.write({
                "playbook_id": playbook.id,
                "playbook_auto_start": self.playbook_auto_start,
            })

        # 6 — Bulk-create leads from contact list
        created_leads = self.env["crm.lead"]
        if self.create_leads_from_contacts and self.target_partner_ids:
            pipeline = self.env["lead.engine.qualification.pipeline"]
            pb_svc = self.env["lead.engine.playbook.service"]
            prefix = self.lead_name_prefix or self.campaign_name
            for partner in self.target_partner_ids:
                lead = self.env["crm.lead"].create({
                    "name": "%s — %s" % (prefix, partner.name),
                    "partner_id": partner.id,
                    "partner_name": partner.company_name or partner.name or False,
                    "contact_name": partner.name if not partner.is_company else False,
                    "email_from": partner.email or False,
                    "phone": partner.phone or False,
                    "lead_engine_source_id": source.id,
                    "le_channel": source.channel,
                    "type": "lead",
                    "team_id": source.default_team_id.id or False,
                    "user_id": source.default_user_id.id or False,
                })
                pipeline.run_qualification_pipeline(lead)
                if self.assignment_mode == "manual" and (self.assign_team_id or self.assign_user_id):
                    lead.write({
                        "team_id": (self.assign_team_id or source.default_team_id).id or False,
                        "user_id": (self.assign_user_id or source.default_user_id).id or False,
                    })
                pb_svc.try_auto_start_after_qualification(lead)
                created_leads |= lead

        # 7 — Optional initial outreach email for newly created leads
        if self.send_initial_email and self.email_template_id and created_leads:
            for lead in created_leads:
                try:
                    self.email_template_id.send_mail(
                        lead.id,
                        force_send=True,
                        raise_exception=False,
                    )
                except Exception:
                    # Keep launch resilient: one bad recipient/template render
                    # should not block campaign creation.
                    continue

        # 8 — Open results: lead list if contacts used, otherwise the source form
        if created_leads:
            return {
                "type": "ir.actions.act_window",
                "name": "Leads created — %s" % self.campaign_name,
                "res_model": "crm.lead",
                "view_mode": "list,form",
                "domain": [("id", "in", created_leads.ids)],
                "target": "current",
            }
        return {
            "type": "ir.actions.act_window",
            "res_model": "lead.engine.source",
            "res_id": source.id,
            "view_mode": "form",
            "target": "current",
        }


# ── Wizard line: score rule ────────────────────────────────────────────────────
class LeadEngineCampaignWizardScoreLine(models.TransientModel):
    _name = "lead.engine.campaign.wizard.score.line"
    _description = "Campaign Wizard Score Rule Line"
    _order = "wizard_id, id"

    wizard_id = fields.Many2one(
        comodel_name="lead.engine.campaign.wizard",
        required=True,
        ondelete="cascade",
    )
    name = fields.Char(
        required=True,
        help="Short label shown in the score rule list (e.g. 'Email provided').",
    )
    lead_field = fields.Selection(
        selection=LEAD_FIELD_SELECTION,
        string="Lead field",
        help="Leave empty to apply this score to every lead from the source (base score).",
    )
    score_delta = fields.Integer(string="Points", default=10, required=True)

    @api.onchange("lead_field")
    def _onchange_lead_field(self):
        if self.lead_field and not self.name:
            label = dict(LEAD_FIELD_SELECTION).get(self.lead_field, "")
            self.name = label


# ── Wizard line: playbook step ────────────────────────────────────────────────
class LeadEngineCampaignWizardStepLine(models.TransientModel):
    _name = "lead.engine.campaign.wizard.step.line"
    _description = "Campaign Wizard Playbook Step Line"
    _order = "wizard_id, sequence"

    wizard_id = fields.Many2one(
        comodel_name="lead.engine.campaign.wizard",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(default=10, required=True)
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
    activity_summary = fields.Char(string="Summary")
    activity_note = fields.Html(string="Instructions")
    mail_template_id = fields.Many2one(
        comodel_name="mail.template",
        string="Email template",
        domain=[("model", "=", "crm.lead")],
    )
