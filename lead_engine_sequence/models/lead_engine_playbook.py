# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class LeadEnginePlaybook(models.Model):
    _name = "lead.engine.playbook"
    _description = "Lead Engine Playbook"
    _order = "sequence, name, id"

    name = fields.Char(required=True)
    code = fields.Char(
        required=True,
        help="Stable key for imports and automation.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        comodel_name="res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    description = fields.Text()
    step_ids = fields.One2many(
        comodel_name="lead.engine.playbook.step",
        inverse_name="playbook_id",
        string="Steps",
    )
    run_ids = fields.One2many(
        comodel_name="lead.engine.playbook.run",
        inverse_name="playbook_id",
        string="Runs",
    )
    run_count_total = fields.Integer(
        string="Runs (total)",
        compute="_compute_run_stats",
    )
    run_count_running = fields.Integer(
        string="Active runs",
        compute="_compute_run_stats",
    )
    run_count_error = fields.Integer(
        string="Runs in error",
        compute="_compute_run_stats",
    )
    run_count_done = fields.Integer(
        string="Runs done",
        compute="_compute_run_stats",
    )

    @api.depends("run_ids.state")
    def _compute_run_stats(self):
        Run = self.env["lead.engine.playbook.run"]
        for pb in self:
            pb_id = pb._origin.id
            if not pb_id:
                pb.run_count_total = 0
                pb.run_count_running = 0
                pb.run_count_error = 0
                pb.run_count_done = 0
                continue
            groups = Run.read_group(
                [("playbook_id", "=", pb_id)],
                ["__count"],
                ["state"],
                lazy=False,
            )
            by_state = {g["state"]: g["__count"] for g in groups}
            pb.run_count_total = sum(by_state.values())
            pb.run_count_running = by_state.get("running", 0)
            pb.run_count_error = by_state.get("error", 0)
            pb.run_count_done = by_state.get("done", 0)

    _lead_engine_playbook_code_company_uniq = models.Constraint(
        "UNIQUE(code, company_id)",
        "Playbook code must be unique per company.",
    )


class LeadEnginePlaybookStep(models.Model):
    _name = "lead.engine.playbook.step"
    _description = "Lead Engine Playbook Step"
    _order = "playbook_id, sequence, id"

    playbook_id = fields.Many2one(
        comodel_name="lead.engine.playbook",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(default=10, required=True)
    name = fields.Char(required=True)
    step_type = fields.Selection(
        selection=[
            ("create_activity", "Create activity"),
            ("send_email_template", "Send email template"),
            ("assign_owner", "Assign owner / team"),
            ("server_action", "Execute server action"),
        ],
        required=True,
    )
    delay_unit = fields.Selection(
        selection=[
            ("immediate", "Immediate"),
            ("hours", "Hours after previous offset"),
            ("days", "Days after previous offset"),
        ],
        required=True,
        default="immediate",
        help="Delays are cumulative from the playbook run start time: each step adds to "
        "the offset used for scheduling (MVP).",
    )
    delay_amount = fields.Integer(
        default=0,
        help="Number of hours or days to add before this step runs (ignored when delay is immediate).",
    )
    # create_activity
    activity_type_id = fields.Many2one(comodel_name="mail.activity.type", string="Activity type")
    activity_summary = fields.Char(string="Activity summary")
    activity_note = fields.Html(string="Activity note")
    activity_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Assign activity to",
        domain="[('share', '=', False)]",
    )
    # send_email_template
    mail_template_id = fields.Many2one(comodel_name="mail.template", string="Email template")
    # assign_owner
    assign_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Salesperson",
        domain="[('share', '=', False)]",
    )
    assign_team_id = fields.Many2one(comodel_name="crm.team", string="Sales team")
    # server_action
    server_action_id = fields.Many2one(
        comodel_name="ir.actions.server",
        string="Server action",
        help="Must be applicable to crm.lead (binding or code).",
    )

    @api.constrains("delay_unit", "delay_amount")
    def _check_delay(self):
        for rec in self:
            if rec.delay_unit == "immediate" and rec.delay_amount:
                raise ValidationError(
                    self.env._("Immediate steps must use delay amount 0.")
                )
            if rec.delay_unit != "immediate" and rec.delay_amount < 0:
                raise ValidationError(self.env._("Delay amount cannot be negative."))

    @api.constrains(
        "step_type",
        "activity_type_id",
        "mail_template_id",
        "assign_user_id",
        "assign_team_id",
        "server_action_id",
    )
    def _check_step_payload(self):
        for rec in self:
            if rec.step_type == "create_activity" and not rec.activity_type_id:
                raise ValidationError(
                    self.env._("Activity steps require an activity type.")
                )
            if rec.step_type == "send_email_template":
                if not rec.mail_template_id:
                    raise ValidationError(
                        self.env._("Email steps require a mail template.")
                    )
                if rec.mail_template_id.model != "crm.lead":
                    raise ValidationError(
                        self.env._("Email template must target model crm.lead.")
                    )
            if rec.step_type == "assign_owner":
                if not rec.assign_user_id and not rec.assign_team_id:
                    raise ValidationError(
                        self.env._("Assign steps require a user and/or a sales team.")
                    )
            if rec.step_type == "server_action" and not rec.server_action_id:
                raise ValidationError(
                    self.env._("Server action steps require a server action.")
                )
