# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCodeDatabaseAnalysis(TransactionCase):
    """Resolution, safety, persistence, and idempotency for code/DB analysis."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env["dev.project"].search([("code", "=", "TOURZ")], limit=1)
        cls.repo = cls.env["dev.repository"].search(
            [("project_id", "=", cls.project.id)], limit=1
        )
        cls.env_rec = cls.env["dev.environment"].search(
            [
                ("project_id", "=", cls.project.id),
                ("database_identifier", "=", "tours_trading_test"),
            ],
            limit=1,
        )
        cls.task = cls.env["project.task"].browse(2717)
        cls.work = cls.env["dev.work.item"].search(
            [("odoo_task_id", "=", 2717)], limit=1
        )
        if not (cls.project and cls.repo and cls.env_rec and cls.task and cls.work):
            # Fresh modular UAT DB does not carry TOURZ pilot fixtures.
            raise unittest.SkipTest("TOURZ pilot fixtures missing on this database.")
        cls.master_path = "/home/sabry/odoo_base/base_odoo_19/projects/tours-trading"

    def _healthy_analyze(self):
        with patch(
            "odoo.addons.devhub_code_analysis.models.dev_work_code_analysis.urllib.request.urlopen"
        ) as mock_open:
            mock_open.return_value.__enter__.return_value.status = 200
            return self.work.action_analyze_against_code_database()

    def test_2717_resolves_master_repo_and_tours_db(self):
        self.assertEqual(
            self.work.preferred_repository_id.working_directory,
            self.master_path,
        )
        self.assertEqual(
            self.work.preferred_environment_id.database_identifier,
            "tours_trading_test",
        )
        self.assertEqual(self.work.preferred_environment_id.port, 8031)
        ctx = self.work._resolve_code_analysis_context()
        self.assertEqual(ctx["path"], os.path.realpath(self.master_path))
        self.assertEqual(ctx["environment"].database_identifier, "tours_trading_test")

    def test_wrong_project_repository_rejected(self):
        other = self.env["dev.project"].search([("code", "=", "PETSPOT")], limit=1)
        other_repo = other.default_repository_id
        self.assertTrue(other_repo)
        with self.assertRaises(ValidationError):
            self.work.write({"preferred_repository_id": other_repo.id})
        # Resolve-layer ownership guard (bypass ORM constrain via SQL).
        self.env.cr.execute(
            "UPDATE dev_work_item SET preferred_repository_id = %s WHERE id = %s",
            (other_repo.id, self.work.id),
        )
        self.work.invalidate_recordset(["preferred_repository_id"])
        with self.assertRaises(UserError):
            self.work._resolve_code_analysis_context()
        self.env.cr.execute(
            "UPDATE dev_work_item SET preferred_repository_id = %s WHERE id = %s",
            (self.repo.id, self.work.id),
        )
        self.work.invalidate_recordset(["preferred_repository_id"])

    def test_wrong_project_environment_rejected(self):
        other = self.env["dev.project"].search([("code", "=", "PETSPOT")], limit=1)
        other_env = other.default_environment_id
        self.assertTrue(other_env)
        with self.assertRaises(ValidationError):
            self.work.write({"preferred_environment_id": other_env.id})
        self.env.cr.execute(
            "UPDATE dev_work_item SET preferred_environment_id = %s WHERE id = %s",
            (other_env.id, self.work.id),
        )
        self.work.invalidate_recordset(["preferred_environment_id"])
        with self.assertRaises(UserError):
            self.work._resolve_code_analysis_context()
        self.env.cr.execute(
            "UPDATE dev_work_item SET preferred_environment_id = %s WHERE id = %s",
            (self.env_rec.id, self.work.id),
        )
        self.work.invalidate_recordset(["preferred_environment_id"])

    def test_production_environment_rejected(self):
        prod = self.env["dev.environment"].create(
            {
                "name": "Fake prod for analysis deny",
                "project_id": self.project.id,
                "environment_type": "production",
                "environment_role": "dedicated_test",
                "runtime_id": self.env_rec.runtime_id.id,
                "machine_id": self.env_rec.machine_id.id,
                "odoo_version": "19.0",
                "database_identifier": "tours_trading_test_fake_prod",
                "url": "http://127.0.0.1:1",
                "port": 1,
                "config_reference": self.env_rec.config_reference,
                "service_container_reference": "none",
                "data_sensitivity": "internal_test",
                "production_guard_policy": "deny",
            }
        )
        self.work.preferred_environment_id = prod
        with self.assertRaises(UserError):
            self.work._resolve_code_analysis_context()
        self.work.preferred_environment_id = self.env_rec

    def test_missing_path_rejected(self):
        missing = "/tmp/does-not-exist-tourz-analysis"
        self.repo.write(
            {
                "working_directory": missing,
                "canonical_remote_path": missing,
            }
        )
        with self.assertRaises(UserError):
            self.work._resolve_code_analysis_context()
        self.repo.write(
            {
                "working_directory": self.master_path,
                "canonical_remote_path": self.master_path,
            }
        )

    def test_non_allowlisted_path_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.repo.write(
                {
                    "working_directory": tmp,
                    "canonical_remote_path": tmp,
                }
            )
            with self.assertRaises(UserError):
                self.work._resolve_code_analysis_context()
        self.repo.write(
            {
                "working_directory": self.master_path,
                "canonical_remote_path": self.master_path,
            }
        )

    def test_analysis_persists_and_idempotent(self):
        action1 = self._healthy_analyze()
        analysis_id = action1["res_id"]
        analysis = self.env["dev.work.analysis"].browse(analysis_id)
        self.assertEqual(analysis.execution_state, "completed")
        self.assertEqual(analysis.analysis_kind, "code_database")
        self.assertEqual(analysis.database_identifier, "tours_trading_test")
        self.assertTrue(analysis.technical_findings)
        self.assertIn("tours-trading", analysis.reproduction_context or "")
        fingerprint = analysis.analysis_fingerprint
        count_before = self.env["dev.work.analysis"].search_count(
            [("work_item_id", "=", self.work.id)]
        )
        action2 = self._healthy_analyze()
        self.assertEqual(action2["res_id"], analysis_id)
        count_after = self.env["dev.work.analysis"].search_count(
            [("work_item_id", "=", self.work.id)]
        )
        self.assertEqual(count_before, count_after)
        self.assertEqual(
            self.env["dev.work.analysis"].browse(action2["res_id"]).analysis_fingerprint,
            fingerprint,
        )

    def test_changed_head_creates_new_revision(self):
        first = self._healthy_analyze()["res_id"]
        self.repo.head_cache = "b" * 40
        second = self._healthy_analyze()["res_id"]
        self.assertNotEqual(first, second)
        a1 = self.env["dev.work.analysis"].browse(first)
        a2 = self.env["dev.work.analysis"].browse(second)
        self.assertNotEqual(a1.analysis_fingerprint, a2.analysis_fingerprint)
        self.assertEqual(
            a2.execution_state,
            "completed",
            a2.error_details or a2.technical_findings,
        )

    def test_analysis_tab_domain_scoped_to_work_item(self):
        action = self._healthy_analyze()
        analysis = self.env["dev.work.analysis"].browse(action["res_id"])
        scoped = self.env["dev.work.analysis"].search(
            [("work_item_id", "=", self.work.id)]
        )
        self.assertIn(analysis, scoped)
        other = self.env["dev.work.analysis"].search(
            [("work_item_id", "!=", self.work.id)], limit=1
        )
        if other:
            self.assertNotIn(other, scoped)
