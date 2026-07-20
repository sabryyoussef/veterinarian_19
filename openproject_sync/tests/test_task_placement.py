# -*- coding: utf-8 -*-
"""Tests for OpenProject task placement / project ownership sync."""
from __future__ import annotations

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOpenprojectTaskPlacement(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Backend = cls.env["openproject.backend"].sudo()
        cls.Map = cls.env["openproject.project.map"].sudo()
        cls.Task = cls.env["project.task"].sudo()
        cls.Project = cls.env["project.project"].sudo()

        cls.backend = cls.Backend.create(
            {
                "name": "Test OP",
                "api_url": "http://127.0.0.1:8081",
                "api_token": "test-token",
                "enable_pull": True,
                "enable_push": False,
            }
        )

        def mk_project(name, op_id, folder=False):
            p = cls.Project.create({"name": name})
            p.write(
                {
                    "op_project_id": op_id,
                    "op_is_company_folder": folder,
                    "op_is_work_project": not folder,
                }
            )
            return p

        cls.odoo_edafa = mk_project("OP: Edafa", 20, folder=True)
        cls.odoo_dev = mk_project("OP: Dev Needed", 10)
        cls.odoo_kafaat = mk_project("OP: Kafaat", 16)
        cls.odoo_cyclex = mk_project("OP: Cycle X", 17)
        cls.odoo_external = mk_project("OP: External Dev Pool", 19)

        def mk_map(op_id, odoo_project, name):
            return cls.Map.create(
                {
                    "backend_id": cls.backend.id,
                    "op_project_id": op_id,
                    "op_project_name": name,
                    "odoo_project_id": odoo_project.id,
                    "active": True,
                    "op_push_create": False,
                }
            )

        cls.map_dev = mk_map(10, cls.odoo_dev, "Dev Needed (WhatsApp)")
        cls.map_kafaat = mk_map(16, cls.odoo_kafaat, "Kafaat")
        cls.map_cyclex = mk_map(17, cls.odoo_cyclex, "Cycle X")
        cls.map_external = mk_map(19, cls.odoo_external, "External Dev Pool")
        cls.map_edafa = mk_map(20, cls.odoo_edafa, "Edafa")
        cls.map_edafa.write({"op_is_company_folder": True})

    def _wp(self, wp_id, subject, project_id, parent_id=None):
        body = {
            "id": wp_id,
            "subject": subject,
            "lockVersion": 1,
            "description": {"raw": "", "format": "markdown"},
            "_links": {
                "project": {"href": f"/api/v3/projects/{project_id}"},
                "priority": {"href": "/api/v3/priorities/8"},
            },
        }
        if parent_id:
            body["_links"]["parent"] = {
                "href": f"/api/v3/work_packages/{parent_id}",
                "title": f"Parent {parent_id}",
            }
        return body

    def test_wp_op16_created_in_odoo_kafaat(self):
        task, created, _, _ = self.Task._op_upsert_from_wp(
            self.map_kafaat, self._wp(9001, "Kafaat delivery", 16), resolve_parent=False
        )
        self.assertTrue(created)
        self.assertEqual(task.project_id, self.odoo_kafaat)
        self.assertEqual(task.op_project_id, 16)

    def test_wp_op17_created_in_odoo_cyclex(self):
        task, created, _, _ = self.Task._op_upsert_from_wp(
            self.map_cyclex, self._wp(9002, "Cycle X task", 17), resolve_parent=False
        )
        self.assertTrue(created)
        self.assertEqual(task.project_id, self.odoo_cyclex)

    def test_wp_op10_stays_in_dev_needed(self):
        task, created, _, _ = self.Task._op_upsert_from_wp(
            self.map_dev, self._wp(9003, "Dev Needed task", 10), resolve_parent=False
        )
        self.assertTrue(created)
        self.assertEqual(task.project_id, self.odoo_dev)

    def test_wp_project_change_moves_task(self):
        task, _, _, _ = self.Task._op_upsert_from_wp(
            self.map_dev, self._wp(9004, "Move me", 10), resolve_parent=False
        )
        self.assertEqual(task.project_id, self.odoo_dev)
        self.Task._op_upsert_from_wp(
            self.map_kafaat, self._wp(9004, "Move me", 16), resolve_parent=False
        )
        task.invalidate_recordset()
        self.assertEqual(task.project_id, self.odoo_kafaat)
        self.assertEqual(task.op_project_id, 16)

    def test_same_project_parent_kept(self):
        parent, _, _, _ = self.Task._op_upsert_from_wp(
            self.map_dev, self._wp(9010, "edafa_kafaat_parent", 10), resolve_parent=False
        )
        child, _, parent_wp, _ = self.Task._op_upsert_from_wp(
            self.map_dev,
            self._wp(9011, "Child in dev", 10, parent_id=9010),
            resolve_parent=True,
        )
        self.assertEqual(parent_wp, 9010)
        self.assertEqual(child.parent_id, parent)
        self.assertFalse(child.op_cross_project_parent)

    def test_cross_project_parent_metadata_only(self):
        parent, _, _, _ = self.Task._op_upsert_from_wp(
            self.map_dev, self._wp(9020, "edafa_kafaat_parent", 10), resolve_parent=False
        )
        child, _, _, _ = self.Task._op_upsert_from_wp(
            self.map_kafaat,
            self._wp(9021, "Kafaat child", 16, parent_id=9020),
            resolve_parent=True,
        )
        self.assertEqual(child.project_id, self.odoo_kafaat)
        self.assertFalse(child.parent_id)
        self.assertTrue(child.op_cross_project_parent)
        self.assertEqual(child.op_parent_work_package_id, 9020)
        self.assertEqual(child.op_parent_subject, "Parent 9020")

    def test_resync_no_duplicate(self):
        self.Task._op_upsert_from_wp(
            self.map_kafaat, self._wp(9030, "Once", 16), resolve_parent=False
        )
        count_before = self.Task.search_count(
            [("op_backend_id", "=", self.backend.id), ("op_work_package_id", "=", 9030)]
        )
        self.Task._op_upsert_from_wp(
            self.map_kafaat, self._wp(9030, "Once updated", 16), resolve_parent=False
        )
        count_after = self.Task.search_count(
            [("op_backend_id", "=", self.backend.id), ("op_work_package_id", "=", 9030)]
        )
        self.assertEqual(count_before, 1)
        self.assertEqual(count_after, 1)

    def test_manual_task_untouched_by_realign(self):
        manual = self.Task.create(
            {"name": "Manual only", "project_id": self.odoo_dev.id}
        )
        wizard = self.env["openproject.task.realign.wizard"].create(
            {"backend_id": self.backend.id, "dry_run": True}
        )
        wizard.action_build_audit()
        line = wizard.line_ids.filtered(lambda l: l.task_id == manual)
        self.assertFalse(line)

    def test_folder_project_skipped(self):
        task, _, _, warnings = self.Task._op_upsert_from_wp(
            self.map_edafa, self._wp(9040, "Should skip", 20), resolve_parent=False
        )
        self.assertFalse(task)
        self.assertEqual(warnings, 1)

    def test_realign_dry_run_no_write(self):
        misplaced, _, _, _ = self.Task._op_upsert_from_wp(
            self.map_external,
            self._wp(9050, "External", 19),
            resolve_parent=False,
        )
        misplaced.write({"project_id": self.odoo_dev.id})
        wizard = self.env["openproject.task.realign.wizard"].create(
            {"backend_id": self.backend.id, "dry_run": True}
        )
        wizard.action_build_audit()
        line = wizard.line_ids.filtered(lambda l: l.task_id == misplaced)
        self.assertTrue(line)
        self.assertEqual(line.action, "move")
        self.assertEqual(misplaced.project_id, self.odoo_dev)

    def test_realign_apply_moves_project(self):
        task, _, _, _ = self.Task._op_upsert_from_wp(
            self.map_external,
            self._wp(9060, "Move on apply", 19),
            resolve_parent=False,
        )
        task.write({"project_id": self.odoo_dev.id})
        wizard = self.env["openproject.task.realign.wizard"].create(
            {"backend_id": self.backend.id, "dry_run": False}
        )
        wizard.action_build_audit()
        wizard.action_apply()
        task.invalidate_recordset()
        self.assertEqual(task.project_id, self.odoo_external)

    def test_stage_mapping_on_move(self):
        stage_a = self.env["project.task.type"].create(
            {"name": "In Progress", "project_ids": [(6, 0, [self.odoo_dev.id])]}
        )
        stage_b = self.env["project.task.type"].create(
            {"name": "In Progress", "project_ids": [(6, 0, [self.odoo_external.id])]}
        )
        task, _, _, _ = self.Task._op_upsert_from_wp(
            self.map_external,
            self._wp(9070, "Stage move", 19),
            resolve_parent=False,
        )
        task.write({"project_id": self.odoo_dev.id, "stage_id": stage_a.id})
        vals = task._op_stage_vals_for_project_move(self.odoo_external)
        self.assertEqual(vals.get("stage_id"), stage_b.id)
