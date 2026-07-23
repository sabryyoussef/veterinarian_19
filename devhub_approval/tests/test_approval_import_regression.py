# -*- coding: utf-8 -*-
"""Regression: exact-hash approval must resolve DevWorkPlan (UAT NameError fix)."""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "devhub_approval")
class TestDevWorkPlanApprovalImport(TransactionCase):
    """Prove DevWorkPlan is imported and usable from the approval inherit module."""

    def test_devworkplan_symbol_imported_no_nameerror(self):
        from odoo.addons.devhub_approval.models import dev_work_plan_approval as mod

        self.assertTrue(hasattr(mod, "DevWorkPlan"))
        self.assertEqual(mod.DevWorkPlan._name, "dev.work.plan")
        # Runtime path used by action_approve_exact / action_reject
        Plan = self.env["dev.work.plan"]
        self.assertTrue(issubclass(mod.DevWorkPlan, type(Plan)))

    def test_approve_exact_method_bound_on_plan(self):
        Plan = self.env["dev.work.plan"]
        self.assertTrue(callable(getattr(Plan, "action_approve_exact", None)))
        self.assertTrue(callable(getattr(Plan, "action_reject", None)))
        # Source must reference imported class (not undefined name)
        import inspect
        from odoo.addons.devhub_approval.models import dev_work_plan_approval as mod

        src = inspect.getsource(mod.DevWorkPlanApproval.action_approve_exact)
        self.assertIn("super(DevWorkPlan", src)
        self.assertIsNotNone(mod.DevWorkPlan)
