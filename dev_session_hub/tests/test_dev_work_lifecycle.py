# -*- coding: utf-8 -*-
import json
import socket
import uuid
from unittest.mock import patch

from psycopg2.errors import UniqueViolation

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestDevWorkLifecycle(TransactionCase):
    """Behavioral coverage for the Phase 1-4 development-work contract."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dev_project = cls.env.ref("dev_session_hub.dev_project_petspot")
        cls.repository = cls.env.ref("dev_session_hub.dev_repository_petspot")
        cls.environment = cls.env.ref("dev_session_hub.dev_environment_petspot_test")
        cls.windows = cls.env.ref("dev_session_hub.dev_client_windows_desktop")
        cls.ubuntu = cls.env.ref("dev_session_hub.dev_client_ubuntu_precision")
        cls.task_link = cls.env.ref("dev_session_hub.dev_task_petspot_wp337")

        cls.backend = cls.env["openproject.backend"].create(
            {
                "name": "Dev Hub lifecycle test backend",
                "api_url": "http://127.0.0.1:9",
                "public_url": "https://openproject.test.invalid",
                "verify_ssl": True,
                "enable_pull": False,
                "enable_push": False,
            }
        )
        cls.odoo_project = cls.env["project.project"].create(
            {"name": "Dev Hub lifecycle test project"}
        )
        cls.odoo_task = cls.env["project.task"].create(
            {
                "name": "Lifecycle work package 880001",
                "project_id": cls.odoo_project.id,
                "op_backend_id": cls.backend.id,
                "op_work_package_id": 880001,
                "op_url": "https://openproject.test.invalid/work_packages/880001",
            }
        )
        cls.machine = cls.env["dev.machine"].create(
            {
                "name": "Lifecycle non-production target",
                "hostname": socket.gethostname(),
                "tailscale_name": "lifecycle-test.tailcf9988.ts.net",
                "tailscale_ip_reference": "100.64.0.98",
                "tailscale_destination_verified": True,
                "tailscale_verified_at": "2026-07-18 16:20:00",
                "pinned_host_key_fingerprint": (
                    "SHA256:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
                ),
                "ssh_alias": "lifecycle-test-ts",
                "role": "TransactionCase target only",
                "trust_zone": "trusted_dev",
                "production": False,
                "allowed_path_prefixes": cls.repository.working_directory,
            }
        )
        cls.environment.machine_id = cls.machine
        cls.snapshot = {
            "branch": "feature/dev-work-lifecycle",
            "head": "a" * 40,
            "dirty": "staged=0; unstaged=2; untracked=1; conflicts=0; digest=abc123",
            "captured_at": "2026-07-18 16:20:00",
        }

        required_models = {
            "dev.work.item",
            "dev.work.lifecycle.event",
            "dev.work.source.message",
            "dev.work.analysis",
            "dev.work.plan",
            "dev.work.plan.step",
            "dev.work.approval",
            "dev.work.checkpoint",
            "dev.completion.report",
            "dev.work.communication",
            "dev.external.outbox",
            "dev.work.generation",
        }
        missing = sorted(name for name in required_models if name not in cls.env)
        if missing:
            raise AssertionError("Missing lifecycle models: %s" % ", ".join(missing))

    def setUp(self):
        super().setUp()
        launcher = patch.object(
            type(self.env["dev.session"]),
            "_pin_enforced_launcher_available",
            autospec=True,
            return_value=True,
        )
        launcher.start()
        self.addCleanup(launcher.stop)
        open_launcher = patch.object(
            type(self.env["dev.session"]),
            "_open_launcher",
            autospec=True,
            return_value={"type": "disabled-launcher-test-double"},
        )
        open_launcher.start()
        self.addCleanup(open_launcher.stop)

    def _model_vals(self, model_name, **values):
        """Keep fixtures compatible with optional presentation-only fields."""
        fields = self.env[model_name]._fields
        return {name: value for name, value in values.items() if name in fields}

    def _work(self, wp_id=880001, task=None, **extra):
        source_key = uuid.uuid4().hex
        source = self.env["dev.work.source.message"].create(
            {
                "provider": "manual",
                "provider_message_id": source_key,
                "chatwoot_account_id": 1,
                "chatwoot_inbox_id": 2,
                "chatwoot_conversation_id": 775,
                "chatwoot_message_id": 776,
                "group_jid": "120363000000000000@g.us",
                "message_timestamp": "2026-07-18 16:20:00",
                "text_snapshot": "Sanitized lifecycle test request %s" % source_key,
            }
        )
        values = {
            "name": "Lifecycle test work",
            "dev_project_id": self.dev_project.id,
            "odoo_project_id": self.odoo_project.id,
            "odoo_task_id": (task or self.odoo_task).id,
            "op_backend_id": self.backend.id if wp_id else False,
            "op_work_package_id": wp_id,
            "op_reference": "WP #%s" % wp_id,
            "op_url": "https://openproject.test.invalid/work_packages/%s" % wp_id,
            "responsible_user_id": self.env.user.id,
            "preferred_repository_id": self.repository.id,
            "preferred_environment_id": self.environment.id,
            "source_message_ids": [(4, source.id)],
        }
        values.update(extra)
        return self.env["dev.work.item"].create(
            self._model_vals("dev.work.item", **values)
        )

    def _call(self, record, names, *args):
        for name in names:
            method = getattr(record, name, None)
            if method:
                return method(*args)
        self.fail("%s implements none of %s" % (record._name, ", ".join(names)))

    def _transition(self, work, phase):
        method = getattr(work, "transition_lifecycle", None)
        if method:
            return method(phase, "TransactionCase transition to %s" % phase)
        method = getattr(work, "action_transition", None)
        if method:
            return method(phase)
        method = getattr(work, "_transition", None)
        if method:
            return method(phase)
        method = getattr(work, "_transition_phase", None)
        if method:
            return method(phase)
        return self._call(
            work,
            (
                "action_%s" % phase,
                "action_mark_%s" % phase,
                "action_set_%s" % phase,
            ),
        )

    def _snapshot_patch(self, snapshot=None):
        return patch.object(
            type(self.env["dev.session"]),
            "_capture_git_snapshot",
            autospec=True,
            return_value=snapshot or self.snapshot,
        )

    def _session(self, work, client=None, environment=None, machine=None):
        environment = environment or self.environment
        machine = machine or self.machine
        return self.env["dev.session"].create(
            {
                "client_id": (client or self.windows).id,
                "project_id": self.dev_project.id,
                "environment_id": environment.id,
                "machine_id": machine.id,
                "repository_id": self.repository.id,
                "working_directory": self.repository.working_directory,
                "task_link_id": self.task_link.id,
                "work_item_id": work.id,
            }
        )

    def _analysis(self, work):
        return self.env["dev.work.analysis"].create(
            self._model_vals(
                "dev.work.analysis",
                work_item_id=work.id,
                revision=1,
                status="draft",
                problem_summary="A bounded lifecycle test problem",
                original_request_snapshot="Please fix the test-only behavior.",
                reproduction_context="Reproduce in the isolated test database.",
                current_behavior="The workflow is incomplete.",
                expected_behavior="The workflow is controlled and auditable.",
                technical_findings="No external service is required.",
                affected_modules_files="dev_session_hub",
                risks="No production access.",
                dependencies="project, openproject_sync",
                open_questions="None",
                evidence_references="test://analysis/1",
                origin="manual",
                repository_observed=self.repository.working_directory,
                head_observed="a" * 40,
            )
        )

    def _plan(self, work, with_step=False):
        plan = self.env["dev.work.plan"].create(
            self._model_vals(
                "dev.work.plan",
                work_item_id=work.id,
                revision=1,
                status="draft",
                goal="Implement the bounded lifecycle.",
                scope="Odoo models and tests.",
                out_of_scope="Production and autonomous workers.",
                proposed_changes="Add lifecycle records.",
                affected_modules_files="dev_session_hub",
                migration_impact="None in TransactionCase.",
                security_impact="No direct external transport.",
                test_plan="Run post-install TransactionCase tests.",
                rollback_plan="Uninstall the test-only module.",
                dependencies="project, openproject_sync",
                risks="Incorrect lifecycle transition.",
                acceptance_criteria="All requested lifecycle tests pass.",
                origin="manual",
            )
        )
        if with_step:
            self.env["dev.work.plan.step"].create(
                {
                    "plan_id": plan.id,
                    "step_key": "S1",
                    "sequence": 1,
                    "title": "Implement the bounded lifecycle",
                    "description": "No external calls.",
                }
            )
        return plan

    def _accept_analysis(self, analysis):
        return self._call(
            analysis,
            ("action_accept", "action_mark_accepted", "action_set_accepted"),
        )

    def _submit_plan(self, plan):
        return self._call(
            plan,
            (
                "action_request_approval",
                "action_submit_for_approval",
                "action_await_approval",
            ),
        )

    def _approve_plan(self, plan):
        return self._call(
            plan,
            ("action_approve_exact", "action_approve", "action_approve_exact_hash"),
        )

    def _approved_plan(self, work):
        if work.lifecycle_phase == "received":
            self._transition(work, "triage")
            self._transition(work, "registered")
            self._transition(work, "analyzing")
            analysis = self._analysis(work)
            self._accept_analysis(analysis)
            self._transition(work, "planning")
        plan = self._plan(work, with_step=True)
        self._submit_plan(plan)
        self._approve_plan(plan)
        return plan

    def _approved_report(self, work):
        plan = self._approved_plan(work)
        step = plan.step_ids[:1]
        step.write({"status": "in_progress"})
        step.write({"status": "done"})
        self._transition(work, "implementing")
        self._transition(work, "testing")
        self.env["dev.work.checkpoint"].sudo().create(
            {
                "work_item_id": work.id,
                "trigger": "client_review",
                "lifecycle_phase": "testing",
                "next_recommended_step": "Review completion report.",
            }
        )
        report = self.env["dev.completion.report"].create(
            {
                "work_item_id": work.id,
                "plan_id": plan.id,
                "original_request_summary": "Safe original request",
                "implemented_summary": "Implemented lifecycle controls.",
                "completed_steps_summary": "S1",
                "changed_components_summary": "dev_session_hub only",
                "repository_reference": self.repository.working_directory,
                "branch": "feature/dev-work-lifecycle",
                "tests_summary": "TransactionCase passed.",
                "uat_status": "not_applicable",
                "known_limitations": "No production deployment.",
                "rollback_notes": "No deployment was performed.",
            }
        )
        report.action_ready_review()
        self._transition(work, "ready_for_review")
        report.action_approve()
        self._transition(work, "completed")
        return report

    def _new_revision(self, record):
        result = self._call(
            record,
            ("action_new_revision", "new_revision", "create_new_revision"),
        )
        if getattr(result, "_name", None) == record._name:
            return result
        return self.env[record._name].search(
            [
                ("work_item_id", "=", record.work_item_id.id),
                ("revision", ">", record.revision),
            ],
            order="revision desc",
            limit=1,
        )

    def test_source_dedupe_and_many_to_many_work_items(self):
        first = self._work()
        second_task = self.env["project.task"].create(
            {"name": "Second source-derived task", "project_id": self.odoo_project.id}
        )
        second = self._work(wp_id=False, task=second_task)
        values = self._model_vals(
            "dev.work.source.message",
            provider="evolution",
            instance_reference="test-instance",
            provider_message_id="message-001",
            evolution_message_id="message-001",
            group_jid="120363000000000000@g.us",
            sender_jid="201000000000@s.whatsapp.net",
            chatwoot_account_id=1,
            chatwoot_inbox_id=2,
            chatwoot_conversation_id=3,
            chatwoot_message_id=4,
            message_timestamp="2026-07-18 16:20:00",
            text_snapshot="Sanitized development request",
            text_hash="b" * 64,
            attachment_references="attachment://safe-reference",
            source_url="https://chatwoot.test.invalid/conversations/3",
            dedupe_key="evolution:test-instance:message-001",
            work_item_ids=[(6, 0, [first.id, second.id])],
        )
        source = self.env["dev.work.source.message"].create(values)
        self.assertEqual(set(source.work_item_ids.ids), {first.id, second.id})
        with self.assertRaises(UniqueViolation), self.env.cr.savepoint():
            self.env["dev.work.source.message"].create(values)

    def test_openproject_and_odoo_task_identity_constraints(self):
        self._work()
        other_task = self.env["project.task"].create(
            {"name": "Other task", "project_id": self.odoo_project.id}
        )
        with self.assertRaises(UniqueViolation), self.env.cr.savepoint():
            self._work(task=other_task)

        unlinked = self.env["project.task"].create(
            {"name": "Unlinked unique work", "project_id": self.odoo_project.id}
        )
        self._work(wp_id=False, task=unlinked)
        with self.assertRaises(UniqueViolation), self.env.cr.savepoint():
            self._work(wp_id=False, task=unlinked)

        mismatched = self.env["project.task"].create(
            {
                "name": "Mismatched WP task",
                "project_id": self.odoo_project.id,
                "op_backend_id": self.backend.id,
                "op_work_package_id": 880099,
            }
        )
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._work(wp_id=880098, task=mismatched)

    def test_lifecycle_direct_write_transition_rules_and_events(self):
        work = self._work()
        phase_field = (
            "current_phase"
            if "current_phase" in work._fields
            else "state"
        )
        self.assertEqual(work[phase_field], "received")
        with self.assertRaises(AccessError):
            work.write({phase_field: "implementing"})

        self._transition(work, "triage")
        self.assertEqual(work[phase_field], "triage")
        events = self.env["dev.work.lifecycle.event"].search(
            [("work_item_id", "=", work.id)]
        )
        self.assertEqual(len(events), 2)
        with self.assertRaises(UserError):
            self._transition(work, "implementing")
        with self.assertRaises(AccessError):
            events.write({"reason": "tampered"})
        with self.assertRaises(AccessError):
            events.unlink()

    def test_accepted_analysis_is_immutable_and_revisioned(self):
        work = self._work()
        self._transition(work, "triage")
        self._transition(work, "registered")
        self._transition(work, "analyzing")
        analysis = self._analysis(work)
        original_hash = analysis.content_hash
        self._accept_analysis(analysis)
        self.assertEqual(analysis.status, "accepted")
        self.assertTrue(analysis.content_hash)
        with self.assertRaises(AccessError):
            analysis.write({"problem_summary": "mutated after acceptance"})

        revision = self._new_revision(analysis)
        self.assertTrue(revision)
        self.assertEqual(revision.revision, analysis.revision + 1)
        self.assertEqual(revision.parent_revision_id, analysis)
        self.assertEqual(revision.status, "draft")
        self.assertEqual(analysis.content_hash, original_hash or analysis.content_hash)
        accepted = (
            work.current_accepted_analysis_id
            if "current_accepted_analysis_id" in work._fields
            else work.accepted_analysis_id
        )
        self.assertEqual(accepted, analysis)

    def test_exact_plan_hash_approval_and_new_revision_clears_effective_approval(self):
        work = self._work()
        self._transition(work, "triage")
        self._transition(work, "registered")
        self._transition(work, "analyzing")
        analysis = self._analysis(work)
        self._accept_analysis(analysis)
        self._transition(work, "planning")
        plan = self._plan(work, with_step=True)
        self._submit_plan(plan)
        self.assertEqual(plan.status, "awaiting_approval")
        self.assertTrue(plan.content_hash)

        approval_model = self.env["dev.work.approval"]
        with self.assertRaises(UserError), self.env.cr.savepoint():
            plan.action_approve_exact("0" * 64)

        self._approve_plan(plan)
        self.assertEqual(plan.status, "approved")
        approvals = approval_model.search(
            [("work_item_id", "=", work.id), ("decision", "=", "approved")]
        )
        self.assertEqual(len(approvals), 1)
        approval_hash_field = (
            "exact_plan_hash"
            if "exact_plan_hash" in approvals._fields
            else "plan_hash"
        )
        self.assertEqual(approvals[approval_hash_field], plan.content_hash)
        with self.assertRaises(AccessError):
            plan.write({"goal": "Mutated approved goal"})
        with self.assertRaises(AccessError):
            approvals.write({"comment": "tampered"})

        revision = self._new_revision(plan)
        self.assertEqual(revision.revision, plan.revision + 1)
        self.assertEqual(revision.parent_revision_id, plan)
        self.assertEqual(revision.status, "draft")
        approved = (
            work.current_approved_plan_id
            if "current_approved_plan_id" in work._fields
            else work.approved_plan_id
        )
        self.assertFalse(approved)

    def test_plan_step_progress(self):
        work = self._work()
        plan = self._plan(work)
        Step = self.env["dev.work.plan.step"]
        steps = Step
        for sequence, status in enumerate(("done", "done", "done", "pending"), 1):
            steps |= Step.create(
                self._model_vals(
                    "dev.work.plan.step",
                    plan_id=plan.id,
                    plan_revision_id=plan.id,
                    step_key="S%s" % sequence,
                    sequence=sequence,
                    title="Step %s" % sequence,
                    description="Bounded test step",
                    status=status,
                )
            )
        plan.invalidate_recordset()
        self.assertEqual(plan.progress, 75.0)
        work.invalidate_recordset()
        self.assertEqual(work.completed_step_count, 3)
        self.assertEqual(work.actionable_step_count, 4)
        if "progress_done" in plan._fields:
            self.assertEqual(plan.progress_done, 3)
        if "progress_total" in plan._fields:
            self.assertEqual(plan.progress_total, 4)

    def test_checkpoint_is_immutable_and_pause_creates_one(self):
        work = self._work()
        self._approved_plan(work)
        session = self._session(work)
        with self._snapshot_patch():
            session.action_start()
            before = self.env["dev.work.checkpoint"].search_count(
                [("work_item_id", "=", work.id)]
            )
            session.action_pause()
        checkpoints = self.env["dev.work.checkpoint"].search(
            [("work_item_id", "=", work.id)], order="id desc"
        )
        self.assertEqual(len(checkpoints), before + 1)
        self.assertEqual(checkpoints[0].session_id, session)
        self.assertEqual(checkpoints[0].trigger, "pause")
        self.assertEqual(checkpoints[0].branch, self.snapshot["branch"])
        self.assertEqual(checkpoints[0].git_head, self.snapshot["head"])
        with self.assertRaises(AccessError):
            checkpoints[0].write({"blockers": "tampered"})
        with self.assertRaises(AccessError):
            checkpoints[0].unlink()

    def test_resume_brief_is_sanitized_bounded_and_reports_drift(self):
        work = self._work()
        self._approved_plan(work)
        source = self.env["dev.work.source.message"].create(
            self._model_vals(
                "dev.work.source.message",
                provider="chatwoot",
                chatwoot_conversation_id=991,
                chatwoot_message_id=992,
                text_snapshot="Safe original request",
                provider_message_id="992",
                work_item_ids=[(4, work.id)],
            )
        )
        self.assertTrue(source)
        session = self._session(work)
        with self._snapshot_patch():
            session.action_start()
            session.action_pause()
        changed = dict(
            self.snapshot,
            branch="feature/changed",
            head="d" * 40,
            dirty="staged=0; unstaged=3; untracked=1; conflicts=0; digest=changed",
        )
        session.client_id = self.ubuntu
        with self._snapshot_patch(changed):
            session.action_resume()

        brief = self._call(
            work,
            (
                "build_resume_brief",
                "_build_resume_brief",
                "get_resume_brief",
                "generate_resume_brief",
            ),
            session,
        )
        if isinstance(brief, dict):
            serialized = json.dumps(brief, sort_keys=True)
        else:
            serialized = str(brief)
        self.assertLessEqual(len(serialized), 16000)
        self.assertIn("changed", serialized.lower())
        self.assertIn("feature/changed", serialized)
        forbidden = (
            "password=",
            "authorization:",
            "bearer ",
            "private key",
            "cursor transcript",
        )
        for token in forbidden:
            self.assertNotIn(token, serialized.lower())
        with self._snapshot_patch():
            session.action_abandon()

    def test_completion_report_lifecycle_and_immutability(self):
        work = self._work()
        plan = self._approved_plan(work)
        step = plan.step_ids[:1]
        step.write({"status": "in_progress"})
        step.write({"status": "done"})
        self._transition(work, "implementing")
        self._transition(work, "testing")
        self.env["dev.work.checkpoint"].sudo().create(
            {
                "work_item_id": work.id,
                "trigger": "client_review",
                "lifecycle_phase": "testing",
                "next_recommended_step": "Review the completion report.",
            }
        )
        report = self.env["dev.completion.report"].create(
            self._model_vals(
                "dev.completion.report",
                work_item_id=work.id,
                plan_id=plan.id,
                revision=1,
                status="draft",
                original_request_summary="Safe original request",
                implemented_summary="Implemented lifecycle controls.",
                completed_steps_summary="S1",
                changed_components_summary="dev_session_hub only",
                repository_reference=self.repository.working_directory,
                branch="feature/dev-work-lifecycle",
                tests_summary="TransactionCase passed.",
                uat_status="not_applicable",
                known_limitations="No production deployment.",
                rollback_notes="No deployment was performed.",
                deployment_status="not_deployed",
                production_status="not_verified",
                follow_up_items="Review before Phase 5.",
            )
        )
        self._call(
            report,
            ("action_ready_review", "action_submit_for_review", "action_request_review"),
        )
        self.assertEqual(report.status, "ready_review")
        self._transition(work, "ready_for_review")
        self._call(report, ("action_approve", "action_mark_approved"))
        self.assertEqual(report.status, "approved")
        self.assertTrue(report.content_hash)
        with self.assertRaises(AccessError):
            report.write({"implemented_summary": "tampered"})
        completed = (
            work.completion_report_id
            if "completion_report_id" in work._fields
            else work.current_completion_report_id
        )
        self.assertEqual(completed, report)

    def test_communication_requires_review_and_queues_chatwoot_without_http(self):
        work = self._work()
        report = self._approved_report(work)
        communication = self.env["dev.work.communication"].create(
            self._model_vals(
                "dev.work.communication",
                work_item_id=work.id,
                completion_report_id=report.id,
                source_message_id=work.source_message_ids[:1].id,
                communication_type="completion",
                chatwoot_account_id=1,
                chatwoot_inbox_id=2,
                chatwoot_conversation_id=775,
                destination_type="group_jid",
                destination_reference="120363000000000000@g.us",
                language_code="en",
                body="The reviewed test-only work is complete.",
            )
        )
        with self.assertRaises(UserError):
            self._call(
                communication,
                ("action_queue", "action_queue_send", "action_send"),
            )

        with patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("Dev Hub must never perform direct HTTP"),
        ):
            self._call(
                communication,
                ("action_review", "action_submit_review", "action_request_review"),
            )
            self._call(
                communication,
                ("action_approve_send", "action_approve"),
            )
            outbox = self._call(
                communication,
                ("action_queue", "action_queue_send", "action_send"),
            )

        self.assertEqual(outbox.channel, "chatwoot")
        self.assertEqual(outbox.state, "pending")
        self.assertEqual(outbox.idempotency_key, communication.idempotency_key)
        payload_field = (
            "payload_json" if "payload_json" in outbox._fields else "payload"
        )
        payload = outbox[payload_field]
        self.assertLessEqual(len(payload), 16000)
        self.assertIn("chatwoot", payload.lower())
        self.assertNotIn("api_token", payload.lower())
        self.assertFalse(communication.chatwoot_message_id)
        self.assertFalse(communication.evolution_message_id)
        self.assertEqual(communication.state, "queued")

    def test_full_phase_1_to_4_uat_without_automatic_send(self):
        work = self._work()
        self._transition(work, "triage")
        self._transition(work, "registered")
        self._transition(work, "analyzing")
        analysis = self._analysis(work)
        self._accept_analysis(analysis)
        self._transition(work, "planning")

        plan_v1 = self._plan(work)
        for sequence in range(1, 6):
            self.env["dev.work.plan.step"].create(
                {
                    "plan_id": plan_v1.id,
                    "step_key": "P%s" % sequence,
                    "sequence": sequence * 10,
                    "title": "Test-safe implementation step %s" % sequence,
                }
            )
        plan_v2 = self._new_revision(plan_v1)
        self.assertEqual(plan_v2.revision, 2)
        self.assertEqual(plan_v1.status, "superseded")
        self._submit_plan(plan_v2)
        self._approve_plan(plan_v2)

        session = self._session(work)
        with self._snapshot_patch():
            session.action_start()
        for step in plan_v2.step_ids.sorted(lambda item: (item.sequence, item.id))[:3]:
            step.write({"status": "in_progress"})
            step.write({"status": "done", "result_summary": "Verified in Test."})
        with self._snapshot_patch():
            session.action_pause()
        self.assertEqual(work.current_checkpoint_id.trigger, "pause")
        self.assertEqual(work.completed_step_count, 3)

        with self._snapshot_patch():
            session.write({"client_id": self.ubuntu.id})
            action = session.action_resume()
        wizard = self.env[action["res_model"]].browse(action["res_id"])
        self.assertIn("Revision 2", wizard.resume_brief)
        self.assertIn("progress 3 / 5", wizard.resume_brief)
        for step in plan_v2.step_ids.filtered(lambda item: item.status == "pending"):
            step.write({"status": "in_progress"})
            step.write({"status": "done", "result_summary": "Verified in Test."})
        self._transition(work, "testing")

        report = self.env["dev.completion.report"].create(
            {
                "work_item_id": work.id,
                "plan_id": plan_v2.id,
                "original_request_summary": work.source_message_ids[:1].text_snapshot,
                "implemented_summary": "Completed the approved Test-only lifecycle plan.",
                "completed_steps_summary": "P1, P2, P3, P4, P5",
                "changed_components_summary": "dev_session_hub only",
                "repository_reference": self.repository.working_directory,
                "branch": "feature/dev-work-lifecycle",
                "tests_summary": "Five plan steps completed; TransactionCase passed.",
                "uat_status": "passed",
                "known_limitations": "No production deployment and no autonomous worker.",
                "rollback_notes": "No external deployment occurred.",
            }
        )
        report.action_ready_review()
        with self._snapshot_patch():
            work.action_ready_for_review()
        report.action_approve()
        work.action_complete()

        before = self.env["dev.external.outbox"].search_count(
            [("work_item_id", "=", work.id), ("channel", "=", "chatwoot")]
        )
        source = work.source_message_ids[:1]
        communication = self.env["dev.work.communication"].create(
            {
                "work_item_id": work.id,
                "completion_report_id": report.id,
                "source_message_id": source.id,
                "communication_type": "completion",
                "body": "تم الانتهاء من العمل واختباره على بيئة الاختبار.",
                "chatwoot_account_id": source.chatwoot_account_id or 1,
                "chatwoot_inbox_id": source.chatwoot_inbox_id or 2,
                "chatwoot_conversation_id": source.chatwoot_conversation_id or 3,
                "reply_to_chatwoot_message_id": source.chatwoot_message_id,
                "destination_type": "group_jid",
                "destination_reference": source.group_jid
                or "120363000000000000@g.us",
            }
        )
        communication.action_review()
        communication.action_approve()
        self.assertEqual(
            self.env["dev.external.outbox"].search_count(
                [("work_item_id", "=", work.id), ("channel", "=", "chatwoot")]
            ),
            before,
            "Human approval must not auto-send or auto-queue.",
        )
        communication.action_queue()
        work.action_reported()
        with self._snapshot_patch():
            session.action_complete()
        self.assertEqual(work.lifecycle_phase, "reported")

    def test_production_linked_session_is_denied_without_external_calls(self):
        work = self._work()
        self._approved_plan(work)
        production = self.env["dev.environment"].create(
            {
                "name": "Lifecycle blocked production fixture",
                "project_id": self.dev_project.id,
                "environment_type": "production",
                "machine_id": self.machine.id,
                "database_identifier": "redacted-production-fixture",
                "port": 9997,
                "config_reference": "/unresolved/production.conf",
                "service_container_reference": "unresolved",
                "data_sensitivity": "production",
                "production_guard_policy": "Development launch disabled.",
            }
        )
        session = self._session(work, environment=production)
        with patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("Production denial must not call HTTP"),
        ), self.assertRaises(UserError):
            session.action_start()
        self.assertEqual(session.state, "draft")
        self.assertFalse(
            self.env["dev.work.checkpoint"].search(
                [("session_id", "=", session.id)]
            )
        )

    def _outbox_user(self):
        return new_test_user(
            self.env,
            login="dev-hub-outbox-%s" % uuid.uuid4().hex,
            groups="dev_session_hub.group_dev_hub_integration",
        )

    def _generation_user(self):
        return new_test_user(
            self.env,
            login="dev-hub-generation-%s" % uuid.uuid4().hex,
            groups="dev_session_hub.group_dev_hub_generation",
        )

    def _generation_ready_work(self):
        work = self._work()
        self._transition(work, "triage")
        self._transition(work, "registered")
        self.env["dev.work.checkpoint"].sudo().create(
            {
                "work_item_id": work.id,
                "trigger": "milestone",
                "lifecycle_phase": "registered",
                "repository_id": self.repository.id,
                "git_head": "b" * 40,
                "next_recommended_step": "Generate analysis.",
            }
        )
        work._refresh_context_revision()
        return work

    def test_outbox_service_leasing_callbacks_and_queue_idempotency(self):
        work = self._work()
        outbox = work._queue_outbox(
            "openproject",
            "milestone",
            {
                "schema": "dev-hub.op-milestone.v1",
                "backend_id": self.backend.id,
                "work_package_id": work.op_work_package_id,
                "milestone": "material_blocker",
                "summary": "Test-only blocker.",
                "status_hint": "on_hold",
            },
            "test:%s" % uuid.uuid4().hex,
        )
        duplicate = work._queue_outbox(
            outbox.channel,
            outbox.operation,
            json.loads(outbox.payload_json),
            outbox.idempotency_key,
        )
        self.assertEqual(duplicate, outbox)

        integration = self._outbox_user()
        service = self.env["dev.external.outbox"].with_user(integration)
        lease = service.service_lease(limit=1, consumer_ref="test-consumer")
        self.assertEqual(lease[0]["id"], outbox.id)
        self.assertEqual(outbox.state, "leased")
        service.service_mark_processing(
            outbox.id, outbox.correlation_id, lease[0]["lease_token"]
        )
        result = service.service_ack_success(
            outbox.id,
            outbox.correlation_id,
            lease[0]["lease_token"],
            {"external_reference": "test-activity-1"},
        )
        self.assertEqual(result["state"], "done")
        self.assertEqual(outbox.state, "done")
        self.assertEqual(
            service.service_ack_success(outbox.id, outbox.correlation_id)["state"],
            "done",
        )

        ordinary = new_test_user(
            self.env,
            login="dev-hub-ordinary-%s" % uuid.uuid4().hex,
            groups="dev_session_hub.group_dev_hub_user",
        )
        with self.assertRaises(AccessError):
            self.env["dev.external.outbox"].with_user(ordinary).service_lease()

    def test_outbox_retry_dead_letter_and_service_scope(self):
        work = self._work()
        outbox = work._prepare_op_milestone(
            "material_blocker", "Safe test-only retry.", "on_hold"
        )
        outbox_user = self._outbox_user()
        generation_user = self._generation_user()
        service = self.env["dev.external.outbox"].with_user(outbox_user)
        with self.assertRaises(AccessError):
            self.env["dev.external.outbox"].with_user(generation_user).service_lease()
        lease = service.service_lease(limit=1, consumer_ref="retry-test")[0]
        retry = service.service_ack_failure(
            outbox.id,
            outbox.correlation_id,
            "temporary_transport",
            "Temporary transport failure before a confirmed delivery.",
            lease_token=lease["lease_token"],
            transient=True,
            retry_after_seconds=30,
        )
        self.assertEqual(retry["state"], "retry")
        outbox.with_context(dev_outbox_action=True).write(
            {"next_attempt_at": fields.Datetime.now()}
        )
        lease = service.service_lease(limit=1, consumer_ref="dead-letter-test")[0]
        service.service_mark_processing(
            outbox.id, outbox.correlation_id, lease["lease_token"]
        )
        dead = service.service_ack_failure(
            outbox.id,
            outbox.correlation_id,
            "delivery_uncertain",
            "External outcome is uncertain; automatic retry is unsafe.",
            lease_token=lease["lease_token"],
            transient=True,
            delivery_uncertain=True,
        )
        self.assertEqual(dead["state"], "uncertain_delivery")

    def test_outbox_stale_lease_is_fenced_and_uncertain_delivery_reconciles(self):
        work = self._work()
        outbox = work._prepare_op_milestone(
            "material_blocker", "Safe reconciliation test.", "on_hold"
        )
        service = self.env["dev.external.outbox"].with_user(self._outbox_user())
        first = service.service_lease(limit=1, consumer_ref="first-worker")[0]
        service.service_mark_processing(
            outbox.id, outbox.correlation_id, first["lease_token"]
        )
        service.service_ack_failure(
            outbox.id,
            outbox.correlation_id,
            "delivery_uncertain",
            "Provider acceptance requires reconciliation.",
            lease_token=first["lease_token"],
            transient=False,
            delivery_uncertain=True,
            retry_after_seconds=30,
        )
        self.assertEqual(outbox.state, "uncertain_delivery")
        outbox.with_context(dev_outbox_action=True).write(
            {"next_attempt_at": fields.Datetime.now()}
        )
        second = service.service_lease(limit=1, consumer_ref="reconciler")[0]
        self.assertTrue(second["reconcile_only"])
        self.assertNotEqual(first["lease_token"], second["lease_token"])
        self.assertGreater(second["lease_version"], first["lease_version"])
        with self.assertRaises(AccessError):
            service.service_mark_processing(
                outbox.id, outbox.correlation_id, first["lease_token"]
            )
        service.service_mark_processing(
            outbox.id, outbox.correlation_id, second["lease_token"]
        )
        result = service.service_ack_success(
            outbox.id,
            outbox.correlation_id,
            second["lease_token"],
            {"external_reference": "reconciled-activity-1"},
        )
        self.assertEqual(result["state"], "done")
        self.assertFalse(outbox.reconciliation_required)

    def test_outbox_rejects_unsupported_or_malformed_intents(self):
        work = self._work()
        with self.assertRaises(ValidationError):
            self.env["dev.external.outbox"].with_context(
                dev_internal_outbox=True
            ).create(
                {
                    "work_item_id": work.id,
                    "channel": "chatwoot",
                    "operation": "public_message",
                    "payload_json": {
                        "schema": "dev-hub.chatwoot-public-message.v0",
                        "account_id": 1,
                    },
                    "idempotency_key": "invalid:%s" % uuid.uuid4().hex,
                }
            )
        with self.assertRaises(ValidationError):
            work._prepare_op_milestone(
                "every_transition", "Unsupported noisy milestone.", "in_progress"
            )

    def test_generation_callbacks_create_drafts_without_plan_approval(self):
        work = self._generation_ready_work()
        analysis_request = work.action_request_analysis_generation()
        integration = self._generation_user()
        service = self.env["dev.work.generation"].with_user(integration)
        with self.assertRaises(AccessError):
            self.env["dev.work.item"].with_user(integration).import_analysis_draft(
                {
                    "work_item_uuid": work.uuid,
                    "problem_summary": "Bypass attempt.",
                    "original_request_summary": "Must use service_complete.",
                }
            )
        lease = service.service_lease(limit=1, consumer_ref="generation-test")[0]
        self.assertEqual(lease["id"], analysis_request.id)
        service.service_mark_processing(
            analysis_request.id,
            analysis_request.correlation_id,
            lease["lease_token"],
            "dify:analysis",
            "analysis-run-%s" % uuid.uuid4().hex,
        )
        outcome = service.service_complete(
            analysis_request.id,
            analysis_request.correlation_id,
            lease["lease_token"],
            {
                "problem_summary": "A bounded test problem.",
                "original_request_summary": "A bounded test request.",
                "technical_findings": "No production evidence.",
                "observed_head": "b" * 40,
            },
        )
        analysis = self.env[outcome["artifact_model"]].browse(
            outcome["artifact_record_id"]
        )
        self.assertEqual(analysis.status, "generated")
        self.assertEqual(work.current_phase, "analyzing")

        analysis.action_accept()
        plan_request = work.action_request_plan_generation()
        lease = service.service_lease(limit=1, consumer_ref="generation-test")[0]
        self.assertEqual(lease["id"], plan_request.id)
        service.service_mark_processing(
            plan_request.id,
            plan_request.correlation_id,
            lease["lease_token"],
            "dify:plan",
            "plan-run-%s" % uuid.uuid4().hex,
        )
        outcome = service.service_complete(
            plan_request.id,
            plan_request.correlation_id,
            lease["lease_token"],
            {
                "goal": "Implement only the approved scope.",
                "scope": "Test scope.",
                "out_of_scope": "Production deployment.",
                "proposed_changes": "Change the test fixture.",
                "affected_components": "dev_session_hub tests.",
                "migration_impact": "None.",
                "security_impact": "Guarded callback only.",
                "test_plan": "Run TransactionCase.",
                "rollback_plan": "Revert the reviewed change.",
                "dependencies": "Odoo test framework.",
                "risks": "Incorrect callback state.",
                "acceptance_criteria": "The test passes.",
                "steps": [
                    {
                        "step_key": "S1",
                        "sequence": 10,
                        "title": "Implement fixture",
                        "description": "Apply the bounded change.",
                        "dependency_keys": "",
                        "acceptance_evidence": "TransactionCase output.",
                    }
                ],
            },
        )
        plan = self.env[outcome["artifact_model"]].browse(outcome["artifact_record_id"])
        self.assertEqual(plan.status, "awaiting_approval")
        self.assertEqual(work.current_phase, "awaiting_plan_approval")
        self.assertFalse(plan.approval_ids)
        with self.assertRaises(AccessError):
            self.env["dev.work.generation"].with_user(
                self._outbox_user()
            ).service_lease()

    def test_generation_rejects_stale_context(self):
        work = self._generation_ready_work()
        request = work.action_request_analysis_generation()
        integration = self._generation_user()
        service = self.env["dev.work.generation"].with_user(integration)
        lease = service.service_lease(limit=1, consumer_ref="stale-test")[0]
        with self.assertRaises(AccessError):
            service.service_mark_processing(
                request.id,
                request.correlation_id,
                "stale-generation-token",
                "dify:analysis",
                "stale-worker-run",
            )
        service.service_mark_processing(
            request.id,
            request.correlation_id,
            lease["lease_token"],
            "dify:analysis",
            "stale-run-%s" % uuid.uuid4().hex,
        )
        work.action_analyze()
        outcome = service.service_complete(
            request.id,
            request.correlation_id,
            lease["lease_token"],
            {
                "problem_summary": "Stale output.",
                "original_request_summary": "Stale request.",
            },
        )
        self.assertEqual(outcome["error_code"], "stale_generation_context")
        self.assertEqual(request.state, "dead_letter")
        self.assertFalse(request.artifact_record_id)

    def test_generation_rejects_invalid_schema_and_production(self):
        work = self._generation_ready_work()
        request = work.action_request_analysis_generation()
        service = self.env["dev.work.generation"].with_user(self._generation_user())
        lease = service.service_lease(limit=1, consumer_ref="invalid-output-test")[0]
        service.service_mark_processing(
            request.id,
            request.correlation_id,
            lease["lease_token"],
            "dify:analysis",
            "invalid-run-%s" % uuid.uuid4().hex,
        )
        outcome = service.service_complete(
            request.id,
            request.correlation_id,
            lease["lease_token"],
            {"problem_summary": "Missing required original request summary."},
        )
        self.assertEqual(outcome["error_code"], "invalid_generation_output")
        self.assertEqual(request.state, "dead_letter")
        self.assertFalse(request.artifact_record_id)

        production = self.env["dev.environment"].create(
            {
                "name": "Generation blocked production fixture",
                "project_id": self.dev_project.id,
                "environment_type": "production",
                "machine_id": self.machine.id,
                "database_identifier": "redacted-production-generation",
                "odoo_version": "19.0",
                "port": 65531,
                "config_reference": "/unresolved/production.conf",
                "service_container_reference": "unresolved-production-service",
                "url": "https://production.invalid",
                "data_sensitivity": "production",
                "production_guard_policy": "Generation disabled.",
            }
        )
        blocked = work
        blocked.write({"preferred_environment_id": production.id})
        with self.assertRaises(UserError):
            blocked.action_request_analysis_generation()

    def test_communication_context_cannot_forge_review_or_queue(self):
        work = self._work()
        report = self._approved_report(work)
        source = work.source_message_ids[:1]
        communication = self.env["dev.work.communication"].create(
            {
                "work_item_id": work.id,
                "completion_report_id": report.id,
                "source_message_id": source.id,
                "communication_type": "completion",
                "body": "Reviewed exact destination test.",
                "chatwoot_account_id": source.chatwoot_account_id,
                "chatwoot_inbox_id": source.chatwoot_inbox_id,
                "chatwoot_conversation_id": source.chatwoot_conversation_id,
                "destination_type": "group_jid",
                "destination_reference": source.group_jid,
            }
        )
        communication.action_review()
        with self.assertRaises(AccessError):
            communication.with_context(dev_communication_action=True).write(
                {"state": "queued"}
            )
        with self.assertRaises(AccessError):
            communication.write({"body": "Changed after review"})
        communication.action_approve()
        first = communication.action_queue()
        second = communication.action_queue()
        self.assertEqual(first, second)
        self.assertEqual(communication.review_hash, communication.approved_hash)

    def test_approver_cannot_forge_immutable_approval_record(self):
        work = self._work()
        self._transition(work, "triage")
        self._transition(work, "registered")
        self._transition(work, "analyzing")
        analysis = self._analysis(work)
        analysis.action_accept()
        self._transition(work, "planning")
        plan = self._plan(work, with_step=True)
        plan.action_submit_for_approval()
        approver = new_test_user(
            self.env,
            login="dev-hub-approver-%s" % uuid.uuid4().hex,
            groups=(
                "dev_session_hub.group_dev_hub_user,"
                "dev_session_hub.group_dev_hub_approver"
            ),
        )
        self.dev_project.write({"member_ids": [(4, approver.id)]})
        self.assertIn(approver, self.dev_project.member_ids)
        with self.assertRaises(AccessError):
            self.env["dev.work.approval"].with_user(approver).with_context(
                dev_internal_approval=True
            ).create(
                {
                    "work_item_id": work.id,
                    "plan_id": plan.id,
                    "plan_revision": plan.revision,
                    "plan_hash": plan.content_hash,
                    "decision": "approved",
                    "approver_id": approver.id,
                    "decided_at": "2026-07-18 20:00:00",
                }
            )
        approval = plan.with_user(approver).action_approve_exact(plan.content_hash)
        self.assertEqual(approval.approver_id, approver)
