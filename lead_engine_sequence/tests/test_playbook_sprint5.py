# -*- coding: utf-8 -*-

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLeadEnginePlaybookSprint5(TransactionCase):
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
        cls.user = cls.env.ref("base.user_admin")
        cls.source = cls.Source.create(
            {
                "name": "S5 Source",
                "code": "S5_SRC",
                "channel": "api",
                "company_id": cls.company.id,
            }
        )

    def _lead_vals(self, **kwargs):
        vals = {"company_id": self.company.id}
        vals.update(kwargs)
        return vals

    def _playbook(self, code):
        return self.Playbook.create(
            {
                "name": "S5 PB",
                "code": code,
                "company_id": self.company.id,
            }
        )

    def test_cancel_run_skips_open_lines(self):
        pb = self._playbook("CXL")
        self.Step.create(
            {
                "playbook_id": pb.id,
                "sequence": 1,
                "name": "Later",
                "step_type": "assign_owner",
                "delay_unit": "hours",
                "delay_amount": 48,
                "assign_user_id": self.user.id,
            }
        )
        lead = self.Lead.create(
            self._lead_vals(
                name="Cx",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        run = self.Svc.start_playbook(lead, pb)
        self.assertEqual(run.state, "running")
        self.Svc.cancel_run(run)
        self.assertEqual(run.state, "cancelled")
        self.assertTrue(all(l.state == "skipped" for l in run.line_ids))

    def test_retry_errored_run_re_executes_step(self):
        act = self.env["ir.actions.server"].create(
            {
                "name": "S5 Fail then ok",
                "model_id": self.env["ir.model"]._get("crm.lead").id,
                "state": "code",
                "code": "raise UserError('fail_once')",
            }
        )
        pb = self._playbook("RTRY")
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
                name="R",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        run = self.Svc.start_playbook(lead, pb)
        self.assertEqual(run.state, "error")
        act.code = (
            "for record in records:\n"
            "    record.write({'name': (record.name or '') + ' ok'})"
        )
        self.Svc.retry_errored_run(run)
        self.assertEqual(run.state, "done")
        self.assertTrue(lead.name.endswith(" ok"))

    def test_retry_non_error_raises(self):
        pb = self._playbook("NR")
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
        lead = self.Lead.create(
            self._lead_vals(
                name="NR",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        run = self.Svc.start_playbook(lead, pb)
        self.assertEqual(run.state, "done")
        with self.assertRaises(UserError):
            self.Svc.retry_errored_run(run)

    def test_playbook_run_stats_compute(self):
        pb = self._playbook("STAT")
        self.Step.create(
            {
                "playbook_id": pb.id,
                "sequence": 1,
                "name": "A",
                "step_type": "assign_owner",
                "delay_unit": "immediate",
                "delay_amount": 0,
                "assign_user_id": self.user.id,
            }
        )
        lead = self.Lead.create(
            self._lead_vals(
                name="St",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        self.Svc.start_playbook(lead, pb)
        pb.invalidate_recordset()
        self.assertEqual(pb.run_count_total, 1)
        self.assertEqual(pb.run_count_done, 1)
        self.assertEqual(pb.run_count_running, 0)
        self.assertEqual(pb.run_count_error, 0)

    def test_pending_due_line_count_on_running(self):
        pb = self._playbook("DUE")
        self.Step.create(
            {
                "playbook_id": pb.id,
                "sequence": 1,
                "name": "Later",
                "step_type": "assign_owner",
                "delay_unit": "hours",
                "delay_amount": 10,
                "assign_user_id": self.user.id,
            }
        )
        lead = self.Lead.create(
            self._lead_vals(
                name="Due",
                lead_engine_source_id=self.source.id,
                team_id=False,
                user_id=False,
            )
        )
        run = self.Svc.start_playbook(lead, pb)
        run.line_ids.write({"scheduled_at": fields.Datetime.now()})
        run.invalidate_recordset()
        self.assertEqual(run.pending_due_line_count, 1)
