# -*- coding: utf-8 -*-

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLeadEngineScoring(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Source = cls.env["lead.engine.source"]
        cls.Lead = cls.env["crm.lead"]
        cls.ScoreRule = cls.env["lead.engine.score.rule"]
        cls.Pipeline = cls.env["lead.engine.qualification.pipeline"]
        cls.company = cls.env.company
        cls.source = cls.Source.create(
            {
                "name": "S3 Score Source",
                "code": "S3_SCORE",
                "channel": "api",
                "company_id": cls.company.id,
                "auto_score": True,
                "auto_assign": False,
            }
        )

    def setUp(self):
        super().setUp()
        self.ScoreRule.search([("company_id", "=", self.company.id)]).unlink()

    def _lead(self, **kwargs):
        base = {
            "name": "Lead",
            "lead_engine_source_id": self.source.id,
            "le_channel": "api",
        }
        base.update(kwargs)
        return self.Lead.create(base)

    def test_negative_score_delta_rejected(self):
        with self.assertRaises(ValidationError):
            self.ScoreRule.create(
                {
                    "name": "Bad",
                    "sequence": 1,
                    "company_id": self.company.id,
                    "rule_type": "always",
                    "score_delta": -1,
                }
            )

    def test_multiple_matching_rules_additive_sequence(self):
        self.ScoreRule.create(
            {
                "name": "R1",
                "sequence": 10,
                "company_id": self.company.id,
                "rule_type": "always",
                "score_delta": 3,
            }
        )
        self.ScoreRule.create(
            {
                "name": "R2",
                "sequence": 20,
                "company_id": self.company.id,
                "rule_type": "always",
                "score_delta": 7,
            }
        )
        lead = self._lead()
        self.Pipeline.recompute_score(lead)
        self.assertEqual(lead.lead_score, 10)

    def test_no_matching_rules_zero_score(self):
        self.ScoreRule.create(
            {
                "name": "Wrong source",
                "sequence": 1,
                "company_id": self.company.id,
                "rule_type": "always",
                "score_delta": 99,
                "source_id": self.Source.create(
                    {
                        "name": "Other",
                        "code": "OTHER",
                        "channel": "api",
                        "company_id": self.company.id,
                    }
                ).id,
            }
        )
        lead = self._lead()
        self.Pipeline.recompute_score(lead)
        self.assertEqual(lead.lead_score, 0)

    def test_source_specific_rule(self):
        self.ScoreRule.create(
            {
                "name": "For our source",
                "sequence": 1,
                "company_id": self.company.id,
                "rule_type": "always",
                "score_delta": 42,
                "source_id": self.source.id,
            }
        )
        lead = self._lead()
        self.Pipeline.recompute_score(lead)
        self.assertEqual(lead.lead_score, 42)

    def test_channel_specific_rule(self):
        self.ScoreRule.create(
            {
                "name": "API only",
                "sequence": 1,
                "company_id": self.company.id,
                "rule_type": "always",
                "score_delta": 5,
                "le_channel": "api",
            }
        )
        lead = self._lead(le_channel="form")
        self.Pipeline.recompute_score(lead)
        self.assertEqual(lead.lead_score, 0)
        lead.le_channel = "api"
        self.Pipeline.recompute_score(lead)
        self.assertEqual(lead.lead_score, 5)

    def test_inactive_score_rule_ignored(self):
        self.ScoreRule.create(
            {
                "name": "Off",
                "sequence": 1,
                "company_id": self.company.id,
                "rule_type": "always",
                "score_delta": 100,
                "active": False,
            }
        )
        self.ScoreRule.create(
            {
                "name": "On",
                "sequence": 2,
                "company_id": self.company.id,
                "rule_type": "always",
                "score_delta": 11,
            }
        )
        lead = self._lead()
        self.Pipeline.recompute_score(lead)
        self.assertEqual(lead.lead_score, 11)

    def test_recompute_after_lead_update(self):
        self.ScoreRule.create(
            {
                "name": "Bonus Acme",
                "sequence": 1,
                "company_id": self.company.id,
                "rule_type": "field",
                "field_name": "name",
                "operator": "contains",
                "value": "Acme",
                "score_delta": 50,
            }
        )
        self.ScoreRule.create(
            {
                "name": "Base",
                "sequence": 2,
                "company_id": self.company.id,
                "rule_type": "always",
                "score_delta": 1,
            }
        )
        lead = self._lead(name="Other")
        self.Pipeline.recompute_score(lead)
        self.assertEqual(lead.lead_score, 1)
        lead.write({"name": "Acme Corp"})
        self.Pipeline.recompute_score(lead)
        self.assertEqual(lead.lead_score, 51)

    def test_auto_score_off_skips_write(self):
        self.source.auto_score = False
        self.ScoreRule.create(
            {
                "name": "Would apply",
                "sequence": 1,
                "company_id": self.company.id,
                "rule_type": "always",
                "score_delta": 77,
            }
        )
        lead = self._lead(lead_score=33)
        self.Pipeline.recompute_score(lead)
        self.assertEqual(lead.lead_score, 33)


@tagged("post_install", "-at_install")
class TestLeadEngineAssignment(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Source = cls.env["lead.engine.source"]
        cls.Lead = cls.env["crm.lead"]
        cls.AssignRule = cls.env["lead.engine.assignment.rule"]
        cls.Pipeline = cls.env["lead.engine.qualification.pipeline"]
        cls.company = cls.env.company
        cls.team_a = cls.env["crm.team"].create({"name": "S3 Team A"})
        cls.team_b = cls.env["crm.team"].create({"name": "S3 Team B"})
        cls.user = cls.env.ref("base.user_admin")
        cls.source = cls.Source.create(
            {
                "name": "S3 Assign Source",
                "code": "S3_ASSIGN",
                "channel": "api",
                "company_id": cls.company.id,
                "auto_score": False,
                "auto_assign": True,
            }
        )

    def setUp(self):
        super().setUp()
        self.AssignRule.search([("company_id", "=", self.company.id)]).unlink()

    def _lead(self, **kwargs):
        base = {
            "name": "Assign Lead",
            "lead_engine_source_id": self.source.id,
            "le_channel": "api",
            "lead_score": 0,
            "team_id": False,
            "user_id": False,
        }
        base.update(kwargs)
        return self.Lead.create(base)

    def test_source_based_assignment(self):
        other = self.Source.create(
            {
                "name": "Other src",
                "code": "OTHER_S3",
                "channel": "api",
                "company_id": self.company.id,
            }
        )
        self.AssignRule.create(
            {
                "name": "Our source only",
                "sequence": 1,
                "company_id": self.company.id,
                "source_id": self.source.id,
                "team_id": self.team_a.id,
                "domain_expression": "[]",
            }
        )
        lead_ok = self._lead()
        self.Pipeline.apply_assignment(lead_ok)
        self.assertEqual(lead_ok.team_id, self.team_a)
        lead_no = self._lead(lead_engine_source_id=other.id)
        self.Pipeline.apply_assignment(lead_no)
        self.assertFalse(lead_no.team_id)

    def test_channel_based_assignment(self):
        self.AssignRule.create(
            {
                "name": "Form channel",
                "sequence": 1,
                "company_id": self.company.id,
                "le_channel": "form",
                "team_id": self.team_b.id,
                "domain_expression": "[]",
            }
        )
        lead = self._lead(le_channel="api")
        self.Pipeline.apply_assignment(lead)
        self.assertFalse(lead.team_id)

    def test_min_score_filter(self):
        self.AssignRule.create(
            {
                "name": "High score only",
                "sequence": 1,
                "company_id": self.company.id,
                "min_score": 100,
                "team_id": self.team_a.id,
                "domain_expression": "[]",
            }
        )
        self.AssignRule.create(
            {
                "name": "Fallback low",
                "sequence": 2,
                "company_id": self.company.id,
                "team_id": self.team_b.id,
                "domain_expression": "[]",
            }
        )
        low = self._lead(lead_score=50)
        self.Pipeline.apply_assignment(low)
        self.assertEqual(low.team_id, self.team_b)
        high = self._lead(lead_score=120, name="High lead")
        self.Pipeline.apply_assignment(high)
        self.assertEqual(high.team_id, self.team_a)

    def test_max_score_filter(self):
        self.AssignRule.create(
            {
                "name": "Score at most 50",
                "sequence": 1,
                "company_id": self.company.id,
                "max_score": 50,
                "team_id": self.team_a.id,
                "domain_expression": "[]",
            }
        )
        self.AssignRule.create(
            {
                "name": "Fallback higher scores",
                "sequence": 2,
                "company_id": self.company.id,
                "team_id": self.team_b.id,
                "domain_expression": "[]",
            }
        )
        low = self._lead(lead_score=40, name="lowmax")
        self.Pipeline.apply_assignment(low)
        self.assertEqual(low.team_id, self.team_a)
        high = self._lead(lead_score=90, name="himax")
        self.Pipeline.apply_assignment(high)
        self.assertEqual(high.team_id, self.team_b)

    def test_no_rule_matched_unassigned(self):
        self.AssignRule.create(
            {
                "name": "Never",
                "sequence": 1,
                "company_id": self.company.id,
                "source_id": self.Source.create(
                    {
                        "name": "X",
                        "code": "X",
                        "channel": "api",
                        "company_id": self.company.id,
                    }
                ).id,
                "team_id": self.team_a.id,
                "domain_expression": "[]",
            }
        )
        lead = self._lead()
        self.Pipeline.apply_assignment(lead)
        self.assertFalse(lead.team_id)
        self.assertFalse(lead.user_id)
        self.assertEqual(lead.assignment_status, "unassigned")

    def test_inactive_assignment_rule_ignored(self):
        self.AssignRule.create(
            {
                "name": "Off",
                "sequence": 1,
                "company_id": self.company.id,
                "active": False,
                "team_id": self.team_a.id,
                "domain_expression": "[]",
            }
        )
        self.AssignRule.create(
            {
                "name": "On",
                "sequence": 2,
                "company_id": self.company.id,
                "team_id": self.team_b.id,
                "domain_expression": "[]",
            }
        )
        lead = self._lead()
        self.Pipeline.apply_assignment(lead)
        self.assertEqual(lead.team_id, self.team_b)

    def test_precedence_first_matching_rule_wins(self):
        self.AssignRule.create(
            {
                "name": "First team",
                "sequence": 1,
                "company_id": self.company.id,
                "team_id": self.team_a.id,
                "domain_expression": "[]",
            }
        )
        self.AssignRule.create(
            {
                "name": "Second user",
                "sequence": 2,
                "company_id": self.company.id,
                "user_id": self.user.id,
                "domain_expression": "[]",
            }
        )
        lead = self._lead()
        self.Pipeline.apply_assignment(lead)
        self.assertEqual(lead.team_id, self.team_a)
        self.assertFalse(lead.user_id)

    def test_domain_match_required(self):
        self.AssignRule.create(
            {
                "name": "Name VIP",
                "sequence": 1,
                "company_id": self.company.id,
                "team_id": self.team_a.id,
                "domain_expression": "[('name', 'ilike', 'VIP')]",
            }
        )
        self.AssignRule.create(
            {
                "name": "Catch all",
                "sequence": 2,
                "company_id": self.company.id,
                "team_id": self.team_b.id,
                "domain_expression": "[]",
            }
        )
        plain = self._lead(name="Plain")
        self.Pipeline.apply_assignment(plain)
        self.assertEqual(plain.team_id, self.team_b)
        vip = self._lead(name="VIP Client")
        self.Pipeline.apply_assignment(vip)
        self.assertEqual(vip.team_id, self.team_a)


@tagged("post_install", "-at_install")
class TestLeadEngineStateMachine(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Source = cls.env["lead.engine.source"]
        cls.Lead = cls.env["crm.lead"]
        cls.Pipeline = cls.env["lead.engine.qualification.pipeline"]
        cls.company = cls.env.company
        cls.team = cls.env["crm.team"].create({"name": "SM Team"})
        cls.user = cls.env.ref("base.user_admin")
        cls.source = cls.Source.create(
            {
                "name": "SM Source",
                "code": "SM_SRC",
                "channel": "api",
                "company_id": cls.company.id,
                "default_team_id": cls.team.id,
                "default_user_id": cls.user.id,
                "auto_score": False,
                "auto_assign": True,
            }
        )

    def test_idempotent_pipeline_same_lead_stays_unique(self):
        lead = self.Lead.create(
            {
                "name": "Solo",
                "lead_engine_source_id": self.source.id,
                "le_channel": "api",
                "external_ref": "idem-sm",
            }
        )
        self.Pipeline.run_qualification_pipeline(lead)
        self.assertEqual(lead.duplicate_status, "unique")
        self.Pipeline.run_qualification_pipeline(lead)
        self.assertEqual(lead.duplicate_status, "unique")

    def test_second_row_duplicate_oldest_master(self):
        first = self.Lead.create(
            {
                "name": "First",
                "lead_engine_source_id": self.source.id,
                "le_channel": "api",
                "external_ref": "dup-sm",
            }
        )
        second = self.Lead.create(
            {
                "name": "Second",
                "lead_engine_source_id": self.source.id,
                "le_channel": "api",
                "external_ref": "dup-sm",
            }
        )
        self.Pipeline.evaluate_duplicate_state(first)
        self.Pipeline.evaluate_duplicate_state(second)
        self.assertEqual(first.duplicate_status, "unique")
        self.assertEqual(second.duplicate_status, "duplicate")
        self.assertEqual(second.duplicate_master_id, first)

    def test_finalize_respects_duplicate_vs_qualification(self):
        lead = self.Lead.create(
            {
                "name": "Dup",
                "lead_engine_source_id": self.source.id,
                "le_channel": "api",
                "external_ref": "x1",
            }
        )
        self.Pipeline.evaluate_duplicate_state(lead)
        self.assertEqual(lead.duplicate_status, "unique")
        self.Pipeline.finalize_qualification_state(lead)
        self.assertEqual(lead.qualification_state, "new")
        other = self.Lead.create(
            {
                "name": "Dup2",
                "lead_engine_source_id": self.source.id,
                "le_channel": "api",
                "external_ref": "x1",
            }
        )
        self.Pipeline.evaluate_duplicate_state(lead)
        self.Pipeline.evaluate_duplicate_state(other)
        self.assertEqual(other.duplicate_status, "duplicate")
        self.Pipeline.apply_assignment(other)
        self.assertEqual(other.assignment_status, "unassigned")
        self.Pipeline.finalize_qualification_state(other)
        self.assertEqual(other.qualification_state, "new")

    def test_assignment_step_does_not_write_qualification_state(self):
        lead = self.Lead.create(
            {
                "name": "Q",
                "lead_engine_source_id": self.source.id,
                "le_channel": "api",
                "qualification_state": "qualified",
            }
        )
        before = lead.qualification_state
        self.Pipeline.apply_assignment(lead)
        self.assertEqual(lead.qualification_state, before)

    def test_recompute_score_does_not_touch_assignment(self):
        lead = self.Lead.create(
            {
                "name": "Mix",
                "lead_engine_source_id": self.source.id,
                "le_channel": "api",
                "user_id": self.user.id,
                "team_id": self.team.id,
                "assignment_status": "manual",
                "lead_score": 0,
            }
        )
        self.env["lead.engine.score.rule"].create(
            {
                "name": "+5",
                "sequence": 1,
                "company_id": self.company.id,
                "rule_type": "always",
                "score_delta": 5,
            }
        )
        self.source.auto_score = True
        st = lead.assignment_status
        uid = lead.user_id
        self.Pipeline.recompute_score(lead)
        self.assertEqual(lead.assignment_status, st)
        self.assertEqual(lead.user_id, uid)
        self.assertEqual(lead.lead_score, 5)

    def test_evaluate_duplicate_does_not_overwrite_qualification(self):
        lead = self.Lead.create(
            {
                "name": "Q2",
                "lead_engine_source_id": self.source.id,
                "le_channel": "api",
                "external_ref": "q2",
                "qualification_state": "working",
            }
        )
        self.Pipeline.evaluate_duplicate_state(lead)
        self.assertEqual(lead.qualification_state, "working")
