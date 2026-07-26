# -*- coding: utf-8 -*-
"""Tests for Dev Hub project OpenProject / Odoo task tabs."""
from __future__ import annotations

from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestDevProjectOpTabs(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env,
            login="dev-hub-op-tabs-mgr-%s" % cls.env.cr.dbname,
            groups=(
                "devhub_core.group_dev_hub_user,"
                "devhub_core.group_dev_hub_manager,"
                "project.group_project_manager"
            ),
        )
        cls.user = new_test_user(
            cls.env,
            login="dev-hub-op-tabs-user-%s" % cls.env.cr.dbname,
            groups="devhub_core.group_dev_hub_user,project.group_project_user",
        )
        cls.backend = cls.env["openproject.backend"].create(
            {
                "name": "OP tabs test backend",
                "api_url": "http://127.0.0.1:9",
                "public_url": "https://openproject.tabs.test.invalid",
                "verify_ssl": False,
                "enable_pull": True,
                "enable_push": False,
                "api_token": "test-token-not-for-ui",
            }
        )
        cls.odoo_project = cls.env["project.project"].create(
            {"name": "OP tabs Odoo project"}
        )
        cls.pmap = cls.env["openproject.project.map"].create(
            {
                "backend_id": cls.backend.id,
                "op_project_id": 900006,
                "op_project_name": "Tabs Torz Fixture",
                "odoo_project_id": cls.odoo_project.id,
                "active": True,
                "op_push_create": False,
            }
        )
        cls.task = cls.env["project.task"].create(
            {
                "name": "Tabs WP fixture",
                "project_id": cls.odoo_project.id,
                "op_backend_id": cls.backend.id,
                "op_project_id": 900006,
                "op_work_package_id": 900116,
                "op_url": "https://openproject.tabs.test.invalid/work_packages/900116",
                "op_sync_state": "synced",
            }
        )
        cls.dev_project = cls.env["dev.project"].create(
            {
                "name": "Tabs Dev Project",
                "code": "TABSTEST",
                "owner_id": cls.manager.id,
                "member_ids": [(4, cls.manager.id), (4, cls.user.id)],
                "production_policy": "Production denied for tabs fixture.",
                "agent_instruction_summary": "Tabs fixture only.",
                "openproject_map_ids": [(4, cls.pmap.id)],
            }
        )

    def test_mapped_tasks_and_op_subset(self):
        self.assertTrue(self.dev_project.has_openproject_mapping)
        self.assertEqual(self.dev_project.primary_odoo_project_id, self.odoo_project)
        self.assertIn(self.task, self.dev_project.mapped_task_ids)
        self.assertIn(self.task, self.dev_project.mapped_op_task_ids)
        bare = self.env["project.task"].create(
            {"name": "No OP", "project_id": self.odoo_project.id}
        )
        self.dev_project.invalidate_recordset()
        self.assertIn(bare, self.dev_project.mapped_task_ids)
        self.assertNotIn(bare, self.dev_project.mapped_op_task_ids)

    def test_empty_without_maps(self):
        empty = self.env["dev.project"].create(
            {
                "name": "Empty Tabs",
                "code": "TABSEMPTY",
                "owner_id": self.manager.id,
                "member_ids": [(4, self.manager.id)],
                "production_policy": "denied",
                "agent_instruction_summary": "empty",
            }
        )
        self.assertFalse(empty.has_openproject_mapping)
        self.assertFalse(empty.mapped_task_ids)
        self.assertFalse(empty.mapped_op_task_ids)

    def test_ensure_work_item_idempotent(self):
        action1 = self.dev_project._ensure_work_item_for_task(self.task)
        work_id = action1["res_id"]
        work = self.env["dev.work.item"].browse(work_id)
        self.assertEqual(work.odoo_task_id, self.task)
        self.assertEqual(work.dev_project_id, self.dev_project)
        self.assertTrue(work.source_message_ids)
        action2 = self.dev_project._ensure_work_item_for_task(self.task)
        self.assertEqual(action2["res_id"], work_id)
        self.assertEqual(
            self.env["dev.work.item"].search_count([("odoo_task_id", "=", self.task.id)]),
            1,
        )
        self.assertEqual(self.task.dev_work_item_id, work)

    def test_user_cannot_pull(self):
        with self.assertRaises(AccessError):
            self.dev_project.with_user(self.user).action_pull_openproject_maps()

    def test_pull_mocked_no_http(self):
        calls = []

        def fake_pull(self_map, raise_on_error=False):
            calls.append(self_map.id)
            return {
                "pulled": 1,
                "created": 0,
                "updated": 1,
                "skipped": 0,
                "warnings": 0,
                "errors": 0,
            }

        with patch.object(
            type(self.pmap), "action_pull", autospec=True, side_effect=fake_pull
        ):
            result = self.dev_project.with_user(self.manager).action_pull_openproject_maps()
        self.assertEqual(calls, [self.pmap.id])
        self.assertEqual(result["type"], "ir.actions.client")
        self.assertEqual(result["tag"], "display_notification")
        # Token must not appear in client payload
        self.assertNotIn("test-token", str(result))

    def test_form_view_tab_order_regression(self):
        view = self.env.ref("devhub_core.view_dev_project_form")
        # Use combined arch so optional module inherits (OpenProject tabs) are included.
        arch = self.env["dev.project"].get_view(view.id)["arch"]
        pages = []
        needle = 'string="'
        # Extract notebook page strings in order
        idx = 0
        while True:
            start = arch.find("<page ", idx)
            if start < 0:
                break
            s = arch.find(needle, start)
            e = arch.find('"', s + len(needle))
            pages.append(arch[s + len(needle) : e])
            idx = start + 1
        # XML may store & as &amp; in arch_db
        normalized = [p.replace("&amp;", "&") for p in pages]
        self.assertEqual(
            normalized[:5],
            [
                "Guardrails",
                "Repositories",
                "Environments",
                "Odoo Project & Tasks",
                "OpenProject Work Packages",
            ],
        )

    def test_token_not_on_dev_project_fields(self):
        fields = self.env["dev.project"].fields_get()
        self.assertNotIn("api_token", fields)
        # Form should not expose backend token via related field names
        for name in fields:
            self.assertNotIn("token", name.lower())
