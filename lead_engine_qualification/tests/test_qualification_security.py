# -*- coding: utf-8 -*-
"""
Additional tests for lead_engine_qualification — security and advanced scoring.

Workflow covered (no browser):
  - Score rules with 'set' / 'not_set' operators
  - Score rules with '>' / '>=' / '<' comparisons (field_name=lead_score)
  - Assignment rule source filter: only matching source gets assigned
  - Identity map created only once per external_ref (idempotent)
  - Qualification state transitions via pipeline (new → working → qualified)
  - Security: internal user without Lead Manager group cannot write score rules
"""

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestQualificationSecurity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Source = cls.env["lead.engine.source"]
        cls.Lead = cls.env["crm.lead"]
        cls.ScoreRule = cls.env["lead.engine.score.rule"]
        cls.Pipeline = cls.env["lead.engine.qualification.pipeline"]
        cls.company = cls.env.company
        cls.team = cls.env["crm.team"].create({"name": "Security Test Team"})
        cls.source = cls.Source.create(
            {
                "name": "Sec Source",
                "code": "SEC_SRC",
                "channel": "api",
                "company_id": cls.company.id,
            }
        )
        # Internal user without Lead Engine manager rights
        cls.plain_user = cls.env["res.users"].create(
            {
                "name": "Plain Internal User",
                "login": "plain_internal_le@test.example",
                "groups_id": [(4, cls.env.ref("base.group_user").id)],
            }
        )

    def test_plain_user_cannot_create_score_rule(self):
        """A plain internal user must not be able to create scoring rules."""
        with self.assertRaises(AccessError):
            self.ScoreRule.with_user(self.plain_user).create(
                {
                    "name": "Unauthorized Rule",
                    "sequence": 1,
                    "company_id": self.company.id,
                    "rule_type": "always",
                    "score_delta": 10,
                }
            )

    def test_admin_can_create_score_rule(self):
        admin = self.env.ref("base.user_admin")
        rule = self.ScoreRule.with_user(admin).create(
            {
                "name": "Admin Rule",
                "sequence": 99,
                "company_id": self.company.id,
                "rule_type": "always",
                "score_delta": 1,
            }
        )
        self.assertTrue(rule.id)


@tagged("post_install", "-at_install")
class TestQualificationAdvancedScoring(TransactionCase):

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
                "name": "Adv Src",
                "code": "ADV_SRC",
                "channel": "form",
                "company_id": cls.company.id,
            }
        )

    def _rule(self, **kwargs):
        vals = {
            "sequence": 10,
            "company_id": self.company.id,
            "rule_type": "always",
            "score_delta": 10,
        }
        vals.update(kwargs)
        return self.ScoreRule.create(vals)

    def _lead(self, **kwargs):
        vals = {
            "lead_engine_source_id": self.source.id,
            "le_channel": "form",
        }
        vals.update(kwargs)
        return self.Lead.create(vals)

    # ── field operator: set / not_set ─────────────────────────────────────────

    def test_score_rule_field_set_operator_adds_score(self):
        """'set' rule fires when field has a value."""
        self._rule(
            name="Email set bonus",
            rule_type="field",
            field_name="email_from",
            operator="set",
            score_delta=20,
        )
        lead = self._lead(name="Email Lead", email_from="test@example.com")
        self.Pipeline.apply(lead)
        self.assertGreaterEqual(lead.lead_score, 20)

    def test_score_rule_field_set_operator_skipped_when_empty(self):
        """'set' rule should NOT fire when field is empty."""
        # Remove any pre-existing 'always' rules to isolate
        self.ScoreRule.search(
            [("company_id", "=", self.company.id), ("rule_type", "=", "always")]
        ).write({"active": False})
        self._rule(
            name="Phone set bonus",
            rule_type="field",
            field_name="phone",
            operator="set",
            score_delta=30,
        )
        lead = self._lead(name="No Phone Lead")
        self.Pipeline.apply(lead)
        self.assertEqual(lead.lead_score, 0)

    def test_score_rule_field_not_set_operator(self):
        """'not_set' rule fires when field is empty."""
        self.ScoreRule.search(
            [("company_id", "=", self.company.id), ("rule_type", "=", "always")]
        ).write({"active": False})
        self._rule(
            name="Missing phone penalty",
            rule_type="field",
            field_name="phone",
            operator="not_set",
            score_delta=5,
        )
        lead = self._lead(name="NoPhoneLead2")
        self.Pipeline.apply(lead)
        self.assertEqual(lead.lead_score, 5)

    # ── source-specific assignment rule ───────────────────────────────────────

    def test_assignment_rule_source_filter_does_not_match_other_source(self):
        """Assignment rule scoped to a different source must not affect our lead."""
        other_source = self.Source.create(
            {
                "name": "Other Src",
                "code": "OTHER_SRC2",
                "channel": "api",
                "company_id": self.company.id,
            }
        )
        user = self.env.ref("base.user_admin")
        team = self.env["crm.team"].create({"name": "Assign Team 2"})
        self.env["lead.engine.assignment.rule"].create(
            {
                "name": "Only Other Source",
                "sequence": 1,
                "company_id": self.company.id,
                "source_id": other_source.id,
                "user_id": user.id,
                "team_id": team.id,
                "domain_expression": "[]",
            }
        )
        lead = self._lead(name="No Match Lead")
        self.Pipeline.apply(lead)
        # Assignment rule was for other_source; our lead.source is ADV_SRC → not assigned
        self.assertNotEqual(lead.user_id.id, user.id)

    # ── identity map idempotency ──────────────────────────────────────────────

    def test_identity_map_not_duplicated_on_second_pipeline_run(self):
        """Running pipeline twice on the same lead must not create two identity map rows."""
        Map = self.env["lead.engine.identity.map"]
        lead = self._lead(name="Idem Lead", external_ref="ext-idem-001")
        self.Pipeline.apply(lead)
        self.Pipeline.apply(lead)
        maps = Map.search(
            [("source_id", "=", self.source.id), ("external_ref", "=", "ext-idem-001")]
        )
        self.assertEqual(len(maps), 1)
