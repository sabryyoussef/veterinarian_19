# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "linkedin_connector")
class TestLinkedinBulkWizardSchema(TransactionCase):
    """Guards against stale registry (server_wide_modules) missing new wizard fields."""

    def test_wizard_has_recurrence_fields(self):
        W = self.env["linkedin.post.bulk.schedule"]
        self.assertIn("recurrence_mode", W._fields, "Restart Odoo after code changes, then upgrade the module.")
        self.assertIn("schedule_count", W._fields, "Restart Odoo after code changes, then upgrade the module.")
