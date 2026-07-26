# -*- coding: utf-8 -*-
"""Isolated tests for project_public_task_update — disposable DBs only."""
from __future__ import annotations

import re
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import HttpCase, tagged, TransactionCase

from odoo.addons.project_public_task_update.models.project_task import (
    MAX_CLARIFICATION,
    MAX_SUBMITTER_NAME,
    MAX_SUGGESTED_SUBTASK_LINES,
)


CSRF_RE = re.compile(
    r'<input[^>]+name=["\']csrf_token["\'][^>]+value=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)


def _extract_csrf(html: str) -> str:
    match = CSRF_RE.search(html or "")
    if not match:
        raise AssertionError("CSRF token input not found in HTML")
    return match.group(1)


def _html_without_styles(html: str) -> str:
    """Remove stylesheet blocks before scanning visible markup for #task_id refs."""
    return _STYLE_BLOCK_RE.sub("", html or "")


def task_id_exposure_findings(html: str, tid: int) -> list[str]:
    """Return findings if a database task id is exposed in structured HTML ways.

    Intentionally does **not** treat CSS hex colors such as ``#111827`` as
    exposure when ``tid == 111``. Style blocks are stripped before visible
    ``#<id>`` / label checks; attribute and ``/task/<id>`` checks use the
    full document.
    """
    html = html or ""
    tid_s = str(int(tid))
    findings: list[str] = []

    attr_re = re.compile(
        rf"""(?ix)
        (?:\bid|value|data-id|name)\s*=\s*
        (["']?){re.escape(tid_s)}(?!\d)\1
        """
    )
    if attr_re.search(html):
        findings.append(f"attribute equals task id {tid_s}")

    if re.search(rf"/task/{re.escape(tid_s)}\b", html):
        findings.append(f"URL path /task/{tid_s}")

    visible = _html_without_styles(html)
    if re.search(
        rf"""(?ix)href\s*=\s*["'][^"']*#{re.escape(tid_s)}(?![0-9A-Fa-f])""",
        visible,
    ):
        findings.append(f"href fragment #{tid_s}")
    if re.search(rf"(?i)\bTask\s*#{re.escape(tid_s)}\b", visible):
        findings.append(f"visible Task #{tid_s} label")
    # Standalone fragment/label #tid that is not a longer hex color token.
    if re.search(rf"#{re.escape(tid_s)}(?![0-9A-Fa-f])", visible):
        findings.append(f"standalone fragment #{tid_s}")

    return findings


def assert_no_task_id_exposure(html: str, tids) -> None:
    """Fail if any tid is exposed via attributes, URLs, fragments, or labels."""
    for tid in tids:
        findings = task_id_exposure_findings(html, tid)
        if findings:
            raise AssertionError(
                f"task id {tid} exposed in public HTML: {', '.join(findings)}"
            )


@tagged("post_install", "-at_install")
class TestTaskIdExposureHelpers(TransactionCase):
    """Regression for ID-leak helpers — synthetic HTML, no product changes."""

    def test_css_hex_color_not_false_positive_for_task_id(self):
        html = """
        <html><head><style>:root { --text: #111827; } textarea { min-height: 110px; }</style></head>
        <body><span class="subtask-name">HTTP Child Early</span></body></html>
        """
        self.assertEqual(task_id_exposure_findings(html, 111), [])
        assert_no_task_id_exposure(html, [111])

    def test_detects_attribute_url_fragment_and_label_exposure(self):
        cases = [
            ('<div data-id="111"></div>', "attribute"),
            ('<input value="111"/>', "attribute"),
            ('<a href="/task/111">x</a>', "URL path"),
            ('<a href="#111">jump</a>', "href fragment"),
            ("<p>Please review Task #111 tomorrow</p>", "visible Task #"),
        ]
        for html, kind in cases:
            with self.subTest(kind=kind, html=html):
                findings = task_id_exposure_findings(html, 111)
                self.assertTrue(findings, f"expected detection for {kind}: {html!r}")
                with self.assertRaises(AssertionError):
                    assert_no_task_id_exposure(html, [111])

    def test_style_stripped_before_visible_hash_checks(self):
        # #111 only inside <style> must not count; same id in body label must.
        styled_only = "<style>.x { color: #111; }</style><p>ok</p>"
        # Note: #111 in CSS is a 3-digit hex color; after strip, no exposure.
        # Use a non-hex-terminator case inside style that would otherwise match.
        styled_fragment = "<style>/* #111 */</style><div>safe</div>"
        self.assertEqual(task_id_exposure_findings(styled_fragment, 111), [])
        mixed = styled_fragment + "<p>Task #111</p>"
        self.assertTrue(any("Task #" in f for f in task_id_exposure_findings(mixed, 111)))


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

    def test_unique_token_constraint_and_empty_string(self):
        t1 = self.Task.create({"name": "Tok1", "project_id": self.project.id})
        t2 = self.Task.create({"name": "Tok2", "project_id": self.project.id})
        t1.action_generate_public_update_token()
        token = t1.public_update_token
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                t2.write({"public_update_token": token})
                self.env.flush_all()
        with self.assertRaises(ValidationError):
            t2.write({"public_update_token": ""})
        # Multiple NULL tokens remain allowed.
        t3 = self.Task.create({"name": "Tok3", "project_id": self.project.id})
        t4 = self.Task.create({"name": "Tok4", "project_id": self.project.id})
        self.assertFalse(t3.public_update_token)
        self.assertFalse(t4.public_update_token)

    def test_empty_token_does_not_resolve(self):
        Task = self.env["project.task"]
        self.assertFalse(Task._get_task_by_public_update_token(""))
        self.assertFalse(Task._get_task_by_public_update_token("   "))
        self.assertFalse(Task._get_task_by_public_update_token("short"))

    def test_collision_retry_bounded(self):
        task = self.Task.create({"name": "Collision", "project_id": self.project.id})
        with patch(
            "odoo.addons.project_public_task_update.models.project_task.secrets.token_urlsafe",
            return_value="collision-token-value-aaaa",
        ), patch.object(type(task), "search_count", return_value=1):
            with self.assertRaises(UserError):
                task._generate_unique_public_update_token()

    def test_submission_locks_before_rate_limit_check(self):
        """Throttle decision must run after FOR UPDATE row lock (concurrency gate)."""
        order = []
        task = self.Task.create({"name": "LockOrder", "project_id": self.project.id})
        task.action_generate_public_update_token()
        TaskModel = type(task)
        orig_lock = TaskModel._lock_for_public_submission
        orig_rate = TaskModel._public_update_rate_limited

        def lock(self):
            order.append("lock")
            return orig_lock(self)

        def rate(self):
            order.append("rate")
            return False

        with patch.object(TaskModel, "_lock_for_public_submission", lock), patch.object(
            TaskModel, "_public_update_rate_limited", rate
        ):
            task._record_public_update_submission(
                submitter_name="Lock Tester",
                submitter_contact="",
                clarification="First submit under lock",
            )
        self.assertEqual(order[:2], ["lock", "rate"])
        self.assertEqual(task.public_update_submission_count, 1)

    def test_server_side_length_limits(self):
        Task = self.env["project.task"]
        with self.assertRaises(UserError):
            Task._validate_public_submission_fields(
                submitter_name="x" * (MAX_SUBMITTER_NAME + 1),
                submitter_contact="",
                clarification="ok",
                priority_suggestion="",
                due_date_suggestion="",
                notes="",
                suggested_subtasks="",
                team_planning=False,
            )
        ok = Task._validate_public_submission_fields(
            submitter_name="x" * MAX_SUBMITTER_NAME,
            submitter_contact="",
            clarification="y" * MAX_CLARIFICATION,
            priority_suggestion="high",
            due_date_suggestion="",
            notes="",
            suggested_subtasks="",
            team_planning=False,
        )
        self.assertEqual(len(ok["submitter_name"]), MAX_SUBMITTER_NAME)
        with self.assertRaises(UserError):
            Task._validate_public_submission_fields(
                submitter_name="n",
                submitter_contact="",
                clarification="c",
                priority_suggestion="",
                due_date_suggestion="",
                notes="",
                suggested_subtasks="\n".join([f"line{i}" for i in range(MAX_SUGGESTED_SUBTASK_LINES + 1)]),
                team_planning=True,
            )
        # Excess total text (many medium fields summing over the bound)
        big_subtasks = "\n".join(["x" * 200 for _ in range(MAX_SUGGESTED_SUBTASK_LINES)])
        with self.assertRaises(UserError):
            Task._validate_public_submission_fields(
                submitter_name="n" * MAX_SUBMITTER_NAME,
                submitter_contact="c" * 200,
                clarification="c" * MAX_CLARIFICATION,
                priority_suggestion="",
                due_date_suggestion="",
                notes="n" * 3000,
                suggested_subtasks=big_subtasks,
                team_planning=True,
            )

    def test_archived_task_does_not_resolve(self):
        task = self.Task.create({"name": "Archived", "project_id": self.project.id})
        task.action_generate_public_update_token()
        token = task.public_update_token
        task.write({"active": False})
        self.assertFalse(self.Task._get_task_by_public_update_token(token))


@tagged("post_install", "-at_install")
class TestPublicTaskUpdateHttp(HttpCase):
    """HTTP tests for CSRF/session, tokens, headers, and mutations."""

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
        self.assertEqual(response.headers.get("Referrer-Policy"), "no-referrer")
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        csp = response.headers.get("Content-Security-Policy", "")
        self.assertIn("frame-ancestors", csp)
        self.assertIn("'none'", csp)
        robots = response.headers.get("X-Robots-Tag", "")
        self.assertIn("noindex", robots)
        self.assertIn("noindex", response.text.lower())

    def _get_form(self, url=None):
        response = self.url_open(url or self.url)
        self.assertEqual(response.status_code, 200)
        csrf = _extract_csrf(response.text)
        return response, csrf

    def _post(self, csrf, payload, url=None, allow_redirects=True):
        data = dict(payload)
        if csrf is not None:
            data["csrf_token"] = csrf
        return self.url_open(url or self.url, data=data, allow_redirects=allow_redirects)

    def _mutation_snapshot(self, task):
        task.invalidate_recordset()
        note_subtype = self.env.ref("mail.mt_note")
        notes = self.env["mail.message"].search_count([
            ("model", "=", "project.task"),
            ("res_id", "=", task.id),
            ("subtype_id", "=", note_subtype.id),
        ])
        return {
            "count": task.public_update_submission_count,
            "last": task.public_update_last_submission_at,
            "notes": notes,
            "name": task.name,
            "token": task.public_update_token,
            "active_flag": task.public_update_token_active,
        }

    def test_get_returns_csrf_and_zero_mutations(self):
        before = self._mutation_snapshot(self.parent)
        response, csrf = self._get_form()
        self.assertTrue(csrf)
        self.assertIn('name="csrf_token"', response.text)
        after = self._mutation_snapshot(self.parent)
        self.assertEqual(before, after)
        self._assert_safe_headers(response)

    def test_valid_same_session_get_post_succeeds(self):
        _resp, csrf = self._get_form()
        before = self._mutation_snapshot(self.parent)
        response = self._post(csrf, {
            "submitter_name": "Valid User",
            "clarification": "Details here",
            "notes": "Optional",
            "suggested_subtasks": "One\nTwo",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("submitted", response.text.lower())
        after = self._mutation_snapshot(self.parent)
        self.assertEqual(after["count"], before["count"] + 1)
        self.assertEqual(after["notes"], before["notes"] + 1)
        self.assertEqual(after["name"], before["name"])
        self._assert_safe_headers(response)

    def test_missing_csrf_fails_zero_mutation(self):
        before = self._mutation_snapshot(self.parent)
        # Establish session via GET first
        self._get_form()
        response = self.url_open(self.url, data={
            "submitter_name": "No CSRF",
            "clarification": "Should fail",
        }, allow_redirects=False)
        # Odoo rejects CSRF with 400 Bad Request
        self.assertIn(response.status_code, (400, 403))
        after = self._mutation_snapshot(self.parent)
        self.assertEqual(before, after)

    def test_invalid_csrf_fails_zero_mutation(self):
        before = self._mutation_snapshot(self.parent)
        self._get_form()
        response = self._post("not-a-valid-csrf-token", {
            "submitter_name": "Bad CSRF",
            "clarification": "Should fail",
        }, allow_redirects=False)
        self.assertIn(response.status_code, (400, 403))
        after = self._mutation_snapshot(self.parent)
        self.assertEqual(before, after)

    def test_different_session_csrf_fails(self):
        _resp, csrf_a = self._get_form()
        before = self._mutation_snapshot(self.parent)
        # Drop the browser session that owns csrf_a, then POST with the stale token.
        self.opener = __import__("requests").Session()
        self.opener.cookies.clear()
        response = self.url_open(self.url, data={
            "csrf_token": csrf_a,
            "submitter_name": "Cross Session",
            "clarification": "Should fail",
        }, allow_redirects=False)
        self.assertIn(response.status_code, (400, 403))
        after = self._mutation_snapshot(self.parent)
        self.assertEqual(before, after)

    def test_valid_token_shows_direct_children_no_login(self):
        response = self.url_open(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("/web/login", response.url)
        html = response.text
        self.assertIn("HTTP Parent Task", html)
        self.assertIn("HTTP Child Early", html)
        self.assertIn("HTTP Child Late", html)
        self.assertLess(html.index("HTTP Child Early"), html.index("HTTP Child Late"))
        self.assertNotIn("HTTP Grandchild Hidden", html)
        self.assertNotIn("HTTP Foreign Task", html)
        self.assertNotIn("SECRET_PARENT_DESCRIPTION", html)
        self.assertNotIn("SECRET_CHILD_DESCRIPTION", html)
        # Structured ID-leak checks only (CSS hex like #111827 must not false-fail).
        assert_no_task_id_exposure(
            html,
            (self.child_early.id, self.child_late.id, self.parent.id),
        )
        self.assertNotIn("/odoo/project/", html)
        self.assertNotIn("openproject.example", html)
        self.assertNotIn("999001", html)
        self.assertNotIn("op_work_package", html)
        self.assertNotIn("o_mail_thread", html)
        self.assertNotIn("js_attachment", html)
        self._assert_safe_headers(response)

    def test_empty_parent_empty_state(self):
        response = self.url_open(self.empty_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("No sub-tasks yet", response.text)
        self.assertNotIn("HTTP Child Early", response.text)
        self._assert_safe_headers(response)

    def test_invalid_and_short_token_404_headers(self):
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
        _resp, csrf = self._get_form()
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
        response = self._post(csrf, payload)
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

    def test_oversized_field_rejected_zero_mutation(self):
        _resp, csrf = self._get_form()
        before = self._mutation_snapshot(self.parent)
        response = self._post(csrf, {
            "submitter_name": "x" * (MAX_SUBMITTER_NAME + 1),
            "clarification": "ok",
        })
        self.assertEqual(response.status_code, 400)
        after = self._mutation_snapshot(self.parent)
        self.assertEqual(before["count"], after["count"])
        self.assertEqual(before["notes"], after["notes"])
        self._assert_safe_headers(response)

    def test_post_rate_limit(self):
        _resp, csrf = self._get_form()
        payload = {
            "submitter_name": "Rate Limit User",
            "clarification": "First submit",
        }
        first = self._post(csrf, payload)
        self.assertEqual(first.status_code, 200)
        self.assertIn("submitted", first.text.lower())
        # Re-GET for fresh CSRF after success page
        _resp2, csrf2 = self._get_form()
        second = self._post(csrf2, {
            "submitter_name": "Rate Limit User",
            "clarification": "Second submit too soon",
        })
        self.assertEqual(second.status_code, 400)
        self.assertIn("wait", second.text.lower())
        self.parent.invalidate_recordset()
        self.assertEqual(self.parent.public_update_submission_count, 1)

    def test_closed_task_denied(self):
        # Force closed state if CLOSED_STATES / state field available
        if "state" not in self.Task._fields:
            self.skipTest("task.state not available")
        closed_state = None
        for candidate in ("1_done", "1_canceled", "done", "cancel"):
            # pick a value that makes is_closed True
            self.parent.state = candidate
            self.parent.invalidate_recordset(["is_closed", "state"])
            if self.parent.is_closed:
                closed_state = candidate
                break
        if not closed_state:
            self.skipTest("could not set authoritative closed state")
        response = self.url_open(self.url)
        self.assertEqual(response.status_code, 404)
        self._assert_safe_headers(response)

    def test_token_not_in_error_logs_prefix(self):
        # Ensure controller exception path does not include capability token text.
        # We assert log formatting constants by inspecting source contract via behavior:
        # invalid token 404 page must not echo the token string.
        bogus = "BOGUS_TOKEN_VALUE_SHOULD_NOT_ECHO_XXXX"
        response = self.url_open(f"/task/update/{bogus}")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(bogus, response.text)
