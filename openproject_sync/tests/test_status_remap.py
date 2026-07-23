# -*- coding: utf-8 -*-
"""D2: Status Mapping rematch must update stage even when WP payload/hash unchanged."""
from __future__ import annotations

from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOpenprojectStatusRemap(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Backend = cls.env["openproject.backend"].sudo()
        cls.Map = cls.env["openproject.project.map"].sudo()
        cls.StatusMap = cls.env["openproject.status.map"].sudo()
        cls.Task = cls.env["project.task"].sudo()
        cls.Project = cls.env["project.project"].sudo()
        cls.Stage = cls.env["project.task.type"].sudo()

        cls.backend = cls.Backend.create(
            {
                "name": "Test OP Status Remap",
                "api_url": "http://127.0.0.1:8081",
                "api_token": "test-token",
                "enable_pull": True,
                "enable_push": True,  # intentional: upsert must still not outbound-patch
            }
        )
        cls.stage_inbox = cls.Stage.create({"name": "Inbox", "sequence": 1})
        cls.stage_new = cls.Stage.create({"name": "New", "sequence": 2})
        cls.stage_progress = cls.Stage.create({"name": "In Progress", "sequence": 10})
        cls.stage_done = cls.Stage.create({"name": "Done", "sequence": 20, "fold": True})

        cls.project = cls.Project.create({"name": "OP: Remap Project"})
        cls.project.write({"type_ids": [(6, 0, [
            cls.stage_inbox.id,
            cls.stage_new.id,
            cls.stage_progress.id,
            cls.stage_done.id,
        ])]})

        cls.pmap = cls.Map.create(
            {
                "backend_id": cls.backend.id,
                "op_project_id": 912,
                "op_project_name": "Remap Project",
                "odoo_project_id": cls.project.id,
                "active": True,
                "op_push_create": False,
            }
        )

        def mk_status(op_id, name, stage):
            return cls.StatusMap.create(
                {
                    "backend_id": cls.backend.id,
                    "op_status_id": op_id,
                    "op_status_name": name,
                    "op_status_href": f"/api/v3/statuses/{op_id}",
                    "odoo_stage_id": stage.id,
                    "active": True,
                }
            )

        cls.map_new = mk_status(1, "New", cls.stage_new)
        cls.map_progress = mk_status(7, "In progress", cls.stage_progress)
        cls.map_closed = mk_status(12, "Closed", cls.stage_inbox)

    def _wp(self, wp_id, subject, status_id, raw_desc="hello world"):
        return {
            "id": wp_id,
            "subject": subject,
            "lockVersion": 3,
            "description": {"raw": raw_desc, "format": "markdown"},
            "_links": {
                "project": {"href": "/api/v3/projects/912"},
                "status": {
                    "href": f"/api/v3/statuses/{status_id}",
                    "title": {1: "New", 7: "In progress", 12: "Closed"}.get(
                        status_id, "Status"
                    ),
                },
                "priority": {"href": "/api/v3/priorities/8"},
            },
        }

    def test_hash_unchanged_payload_stage_remaps_when_status_map_changes(self):
        wp = self._wp(91001, "Closed task", 12, raw_desc="stable desc")
        task, created, _, _ = self.Task._op_upsert_from_wp(
            self.pmap, wp, resolve_parent=False
        )
        self.assertTrue(created)
        self.assertEqual(task.stage_id, self.stage_inbox)
        old_hash = task.op_sync_hash
        old_desc = task.description
        old_raw = task.op_description_raw

        # Change mapping Closed → Done without WP payload change
        self.map_closed.write({"odoo_stage_id": self.stage_done.id})

        with patch.object(type(task), "_op_push_update") as push_mock:
            task2, created2, _, _ = self.Task._op_upsert_from_wp(
                self.pmap, wp, resolve_parent=False
            )
            push_mock.assert_not_called()

        self.assertFalse(created2)
        self.assertEqual(task2.id, task.id)
        self.assertEqual(task2.stage_id, self.stage_done)
        self.assertEqual(task2.op_description_raw, old_raw)
        self.assertEqual(task2.description, old_desc)
        self.assertNotEqual(task2.op_sync_hash, old_hash)

    def test_new_status_stays_new(self):
        wp = self._wp(91002, "New task", 1)
        task, created, _, _ = self.Task._op_upsert_from_wp(
            self.pmap, wp, resolve_parent=False
        )
        self.assertTrue(created)
        self.assertEqual(task.stage_id, self.stage_new)
        task2, created2, _, _ = self.Task._op_upsert_from_wp(
            self.pmap, wp, resolve_parent=False
        )
        self.assertFalse(created2)
        self.assertEqual(task2.id, task.id)
        self.assertEqual(task2.stage_id, self.stage_new)

    def test_in_progress_stays_in_progress(self):
        wp = self._wp(91003, "Progress task", 7)
        task, _, _, _ = self.Task._op_upsert_from_wp(
            self.pmap, wp, resolve_parent=False
        )
        self.assertEqual(task.stage_id, self.stage_progress)
        task2, created2, _, _ = self.Task._op_upsert_from_wp(
            self.pmap, wp, resolve_parent=False
        )
        self.assertFalse(created2)
        self.assertEqual(task2.stage_id, self.stage_progress)

    def test_no_duplicate_on_repeated_upsert(self):
        wp = self._wp(91004, "Dup check", 12)
        t1, c1, _, _ = self.Task._op_upsert_from_wp(self.pmap, wp, resolve_parent=False)
        t2, c2, _, _ = self.Task._op_upsert_from_wp(self.pmap, wp, resolve_parent=False)
        self.assertTrue(c1)
        self.assertFalse(c2)
        self.assertEqual(t1.id, t2.id)
        twins = self.Task.search(
            [
                ("op_backend_id", "=", self.backend.id),
                ("op_work_package_id", "=", 91004),
            ]
        )
        self.assertEqual(len(twins), 1)

    def test_inbound_upsert_does_not_call_outbound_patch(self):
        self.backend.write({"enable_push": True})
        wp = self._wp(91005, "No push", 12)
        task, _, _, _ = self.Task._op_upsert_from_wp(self.pmap, wp, resolve_parent=False)
        self.map_closed.write({"odoo_stage_id": self.stage_done.id})
        with patch.object(type(task), "_op_push_update") as push_upd, patch.object(
            type(task), "_op_push_create"
        ) as push_crt:
            self.Task._op_upsert_from_wp(self.pmap, wp, resolve_parent=False)
            push_upd.assert_not_called()
            push_crt.assert_not_called()
        self.assertEqual(task.stage_id, self.stage_done)
