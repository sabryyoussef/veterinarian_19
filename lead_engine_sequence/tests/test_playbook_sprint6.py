# -*- coding: utf-8 -*-

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLeadEnginePlaybookSprint6(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Source = cls.env["lead.engine.source"]
        cls.Lead = cls.env["crm.lead"]
        cls.Playbook = cls.env["lead.engine.playbook"]
        cls.Step = cls.env["lead.engine.playbook.step"]
        cls.Svc = cls.env["lead.engine.playbook.service"]
        cls.company = cls.env.company
        cls.user = cls.env.ref("base.user_admin")
        cls.activity_type = cls.env.ref("mail.mail_activity_data_call")
        cls.source = cls.Source.create(
            {
                "name": "S6 Source",
                "code": "S6_SRC",
                "channel": "api",
                "company_id": cls.company.id,
            }
        )

    def _lead_vals(self, **kwargs):
        vals = {"company_id": self.company.id}
        vals.update(kwargs)
        return vals

    def _playbook(self, code, **extra):
        vals = {
            "name": "S6 PB",
            "code": code,
            "company_id": self.company.id,
        }
        vals.update(extra)
        return self.Playbook.create(vals)

    def _assign_step(self, pb, seq=1):
        return self.Step.create(
            {
                "playbook_id": pb.id,
                "sequence": seq,
                "name": "Assign",
                "step_type": "assign_owner",
                "delay_unit": "immediate",
                "delay_amount": 0,
                "assign_user_id": self.user.id,
            }
        )

    def _delayed_assign_step(self, pb, seq=1, hours=48):
        return self.Step.create(
            {
                "playbook_id": pb.id,
                "sequence": seq,
                "name": "Later assign",
                "step_type": "assign_owner",
                "delay_unit": "hours",
                "delay_amount": hours,
                "assign_user_id": self.user.id,
            }
        )

    def test_duplicate_active_run_blocked_same_playbook(self):
        pb = self._playbook("DUPRUN")
        self._delayed_assign_step(pb)
        lead = self.Lead.create(
            self._lead_vals(
                name="Dr",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        self.Svc.start_playbook(lead, pb)
        with self.assertRaises(UserError):
            self.Svc.start_playbook(lead, pb)

    def test_allow_duplicate_active_run_when_forced(self):
        pb = self._playbook("DUPOK")
        self._delayed_assign_step(pb)
        lead = self.Lead.create(
            self._lead_vals(
                name="Dr2",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        r1 = self.Svc.start_playbook(lead, pb)
        r2 = self.Svc.start_playbook(
            lead, pb, allow_duplicate_active_run=True
        )
        self.assertEqual(r1.state, "running")
        self.assertEqual(r2.state, "running")
        self.assertNotEqual(r1.id, r2.id)

    def test_two_different_playbooks_can_run_concurrently(self):
        pb1 = self._playbook("P1")
        self._delayed_assign_step(pb1)
        pb2 = self._playbook("P2")
        self._delayed_assign_step(pb2)
        lead = self.Lead.create(
            self._lead_vals(
                name="Two",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        self.Svc.start_playbook(lead, pb1)
        self.Svc.start_playbook(lead, pb2)
        runs = self.env["lead.engine.playbook.run"].search(
            [("lead_id", "=", lead.id), ("state", "=", "running")]
        )
        self.assertEqual(len(runs), 2)

    def test_execute_due_steps_idempotent(self):
        pb = self._playbook("IDEM")
        self.Step.create(
            {
                "playbook_id": pb.id,
                "sequence": 1,
                "name": "Act",
                "step_type": "create_activity",
                "delay_unit": "immediate",
                "delay_amount": 0,
                "activity_type_id": self.activity_type.id,
                "activity_summary": "once",
            }
        )
        lead = self.Lead.create(
            self._lead_vals(
                name="Id",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        run = self.Svc.start_playbook(lead, pb)
        self.Svc.execute_due_steps(run=run)
        self.Svc.execute_due_steps(run=run)
        acts = self.env["mail.activity"].search(
            [("res_model", "=", "crm.lead"), ("res_id", "=", lead.id)]
        )
        self.assertEqual(len(acts), 1)
        self.assertEqual(run.state, "done")

    def test_execute_step_second_call_noop(self):
        pb = self._playbook("STEP2")
        self._assign_step(pb)
        lead = self.Lead.create(
            self._lead_vals(
                name="S2",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        run = self.Svc.start_playbook(lead, pb)
        line = run.line_ids[0]
        self.assertEqual(line.state, "done")
        self.Svc.execute_step(line)
        self.assertEqual(line.state, "done")

    def test_finalize_run_twice_stable(self):
        pb = self._playbook("FIN2")
        self._assign_step(pb)
        lead = self.Lead.create(
            self._lead_vals(
                name="F2",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        run = self.Svc.start_playbook(lead, pb)
        self.assertEqual(run.state, "done")
        self.Svc.finalize_run(run)
        self.Svc.finalize_run(run)
        self.assertEqual(run.state, "done")

    def test_cancel_running_then_done_lines_unchanged(self):
        pb = self._playbook("CXD")
        self._assign_step(pb, seq=1)
        self.Step.create(
            {
                "playbook_id": pb.id,
                "sequence": 2,
                "name": "Later",
                "step_type": "assign_owner",
                "delay_unit": "hours",
                "delay_amount": 99,
                "assign_user_id": self.user.id,
            }
        )
        lead = self.Lead.create(
            self._lead_vals(
                name="Cxd",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        run = self.Svc.start_playbook(lead, pb)
        line1 = run.line_ids.filtered(lambda l: l.sequence == 1)
        self.assertEqual(line1.state, "done")
        self.Svc.cancel_run(run)
        self.assertEqual(line1.state, "done")
        self.assertEqual(run.state, "cancelled")

    def test_cancel_done_raises(self):
        pb = self._playbook("CXDN")
        self._assign_step(pb)
        lead = self.Lead.create(
            self._lead_vals(
                name="Cd",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        run = self.Svc.start_playbook(lead, pb)
        with self.assertRaises(UserError):
            self.Svc.cancel_run(run)

    def test_inactive_playbook_auto_start_skipped(self):
        pb = self._playbook("INAC", active=False)
        self._assign_step(pb)
        self.source.write(
            {
                "playbook_id": pb.id,
                "playbook_auto_start": True,
            }
        )
        lead = self.Lead.create(
            self._lead_vals(
                name="In",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        self.env["lead.engine.qualification.pipeline"].apply(lead)
        self.Svc.try_auto_start_after_qualification(lead)
        self.assertFalse(
            self.env["lead.engine.playbook.run"].search(
                [("lead_id", "=", lead.id)]
            )
        )

    def test_empty_playbook_start_raises(self):
        pb = self._playbook("EMPTY")
        lead = self.Lead.create(
            self._lead_vals(
                name="Em",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        with self.assertRaises(UserError):
            self.Svc.start_playbook(lead, pb)

    def test_auto_start_skips_when_no_steps(self):
        pb = self._playbook("NOSTEP")
        self.source.write(
            {
                "playbook_id": pb.id,
                "playbook_auto_start": True,
            }
        )
        lead = self.Lead.create(
            self._lead_vals(
                name="Ns",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        self.env["lead.engine.qualification.pipeline"].apply(lead)
        self.Svc.try_auto_start_after_qualification(lead)
        self.assertFalse(
            self.env["lead.engine.playbook.run"].search(
                [("lead_id", "=", lead.id)]
            )
        )

    def test_archived_email_template_blocked_before_run(self):
        tpl = self.env["mail.template"].create(
            {
                "name": "S6 Tpl",
                "model_id": self.env["ir.model"]._get("crm.lead").id,
                "subject": "Hi",
                "body_html": "<p>x</p>",
            }
        )
        pb = self._playbook("BADMAIL")
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
        tpl.active = False
        lead = self.Lead.create(
            self._lead_vals(
                name="Bm",
                email_from="x@example.com",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        with self.assertRaises(UserError):
            self.Svc.start_playbook(lead, pb)

    def test_retry_only_from_error(self):
        pb = self._playbook("RONLY")
        self._assign_step(pb)
        lead = self.Lead.create(
            self._lead_vals(
                name="Ro",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        run = self.Svc.start_playbook(lead, pb)
        with self.assertRaises(UserError):
            self.Svc.retry_errored_run(run)
