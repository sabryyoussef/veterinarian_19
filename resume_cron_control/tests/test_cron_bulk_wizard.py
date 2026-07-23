# -*- coding: utf-8 -*-
"""
Tests for resume_cron_control.

Workflow covered (no browser):
  - Wizard enable / disable scheduled jobs
  - Wizard change interval (with validation)
  - Wizard run_now (trigger via method_direct_trigger)
  - Validation: no crons selected → UserError
  - Validation: interval < 1 → UserError
  - Validation: run_now > 25 jobs → UserError
  - default_get pre-fills cron_ids from active_ids context
"""

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestResumeCronBulkWizard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Wizard = cls.env["resume.cron.bulk.wizard"]
        cls.Cron = cls.env["ir.cron"]

    # ── helpers ───────────────────────────────────────────────────────────────

    def _make_cron(self, name="Test Cron", active=True):
        """Create a minimal ir.cron that can be toggled."""
        model = self.env["ir.model"].search([("model", "=", "res.partner")], limit=1)
        return self.Cron.sudo().create(
            {
                "name": name,
                "model_id": model.id,
                "state": "code",
                "code": "model.search([])",
                "interval_number": 1,
                "interval_type": "hours",
                "numbercall": -1,
                "active": active,
            }
        )

    def _wizard(self, crons, operation, **kwargs):
        vals = {
            "cron_ids": [(6, 0, crons.ids)],
            "operation": operation,
        }
        vals.update(kwargs)
        return self.Wizard.create(vals)

    # ── enable / disable ──────────────────────────────────────────────────────

    def test_enable_inactive_cron(self):
        cron = self._make_cron("Disabled Cron", active=False)
        w = self._wizard(cron, "enable")
        w.action_apply()
        self.assertTrue(cron.active)

    def test_disable_active_cron(self):
        cron = self._make_cron("Active Cron", active=True)
        w = self._wizard(cron, "disable")
        w.action_apply()
        self.assertFalse(cron.active)

    def test_enable_multiple_crons(self):
        c1 = self._make_cron("C1", active=False)
        c2 = self._make_cron("C2", active=False)
        w = self._wizard(c1 | c2, "enable")
        w.action_apply()
        self.assertTrue(c1.active)
        self.assertTrue(c2.active)

    # ── change interval ───────────────────────────────────────────────────────

    def test_change_interval(self):
        cron = self._make_cron("Interval Cron")
        w = self._wizard(cron, "interval", interval_number=30, interval_type="minutes")
        w.action_apply()
        self.assertEqual(cron.interval_number, 30)
        self.assertEqual(cron.interval_type, "minutes")

    def test_change_interval_hours(self):
        cron = self._make_cron("Hours Cron")
        w = self._wizard(cron, "interval", interval_number=6, interval_type="hours")
        w.action_apply()
        self.assertEqual(cron.interval_number, 6)
        self.assertEqual(cron.interval_type, "hours")

    def test_interval_zero_raises_user_error(self):
        cron = self._make_cron("Zero Interval")
        w = self._wizard(cron, "interval", interval_number=0, interval_type="minutes")
        with self.assertRaises(UserError):
            w.action_apply()

    def test_interval_negative_raises_user_error(self):
        cron = self._make_cron("Neg Interval")
        w = self._wizard(cron, "interval", interval_number=-5, interval_type="hours")
        with self.assertRaises(UserError):
            w.action_apply()

    # ── validation: empty crons list ─────────────────────────────────────────

    def test_no_crons_raises_user_error(self):
        w = self._wizard(self.Cron.browse([]), "enable")
        with self.assertRaises(UserError):
            w.action_apply()

    # ── run_now: too many crons ───────────────────────────────────────────────

    def test_run_now_over_limit_raises(self):
        """More than 25 crons selected for run_now must raise UserError."""
        model = self.env["ir.model"].search([("model", "=", "res.partner")], limit=1)
        crons = self.Cron.sudo().browse([])
        for i in range(26):
            crons |= self.Cron.sudo().create(
                {
                    "name": f"Batch Cron {i}",
                    "model_id": model.id,
                    "state": "code",
                    "code": "model.search([])",
                    "interval_number": 1,
                    "interval_type": "hours",
                    "numbercall": -1,
                    "active": False,
                }
            )
        w = self._wizard(crons, "run_now")
        with self.assertRaises(UserError):
            w.action_apply()

    # ── action_apply returns window close ─────────────────────────────────────

    def test_action_apply_returns_close_action(self):
        cron = self._make_cron("Return Check")
        w = self._wizard(cron, "enable")
        result = w.action_apply()
        self.assertEqual(result.get("type"), "ir.actions.act_window_close")

    # ── default_get pre-fills from context ───────────────────────────────────

    def test_default_get_prefills_cron_ids(self):
        cron = self._make_cron("Context Cron")
        ctx = {"active_model": "ir.cron", "active_ids": [cron.id]}
        w = self.Wizard.with_context(**ctx)
        defaults = w.default_get(["cron_ids", "operation"])
        # default_get returns Many2many commands: [(6, 0, [id, ...])] or plain [ids]
        raw = defaults.get("cron_ids") or []
        if raw and isinstance(raw[0], (list, tuple)):
            # ORM command style: [(6, 0, [ids])]
            ids = raw[0][2]
        else:
            ids = list(raw)
        self.assertIn(cron.id, ids)
