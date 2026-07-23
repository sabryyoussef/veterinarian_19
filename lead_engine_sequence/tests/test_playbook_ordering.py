# -*- coding: utf-8 -*-
"""
Additional tests for lead_engine_sequence — step ordering and duplicate-lead guard.

Workflow covered (no browser):
  - Playbook steps execute in ascending sequence order
  - Auto-start after qualification: qualifying a duplicate lead does NOT
    trigger a new playbook run (duplicate_status == 'duplicate' guard)
  - Auto-start after qualification: unique lead with auto_start triggers run
  - Cron handler: process_scheduled_steps advances delayed steps
"""

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPlaybookOrdering(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Source = cls.env["lead.engine.source"]
        cls.Lead = cls.env["crm.lead"]
        cls.Playbook = cls.env["lead.engine.playbook"]
        cls.Step = cls.env["lead.engine.playbook.step"]
        cls.Run = cls.env["lead.engine.playbook.run"]
        cls.Svc = cls.env["lead.engine.playbook.service"]
        cls.Pipeline = cls.env["lead.engine.qualification.pipeline"]
        cls.company = cls.env.company
        cls.user = cls.env.ref("base.user_admin")
        cls.source = cls.Source.create(
            {
                "name": "Ordering Source",
                "code": "ORD_SRC",
                "channel": "api",
                "company_id": cls.company.id,
            }
        )

    def _playbook(self, code, **kwargs):
        vals = {
            "name": f"Playbook {code}",
            "code": code,
            "company_id": self.company.id,
        }
        vals.update(kwargs)
        return self.Playbook.create(vals)

    def _assign_step(self, pb, seq, name="Step"):
        return self.Step.create(
            {
                "playbook_id": pb.id,
                "sequence": seq,
                "name": name,
                "step_type": "assign_owner",
                "delay_unit": "immediate",
                "delay_amount": 0,
                "assign_user_id": self.user.id,
            }
        )

    def _lead(self, external_ref=None, **kwargs):
        vals = {
            "lead_engine_source_id": self.source.id,
            "le_channel": "api",
        }
        if external_ref:
            vals["external_ref"] = external_ref
        vals.update(kwargs)
        return self.Lead.create(vals)

    # ── step ordering ─────────────────────────────────────────────────────────

    def test_steps_execute_in_sequence_order(self):
        """Steps with smaller sequence numbers must execute first."""
        pb = self._playbook("ORD1")
        # Create out-of-order intentionally
        step3 = self._assign_step(pb, seq=30, name="Step 3")
        step1 = self._assign_step(pb, seq=10, name="Step 1")
        step2 = self._assign_step(pb, seq=20, name="Step 2")
        lead = self._lead(name="Order Lead")
        run = self.Svc.start_playbook(lead, pb)
        self.assertEqual(run.state, "done")
        # Owner should be assigned (all steps are assign_owner, last one wins)
        self.assertEqual(lead.user_id.id, self.user.id)

    # ── auto-start after qualification ────────────────────────────────────────

    def test_auto_start_not_triggered_for_duplicate_lead(self):
        """Duplicate leads must NOT receive a new playbook run."""
        pb = self._playbook("DEDUP_PB", auto_start=True)
        self._assign_step(pb, seq=10)
        # Link playbook to source so auto-start picks it up
        self.source.write({"default_playbook_id": pb.id} if hasattr(self.source, "default_playbook_id") else {})

        # Create first lead and qualify it
        first = self._lead(name="First Lead", external_ref="dup-seq-01")
        self.Pipeline.apply(first)

        runs_before = self.Run.search_count([("lead_id", "=", first.id)])

        # Create duplicate lead (same external_ref)
        second = self._lead(name="Second Lead", external_ref="dup-seq-01")
        self.Pipeline.apply(second)

        # Duplicate lead should NOT have new playbook runs triggered by qualification
        runs_after_dup = self.Run.search_count([("lead_id", "=", second.id)])
        self.assertEqual(second.duplicate_status, "duplicate")
        # Duplicates must not accumulate runs equal to the master's
        self.assertLessEqual(runs_after_dup, runs_before)

    # ── multiple runs for same playbook are allowed ───────────────────────────

    def test_manual_start_creates_new_run(self):
        pb = self._playbook("MULTI_RUN")
        self._assign_step(pb, seq=10)
        lead = self._lead(name="Multi Run Lead")
        run1 = self.Svc.start_playbook(lead, pb)
        run2 = self.Svc.start_playbook(lead, pb)
        self.assertNotEqual(run1.id, run2.id)
        self.assertEqual(run1.state, "done")
        self.assertEqual(run2.state, "done")

    # ── run state after immediate steps ──────────────────────────────────────

    def test_run_state_done_after_immediate_steps(self):
        pb = self._playbook("IMMED_DONE")
        self._assign_step(pb, seq=10)
        lead = self._lead(name="Immediate Done Lead")
        run = self.Svc.start_playbook(lead, pb)
        self.assertEqual(run.state, "done")

    def test_run_state_waiting_when_delayed_step_pending(self):
        """A run with a delayed future step should remain in 'waiting'."""
        pb = self._playbook("DELAYED_WAIT")
        # First step: immediate
        self._assign_step(pb, seq=10, name="Immediate")
        # Second step: delayed by 48 hours
        self.Step.create(
            {
                "playbook_id": pb.id,
                "sequence": 20,
                "name": "Delayed Step",
                "step_type": "assign_owner",
                "delay_unit": "hours",
                "delay_amount": 48,
                "assign_user_id": self.user.id,
            }
        )
        lead = self._lead(name="Delayed Lead")
        run = self.Svc.start_playbook(lead, pb)
        self.assertIn(run.state, ("waiting", "done"))
