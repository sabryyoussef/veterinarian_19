# -*- coding: utf-8 -*-

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLeadEnginePlaybookSprint4(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Source = cls.env["lead.engine.source"]
        cls.Lead = cls.env["crm.lead"]
        cls.Playbook = cls.env["lead.engine.playbook"]
        cls.Step = cls.env["lead.engine.playbook.step"]
        cls.Run = cls.env["lead.engine.playbook.run"]
        cls.Svc = cls.env["lead.engine.playbook.service"]
        cls.company = cls.env.company
        cls.team = cls.env["crm.team"].create(
            {"name": "PB Team", "company_id": cls.company.id}
        )
        cls.user = cls.env.ref("base.user_admin")
        cls.activity_type = cls.env.ref("mail.mail_activity_data_call")
        cls.source = cls.Source.create(
            {
                "name": "PB Source",
                "code": "PB_SRC",
                "channel": "api",
                "company_id": cls.company.id,
            }
        )

    def _playbook(self, code="PB1", **kwargs):
        vals = {
            "name": "Test PB",
            "code": code,
            "company_id": self.company.id,
        }
        vals.update(kwargs)
        return self.Playbook.create(vals)

    def _lead_vals(self, **kwargs):
        vals = {"company_id": self.company.id}
        vals.update(kwargs)
        return vals

    def _template(self):
        return self.env["mail.template"].create(
            {
                "name": "LE PB Test",
                "model_id": self.env["ir.model"]._get("crm.lead").id,
                "subject": "Hello",
                "body_html": "<p>Test</p>",
            }
        )

    def test_manual_start_playbook(self):
        pb = self._playbook(code="MAN")
        self.Step.create(
            {
                "playbook_id": pb.id,
                "sequence": 1,
                "name": "Assign",
                "step_type": "assign_owner",
                "delay_unit": "immediate",
                "delay_amount": 0,
                "assign_user_id": self.user.id,
            }
        )
        lead = self.Lead.create(
            self._lead_vals(
                name="L1",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        run = self.Svc.start_playbook(lead, pb)
        self.assertEqual(run.state, "done")
        self.assertEqual(lead.user_id, self.user)
        self.assertTrue(all(l.state == "done" for l in run.line_ids))

    def test_auto_start_after_qualification(self):
        pb = self._playbook(code="AUTO")
        self.Step.create(
            {
                "playbook_id": pb.id,
                "sequence": 1,
                "name": "Assign",
                "step_type": "assign_owner",
                "delay_unit": "immediate",
                "delay_amount": 0,
                "assign_team_id": self.team.id,
            }
        )
        self.source.write(
            {
                "playbook_id": pb.id,
                "playbook_auto_start": True,
                "playbook_auto_start_duplicate": False,
            }
        )
        lead = self.Lead.create(
            self._lead_vals(
                name="Auto",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        self.env["lead.engine.qualification.pipeline"].apply(lead)
        self.Svc.try_auto_start_after_qualification(lead)
        runs = self.Run.search([("lead_id", "=", lead.id)])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs.state, "done")
        self.assertEqual(lead.team_id, self.team)

    def test_duplicate_does_not_auto_start_by_default(self):
        pb = self._playbook(code="DUP")
        self.Step.create(
            {
                "playbook_id": pb.id,
                "sequence": 1,
                "name": "Assign",
                "step_type": "assign_owner",
                "delay_unit": "immediate",
                "delay_amount": 0,
                "assign_user_id": self.user.id,
            }
        )
        self.source.write(
            {
                "playbook_id": pb.id,
                "playbook_auto_start": True,
                "playbook_auto_start_duplicate": False,
            }
        )
        first = self.Lead.create(
            self._lead_vals(
                name="F",
                lead_engine_source_id=self.source.id,
                external_ref="x-dup",
                team_id=False,
                user_id=False,
            )
        )
        self.env["lead.engine.qualification.pipeline"].apply(first)
        second = self.Lead.create(
            self._lead_vals(
                name="S",
                lead_engine_source_id=self.source.id,
                external_ref="x-dup",
                team_id=False,
                user_id=False,
            )
        )
        self.env["lead.engine.qualification.pipeline"].apply(second)
        self.assertEqual(second.duplicate_status, "duplicate")
        self.Svc.try_auto_start_after_qualification(second)
        dup_runs = self.Run.search([("lead_id", "=", second.id)])
        self.assertFalse(dup_runs)

    def test_immediate_activity_step(self):
        pb = self._playbook(code="ACT")
        self.Step.create(
            {
                "playbook_id": pb.id,
                "sequence": 1,
                "name": "Call",
                "step_type": "create_activity",
                "delay_unit": "immediate",
                "delay_amount": 0,
                "activity_type_id": self.activity_type.id,
                "activity_summary": "PB call",
            }
        )
        lead = self.Lead.create(
            self._lead_vals(
                name="Act",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        run = self.Svc.start_playbook(lead, pb)
        acts = self.env["mail.activity"].search(
            [("res_model", "=", "crm.lead"), ("res_id", "=", lead.id)]
        )
        self.assertTrue(acts)
        self.assertEqual(run.state, "done")

    def test_email_template_step_creates_mail(self):
        tpl = self._template()
        pb = self._playbook(code="MAIL")
        self.Step.create(
            {
                "playbook_id": pb.id,
                "sequence": 1,
                "name": "Mail",
                "step_type": "send_email_template",
                "delay_unit": "immediate",
                "delay_amount": 0,
                "mail_template_id": tpl.id,
            }
        )
        lead = self.Lead.create(
            self._lead_vals(
                name="Mail lead",
                email_from="m@example.com",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        before = self.env["mail.mail"].search_count([("model", "=", "crm.lead")])
        run = self.Svc.start_playbook(lead, pb)
        after = self.env["mail.mail"].search_count([("model", "=", "crm.lead")])
        self.assertGreater(after, before)
        self.assertEqual(run.state, "done")

    def test_delay_days_schedules_future_datetime(self):
        pb = self._playbook(code="DAYS")
        self.Step.create(
            {
                "playbook_id": pb.id,
                "sequence": 1,
                "name": "Later",
                "step_type": "assign_owner",
                "delay_unit": "days",
                "delay_amount": 3,
                "assign_user_id": self.user.id,
            }
        )
        lead = self.Lead.create(
            self._lead_vals(
                name="Days",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        run = self.Svc.start_playbook(lead, pb)
        line = run.line_ids[0]
        self.assertEqual(run.state, "running")
        delta = line.scheduled_at - run.started_at
        self.assertGreaterEqual(delta.total_seconds(), 3 * 86400 - 1)

    def test_delayed_step_schedules_then_executes(self):
        pb = self._playbook(code="DEL")
        self.Step.create(
            {
                "playbook_id": pb.id,
                "sequence": 1,
                "name": "Later",
                "step_type": "assign_owner",
                "delay_unit": "hours",
                "delay_amount": 24,
                "assign_user_id": self.user.id,
            }
        )
        lead = self.Lead.create(
            self._lead_vals(
                name="Del",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        run = self.Svc.start_playbook(lead, pb)
        self.assertEqual(run.state, "running")
        line = run.line_ids[0]
        self.assertEqual(line.state, "pending")
        line.write({"scheduled_at": fields.Datetime.now()})
        self.Svc.execute_due_steps(run=run)
        self.assertEqual(line.state, "done")
        self.assertEqual(lead.user_id, self.user)
        self.assertEqual(run.state, "done")

    def test_sequential_two_steps(self):
        """Two immediate steps run in order; avoid team-then-user (CRM may reassign team from user)."""
        pb = self._playbook(code="SEQ")
        self.Step.create(
            {
                "playbook_id": pb.id,
                "sequence": 1,
                "name": "A",
                "step_type": "create_activity",
                "delay_unit": "immediate",
                "delay_amount": 0,
                "activity_type_id": self.activity_type.id,
                "activity_summary": "Seq step 1",
            }
        )
        self.Step.create(
            {
                "playbook_id": pb.id,
                "sequence": 2,
                "name": "B",
                "step_type": "assign_owner",
                "delay_unit": "immediate",
                "delay_amount": 0,
                "assign_team_id": self.team.id,
                "assign_user_id": self.user.id,
            }
        )
        lead = self.Lead.create(
            self._lead_vals(
                name="Seq",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        run = self.Svc.start_playbook(lead, pb)
        self.assertEqual(run.state, "done")
        acts = self.env["mail.activity"].search(
            [("res_model", "=", "crm.lead"), ("res_id", "=", lead.id)]
        )
        self.assertTrue(acts)
        self.assertEqual(lead.team_id, self.team)
        self.assertEqual(lead.user_id, self.user)

    def test_failed_step_sets_error(self):
        act = self.env["ir.actions.server"].create(
            {
                "name": "LE PB Fail",
                "model_id": self.env["ir.model"]._get("crm.lead").id,
                "state": "code",
                "code": "raise UserError('pb_fail')",
            }
        )
        pb = self._playbook(code="ERR")
        self.Step.create(
            {
                "playbook_id": pb.id,
                "sequence": 1,
                "name": "Boom",
                "step_type": "server_action",
                "delay_unit": "immediate",
                "delay_amount": 0,
                "server_action_id": act.id,
            }
        )
        lead = self.Lead.create(
            self._lead_vals(
                name="Err",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        run = self.Svc.start_playbook(lead, pb)
        self.assertEqual(run.state, "error")
        self.assertTrue(all(l.state == "error" for l in run.line_ids))

    def test_start_playbook_duplicate_without_force_raises(self):
        pb = self._playbook(code="ND")
        self.Step.create(
            {
                "playbook_id": pb.id,
                "sequence": 1,
                "name": "X",
                "step_type": "assign_owner",
                "delay_unit": "immediate",
                "delay_amount": 0,
                "assign_user_id": self.user.id,
            }
        )
        first = self.Lead.create(
            self._lead_vals(
                name="A",
                lead_engine_source_id=self.source.id,
                external_ref="nd-1",
                team_id=False,
                user_id=False,
            )
        )
        second = self.Lead.create(
            self._lead_vals(
                name="B",
                lead_engine_source_id=self.source.id,
                external_ref="nd-1",
                team_id=False,
                user_id=False,
            )
        )
        self.env["lead.engine.qualification.pipeline"].apply(first)
        self.env["lead.engine.qualification.pipeline"].apply(second)
        with self.assertRaises(UserError):
            self.Svc.start_playbook(second, pb, force_duplicate=False)

    def test_manual_start_on_duplicate_succeeds_when_forced(self):
        """Mirrors UI manual action: force_duplicate allows playbooks on duplicate rows."""
        pb = self._playbook(code="FD")
        self.Step.create(
            {
                "playbook_id": pb.id,
                "sequence": 1,
                "name": "Assign",
                "step_type": "assign_owner",
                "delay_unit": "immediate",
                "delay_amount": 0,
                "assign_user_id": self.user.id,
            }
        )
        first = self.Lead.create(
            self._lead_vals(
                name="M1",
                lead_engine_source_id=self.source.id,
                external_ref="fd-1",
                team_id=False,
                user_id=False,
            )
        )
        second = self.Lead.create(
            self._lead_vals(
                name="M2",
                lead_engine_source_id=self.source.id,
                external_ref="fd-1",
                team_id=False,
                user_id=False,
            )
        )
        self.env["lead.engine.qualification.pipeline"].apply(first)
        self.env["lead.engine.qualification.pipeline"].apply(second)
        self.assertEqual(second.duplicate_status, "duplicate")
        run = self.Svc.start_playbook(second, pb, force_duplicate=True)
        self.assertEqual(run.state, "done")
        self.assertEqual(second.user_id, self.user)
