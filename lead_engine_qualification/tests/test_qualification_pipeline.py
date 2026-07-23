# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLeadEngineQualificationPipeline(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Source = cls.env["lead.engine.source"]
        cls.Lead = cls.env["crm.lead"]
        cls.ScoreRule = cls.env["lead.engine.score.rule"]
        cls.AssignRule = cls.env["lead.engine.assignment.rule"]
        cls.Pipeline = cls.env["lead.engine.qualification.pipeline"]
        cls.Map = cls.env["lead.engine.identity.map"]
        cls.company = cls.env.company
        cls.team = cls.env["crm.team"].create({"name": "LE Test Team"})
        cls.user = cls.env.ref("base.user_admin")
        cls.source = cls.Source.create(
            {
                "name": "Test Source",
                "code": "TEST_SRC",
                "channel": "api",
                "company_id": cls.company.id,
                "default_team_id": cls.team.id,
                "default_user_id": cls.user.id,
            }
        )

    def test_pipeline_score_assign_identity(self):
        self.ScoreRule.create(
            {
                "name": "Always +10",
                "sequence": 1,
                "company_id": self.company.id,
                "rule_type": "always",
                "score_delta": 10,
            }
        )
        self.ScoreRule.create(
            {
                "name": "Name bonus",
                "sequence": 2,
                "company_id": self.company.id,
                "rule_type": "field",
                "field_name": "name",
                "operator": "contains",
                "value": "Acme",
                "score_delta": 5,
            }
        )
        self.AssignRule.create(
            {
                "name": "Assign to admin",
                "sequence": 1,
                "company_id": self.company.id,
                "user_id": self.user.id,
                "team_id": self.team.id,
                "domain_expression": "[]",
                "stop_processing": True,
            }
        )
        lead = self.Lead.create(
            {
                "name": "Acme Corp inquiry",
                "lead_engine_source_id": self.source.id,
                "le_channel": "api",
                "external_ref": "ext-001",
            }
        )
        self.Pipeline.apply(lead)
        self.assertEqual(lead.lead_score, 15)
        self.assertEqual(lead.assignment_status, "rule_applied")
        self.assertEqual(lead.qualification_state, "working")
        self.assertEqual(lead.duplicate_status, "unique")
        maps = self.Map.search([("external_ref", "=", "ext-001")])
        self.assertEqual(len(maps), 1)
        self.assertEqual(maps.lead_id, lead)

    def test_pipeline_duplicate_skips_assignment(self):
        first = self.Lead.create(
            {
                "name": "First",
                "lead_engine_source_id": self.source.id,
                "le_channel": "api",
                "external_ref": "dup-1",
            }
        )
        self.Pipeline.apply(first)
        second = self.Lead.create(
            {
                "name": "Second",
                "lead_engine_source_id": self.source.id,
                "le_channel": "api",
                "external_ref": "dup-1",
            }
        )
        self.Pipeline.apply(second)
        self.assertEqual(second.duplicate_status, "duplicate")
        self.assertEqual(second.duplicate_master_id, first)
        self.assertEqual(second.assignment_status, "unassigned")
