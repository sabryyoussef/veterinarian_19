# -*- coding: utf-8 -*-
"""Isolated tests for project_public_task_update — do not use production task 213."""
from __future__ import annotations

from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestPublicChildTasksPayload(TransactionCase):
    """Unit tests for the allowlisted child payload helper."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Project = cls.env["project.project"]
        cls.Task = cls.env["project.task"]
        cls.project = cls.Project.create({"name": "PPTU Payload Project"})
        cls.other_project = cls.Project.create({"name": "PPTU Other Project"})
        cls.parent = cls.Task.create({
            "name": "PPTU Parent",
            "project_id": cls.project.id,
            "public_update_purpose": "team_planning",
        })
        cls.child_b = cls.Task.create({
            "name": "Child B",
            "project_id": cls.project.id,
            "parent_id": cls.parent.id,
            "sequence": 20,
        })
        cls.child_a = cls.Task.create({
            "name": "Child A",
            "project_id": cls.project.id,
            "parent_id": cls.parent.id,
            "sequence": 10,
        })
        cls.grandchild = cls.Task.create({
            "name": "Grandchild Secret",
            "project_id": cls.project.id,
            "parent_id": cls.child_a.id,
            "sequence": 5,
        })
        cls.foreign = cls.Task.create({
            "name": "Foreign Child",
            "project_id": cls.other_project.id,
        })
        cls.lonely = cls.Task.create({
            "name": "Lonely Parent",
            "project_id": cls.project.id,
        })

    def test_payload_direct_children_only_ordered(self):
        payload = self.parent._public_child_tasks_payload()
        self.assertEqual([row["name"] for row in payload], ["Child A", "Child B"])
        self.assertTrue(all(set(row) == {"name", "stage_name", "is_closed"} for row in payload))
        names = " ".join(row["name"] for row in payload)
        self.assertNotIn("Grandchild", names)
        self.assertNotIn("Foreign", names)

    def test_payload_empty_parent(self):
        self.assertEqual(self.lonely._public_child_tasks_payload(), [])

    def test_payload_no_ids_or_op_keys(self):
        payload = self.parent._public_child_tasks_payload()
        blob = repr(payload)
        self.assertNotIn(str(self.child_a.id), blob)
        self.assertNotIn(str(self.child_b.id), blob)
        self.assertNotIn("op_work_package", blob)
        self.assertNotIn("op_url", blob)


@tagged("post_install", "-at_install")
class TestPublicTaskUpdateHttp(HttpCase):
    """HTTP tests for the tokenized public form."""

    def setUp(self):
        super().setUp()
        self.Project = self.env["project.project"]
        self.Task = self.env["project.task"]
        self.project = self.Project.create({"name": "PPTU HTTP Project"})
        self.other_project = self.Project.create({"name": "PPTU HTTP Other"})
        self.parent = self.Task.create({
            "name": "HTTP Parent Task",
            "project_id": self.project.id,
            "public_update_purpose": "team_planning",
            "implementation_plan": "Plan text for colleagues only.",
            "description": "<p>SECRET_PARENT_DESCRIPTION_SHOULD_NOT_APPEAR</p>",
        })
        self.child_late = self.Task.create({
            "name": "HTTP Child Late",
            "project_id": self.project.id,
            "parent_id": self.parent.id,
            "sequence": 30,
            "description": "<p>SECRET_CHILD_DESCRIPTION</p>",
        })
        self.child_early = self.Task.create({
            "name": "HTTP Child Early",
            "project_id": self.project.id,
            "parent_id": self.parent.id,
            "sequence": 5,
        })
        self.grandchild = self.Task.create({
            "name": "HTTP Grandchild Hidden",
            "project_id": self.project.id,
            "parent_id": self.child_early.id,
        })
        self.foreign = self.Task.create({
            "name": "HTTP Foreign Task",
            "project_id": self.other_project.id,
        })
        self.empty_parent = self.Task.create({
            "name": "HTTP Empty Parent",
            "project_id": self.project.id,
            "public_update_purpose": "team_planning",
        })
        # Attach OP-like values if fields exist (openproject_sync may be present).
        op_vals = {}
        if "op_work_package_id" in self.Task._fields:
            op_vals["op_work_package_id"] = 999001
        if "op_url" in self.Task._fields:
            op_vals["op_url"] = "https://openproject.example/work_packages/999001"
        if op_vals:
            self.parent.write(op_vals)
            self.child_early.write(op_vals)

        self.parent.action_generate_public_update_token()
        self.token = self.parent.public_update_token
        self.url = f"/task/update/{self.token}"

        self.empty_parent.action_generate_public_update_token()
        self.empty_token = self.empty_parent.public_update_token
        self.empty_url = f"/task/update/{self.empty_token}"

    def _assert_safe_headers(self, response):
        cache = response.headers.get("Cache-Control", "")
        self.assertIn("no-store", cache)
        self.assertIn("private", cache)
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        robots = response.headers.get("X-Robots-Tag", "")
        self.assertIn("noindex", robots)
        # HTML meta robots as defense in depth
        self.assertIn("noindex", response.text.lower())

    def test_valid_token_shows_direct_children_no_login(self):
        response = self.url_open(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("/web/login", response.url)
        html = response.text
        self.assertIn("HTTP Parent Task", html)
        self.assertIn("HTTP Child Early", html)
        self.assertIn("HTTP Child Late", html)
        # Ordering: Early (seq 5) before Late (seq 30)
        self.assertLess(html.index("HTTP Child Early"), html.index("HTTP Child Late"))
        self.assertNotIn("HTTP Grandchild Hidden", html)
        self.assertNotIn("HTTP Foreign Task", html)
        self.assertNotIn("SECRET_PARENT_DESCRIPTION", html)
        self.assertNotIn("SECRET_CHILD_DESCRIPTION", html)
        self.assertNotIn(str(self.child_early.id), html)
        self.assertNotIn(str(self.child_late.id), html)
        self.assertNotIn("/odoo/project/", html)
        self.assertNotIn("openproject.example", html)
        self.assertNotIn("999001", html)
        self.assertNotIn("op_work_package", html)
        self.assertNotIn("o_mail_thread", html)
        self.assertNotIn("o-mail-Thread", html)
        self.assertNotIn("js_attachment", html)
        self._assert_safe_headers(response)

    def test_empty_parent_empty_state(self):
        response = self.url_open(self.empty_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("No sub-tasks yet", response.text)
        self.assertNotIn("HTTP Child Early", response.text)
        self._assert_safe_headers(response)

    def test_invalid_and_short_token_404(self):
        for path in (
            "/task/update/INVALID_TOKEN_DOES_NOT_EXIST_XXXX",
            "/task/update/abc",
        ):
            response = self.url_open(path)
            self.assertEqual(response.status_code, 404, path)
            self.assertIn("unavailable", response.text.lower())
            self.assertNotIn("HTTP Parent Task", response.text)
            self._assert_safe_headers(response)

    def test_inactive_token_404(self):
        self.parent.action_disable_public_update_token()
        response = self.url_open(self.url)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("HTTP Parent Task", response.text)
        self._assert_safe_headers(response)

    def test_expired_token_404(self):
        self.parent.write({
            "public_update_token_active": True,
            "public_update_token_expiry": fields.Datetime.now() - timedelta(hours=1),
        })
        response = self.url_open(self.url)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("HTTP Parent Task", response.text)
        self._assert_safe_headers(response)

    def test_regenerate_invalidates_old_token(self):
        old = self.token
        self.parent.action_generate_public_update_token()
        new = self.parent.public_update_token
        self.assertNotEqual(old, new)
        old_resp = self.url_open(f"/task/update/{old}")
        self.assertEqual(old_resp.status_code, 404)
        new_resp = self.url_open(f"/task/update/{new}")
        self.assertEqual(new_resp.status_code, 200)
        self.assertIn("HTTP Parent Task", new_resp.text)

    def test_post_creates_note_only_and_escapes_html(self):
        before_count = self.parent.public_update_submission_count
        before_name = self.parent.name
        before_child_name = self.child_early.name
        messages_before = self.env["mail.message"].search_count([
            ("model", "=", "project.task"),
            ("res_id", "=", self.parent.id),
        ])
        payload = {
            "submitter_name": "Tester <script>alert(1)</script>",
            "submitter_contact": "tester@example.com",
            "clarification": "Need detail <b>bold</b> & more",
            "notes": "<img src=x onerror=alert(1)>",
            "suggested_subtasks": "Suggested one\nSuggested two",
        }
        response = self.url_open(self.url, data=payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("submitted", response.text.lower())
        self.parent.invalidate_recordset()
        self.assertEqual(self.parent.public_update_submission_count, before_count + 1)
        self.assertEqual(self.parent.name, before_name)
        self.child_early.invalidate_recordset()
        self.assertEqual(self.child_early.name, before_child_name)

        note_subtype = self.env.ref("mail.mt_note")
        notes = self.env["mail.message"].search([
            ("model", "=", "project.task"),
            ("res_id", "=", self.parent.id),
            ("subtype_id", "=", note_subtype.id),
        ], order="id desc", limit=1)
        self.assertTrue(notes)
        self.assertEqual(
            self.env["mail.message"].search_count([
                ("model", "=", "project.task"),
                ("res_id", "=", self.parent.id),
            ]),
            messages_before + 1,
        )
        body = notes.body or ""
        self.assertIn("Team planning update submitted", body)
        self.assertIn("&lt;script&gt;", body)
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn("&lt;b&gt;bold&lt;/b&gt;", body)
        self.assertIn("&lt;img", body)
        self._assert_safe_headers(response)

    def test_post_rate_limit(self):
        payload = {
            "submitter_name": "Rate Limit User",
            "clarification": "First submit",
        }
        first = self.url_open(self.url, data=payload)
        self.assertEqual(first.status_code, 200)
        self.assertIn("submitted", first.text.lower())
        second = self.url_open(self.url, data={
            "submitter_name": "Rate Limit User",
            "clarification": "Second submit too soon",
        })
        self.assertEqual(second.status_code, 200)
        self.assertIn("wait", second.text.lower())
        self.parent.invalidate_recordset()
        # Only one successful increment from this pair (plus any from earlier tests in setUp isolation)
        # Within this test method, count should be +1 from first only.
        # Re-read: setUp creates fresh parent each test method in HttpCase? setUp runs per test.
        self.assertEqual(self.parent.public_update_submission_count, 1)
