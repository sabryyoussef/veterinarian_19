# -*- coding: utf-8 -*-
"""
Tests for lead_engine_campaign.

Workflow covered (no browser):
  - LeadEngineCampaignTemplate: create with score lines and step lines
  - LeadEngineCampaignTemplate: active flag and sequence ordering
  - LeadEngineCampaignWizard.action_launch():
      * Creates a new lead.engine.source with correct code and channel
      * Creates lead.engine.score.rule rows from score_line_ids
      * Creates lead.engine.assignment.rule when assign_team/user provided
      * Creates a new playbook with steps when playbook_choice='new'
      * Returns source form action when no contacts selected
  - LeadEngineCampaignWizard.action_launch() with contacts:
      * Creates crm.lead records for each partner
      * Returns lead list action
"""

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLeadEngineCampaignTemplate(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Template = cls.env["lead.engine.campaign.template"]

    # ── basic creation ─────────────────────────────────────────────────────────

    def test_template_create_minimal(self):
        tpl = self.Template.create({"name": "Minimal Template"})
        self.assertTrue(tpl.id)
        self.assertTrue(tpl.active)

    def test_template_channel_default(self):
        tpl = self.Template.create({"name": "Default Channel Template"})
        self.assertIn(tpl.channel, ("form", "api", "email", "ads", "other"))

    def test_template_score_lines(self):
        tpl = self.Template.create(
            {
                "name": "Scored Template",
                "score_line_ids": [
                    (0, 0, {"name": "Base", "score_delta": 10}),
                    (0, 0, {"name": "Email bonus", "lead_field": "email_from", "score_delta": 20}),
                ],
            }
        )
        self.assertEqual(len(tpl.score_line_ids), 2)

    def test_template_step_lines(self):
        tpl = self.Template.create(
            {
                "name": "Stepped Template",
                "step_line_ids": [
                    (
                        0, 0,
                        {
                            "name": "First call",
                            "step_type": "create_activity",
                            "delay_unit": "immediate",
                            "delay_amount": 0,
                        },
                    ),
                ],
            }
        )
        self.assertEqual(len(tpl.step_line_ids), 1)

    def test_template_ordering_by_sequence(self):
        t1 = self.Template.create({"name": "Z Template", "sequence": 20})
        t2 = self.Template.create({"name": "A Template", "sequence": 5})
        templates = self.Template.search(
            [("id", "in", [t1.id, t2.id])], order="sequence asc"
        )
        self.assertEqual(templates[0].id, t2.id)

    def test_template_inactive_excluded_from_active_search(self):
        tpl = self.Template.create({"name": "Inactive Tpl", "active": False})
        result = self.Template.search([("id", "=", tpl.id)])
        self.assertFalse(result)


@tagged("post_install", "-at_install")
class TestLeadEngineCampaignWizard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Wizard = cls.env["lead.engine.campaign.wizard"]
        cls.Source = cls.env["lead.engine.source"]
        cls.ScoreRule = cls.env["lead.engine.score.rule"]
        cls.AssignRule = cls.env["lead.engine.assignment.rule"]
        cls.Playbook = cls.env["lead.engine.playbook"]
        cls.Lead = cls.env["crm.lead"]
        cls.company = cls.env.company
        cls.user = cls.env.ref("base.user_admin")
        cls.team = cls.env["crm.team"].create({"name": "Wizard Test Team"})

    def _wizard(self, campaign_name="Test Campaign", **kwargs):
        vals = {
            "campaign_name": campaign_name,
            "channel": "form",
            "source_code": "TEST_WIZ_" + campaign_name[:5].upper().replace(" ", "_"),
            "playbook_choice": "none",
        }
        vals.update(kwargs)
        return self.Wizard.create(vals)

    # ── action_launch creates source ──────────────────────────────────────────

    def test_action_launch_creates_source(self):
        wiz = self._wizard(campaign_name="Launch Source Test", source_code="LST_SRC1")
        result = wiz.action_launch()
        src = self.Source.search([("code", "=", "LST_SRC1")], limit=1)
        self.assertTrue(src)
        self.assertEqual(src.channel, "form")

    def test_action_launch_source_code_slugified_when_empty(self):
        wiz = self._wizard(campaign_name="Auto Slug Code", source_code=False)
        wiz.action_launch()
        src = self.Source.search([("name", "=", "Auto Slug Code")], limit=1)
        self.assertTrue(src)
        self.assertTrue(src.code)

    def test_action_launch_returns_source_form_action(self):
        wiz = self._wizard(source_code="ACT_FORM_SRC")
        result = wiz.action_launch()
        self.assertEqual(result.get("type"), "ir.actions.act_window")
        self.assertEqual(result.get("res_model"), "lead.engine.source")

    # ── score rules ───────────────────────────────────────────────────────────

    def test_action_launch_creates_score_rules(self):
        wiz = self._wizard(
            source_code="SCORE_WIZ1",
            score_line_ids=[
                (0, 0, {"name": "Base score", "score_delta": 10}),
                (
                    0, 0,
                    {
                        "name": "Email provided",
                        "lead_field": "email_from",
                        "score_delta": 20,
                    },
                ),
            ],
        )
        wiz.action_launch()
        src = self.Source.search([("code", "=", "SCORE_WIZ1")], limit=1)
        rules = self.ScoreRule.search([("source_id", "=", src.id)])
        self.assertEqual(len(rules), 2)

    # ── assignment rule ───────────────────────────────────────────────────────

    def test_action_launch_creates_assignment_rule_when_team_set(self):
        wiz = self._wizard(
            source_code="ASSIGN_WIZ1",
            assign_team_id=self.team.id,
            assign_user_id=self.user.id,
            assign_min_score=30,
        )
        wiz.action_launch()
        src = self.Source.search([("code", "=", "ASSIGN_WIZ1")], limit=1)
        rules = self.AssignRule.search([("source_id", "=", src.id)])
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules.team_id.id, self.team.id)
        self.assertEqual(rules.min_score, 30)

    def test_action_launch_no_assignment_rule_when_no_team(self):
        wiz = self._wizard(source_code="NO_ASSIGN_WIZ")
        wiz.action_launch()
        src = self.Source.search([("code", "=", "NO_ASSIGN_WIZ")], limit=1)
        rules = self.AssignRule.search([("source_id", "=", src.id)])
        self.assertFalse(rules)

    # ── playbook creation ─────────────────────────────────────────────────────

    def test_action_launch_creates_playbook_when_choice_new(self):
        wiz = self._wizard(
            source_code="PB_WIZ1",
            playbook_choice="new",
            playbook_name="My Campaign Playbook",
        )
        wiz.action_launch()
        pb = self.Playbook.search(
            [("name", "=", "My Campaign Playbook")], limit=1
        )
        self.assertTrue(pb)

    def test_action_launch_no_playbook_when_choice_none(self):
        wiz = self._wizard(source_code="NO_PB_WIZ", playbook_choice="none")
        wiz.action_launch()
        src = self.Source.search([("code", "=", "NO_PB_WIZ")], limit=1)
        self.assertFalse(getattr(src, "playbook_id", False))

    # ── lead creation from contacts ───────────────────────────────────────────

    def test_action_launch_creates_leads_from_contacts(self):
        partner = self.env["res.partner"].create(
            {"name": "Campaign Contact", "email": "cc@example.com"}
        )
        wiz = self._wizard(
            source_code="LEAD_CREATE_WIZ",
            create_leads_from_contacts=True,
            target_partner_ids=[(4, partner.id)],
        )
        before = self.Lead.search_count([])
        result = wiz.action_launch()
        after = self.Lead.search_count([])
        self.assertGreater(after, before)
        self.assertEqual(result.get("res_model"), "crm.lead")
