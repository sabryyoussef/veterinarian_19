# -*- coding: utf-8 -*-
"""Regression: Test deploy SHA gate + staging runner wiring contracts."""
import inspect

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "devhub_deploy_gate")
class TestDeployShaAndRunnerContracts(TransactionCase):
    def test_verify_sha_helper_uses_ls_remote(self):
        Workspace = self.env["dev.execution.workspace"]
        src = inspect.getsource(Workspace._verify_sha_on_branch)
        self.assertIn("ls-remote", src)
        self.assertIn("dev_deploy_skip_remote", src)
        self.assertIn("production", src)

    def test_staging_runner_helper_exists(self):
        Workspace = self.env["dev.execution.workspace"]
        self.assertTrue(hasattr(Workspace, "_run_allowlisted_staging_runner"))
        src = inspect.getsource(Workspace._run_allowlisted_staging_runner)
        self.assertIn("pet_spot_elsahel_test", src)
        self.assertIn("--confirm-live", src)
        self.assertNotIn("-u all", src)
