"""Create the single authorized Phase 5 pilot Work Item.

Run only in the disposable ``devhub_isolation_uat`` database.
"""

import json

from odoo import fields


project = env["dev.project"].search([("code", "=", "PETSPOT-UAT")], limit=1)
repository = env["dev.repository"].search(
    [("project_id", "=", project.id), ("agent_execution_allowed", "=", True)],
    limit=1,
)
environment = env["dev.environment"].search(
    [
        ("project_id", "=", project.id),
        ("name", "=", "Isolation UAT Test"),
        ("environment_type", "!=", "production"),
    ],
    limit=1,
)
backend = env["openproject.backend"].search(
    [("name", "=", "Isolation UAT Dummy Backend")], limit=1
)
admin = env.ref("base.user_admin")

if not project or not repository or not environment or not backend:
    raise RuntimeError("Validated UAT registry is incomplete")
if env["dev.work.source.message"].search(
    [
        ("provider", "=", "manual"),
        ("provider_message_id", "=", "phase5-worker-pilot-20260719"),
    ]
):
    raise RuntimeError("Phase 5 pilot fixture already exists")

odoo_project = env["project.project"].create(
    {"name": "Phase 5 Worker Pilot — Test Contract"}
)
odoo_task = env["project.task"].create(
    {
        "name": "Phase 5 pilot: add fixture README contract test",
        "project_id": odoo_project.id,
        "op_backend_id": backend.id,
        "op_work_package_id": 990002,
        "op_url": "https://openproject.uat.invalid/work_packages/990002",
    }
)
source = env["dev.work.source.message"].create(
    {
        "provider": "manual",
        "provider_message_id": "phase5-worker-pilot-20260719",
        "message_timestamp": fields.Datetime.now(),
        "text_snapshot": (
            "Add one harmless Python unittest that protects the disposable "
            "PetSpot fixture README contract. Stop at human review."
        ),
    }
)
work = env["dev.work.item"].create(
    {
        "name": "Phase5 Pilot: add fixture README contract test",
        "dev_project_id": project.id,
        "odoo_project_id": odoo_project.id,
        "odoo_task_id": odoo_task.id,
        "op_backend_id": backend.id,
        "op_work_package_id": 990002,
        "op_reference": "UAT WP #990002",
        "op_url": "https://openproject.uat.invalid/work_packages/990002",
        "responsible_user_id": admin.id,
        "preferred_repository_id": repository.id,
        "preferred_environment_id": environment.id,
        "source_message_ids": [(4, source.id)],
    }
)
work.action_triage()
work.action_register()
work.action_start_analysis()
analysis = env["dev.work.analysis"].create(
    {
        "work_item_id": work.id,
        "status": "draft",
        "problem_summary": (
            "The disposable fixture README has no automated contract protecting "
            "its explicit test-only identity."
        ),
        "original_request_snapshot": (
            "Add a bounded test-only contract and stop at review_required."
        ),
        "reproduction_context": (
            "Worker-owned disposable repository on the non-production Precision host."
        ),
        "current_behavior": "README fixture identity is verified only manually.",
        "expected_behavior": (
            "A Python unittest verifies the exact fixture heading and rejects "
            "Production-coupling language."
        ),
        "technical_findings": (
            "The repository contains README.md and no existing test suite. A "
            "stdlib unittest is sufficient and requires no dependency change."
        ),
        "affected_components": "tests/__init__.py\ntests/test_fixture_readme.py",
        "risks": (
            "Unauthorized path expansion or Git side effects; controlled by the "
            "explicit allowlist and worker lease."
        ),
        "dependencies": "Python 3 standard library only.",
        "open_questions": "None.",
        "evidence_references": "uat://phase5-worker-pilot/20260719",
        "origin": "manual",
        "repository_id": repository.id,
        "observed_head": repository.head_cache,
    }
)
analysis.action_accept()
work.action_start_planning()
plan = env["dev.work.plan"].create(
    {
        "work_item_id": work.id,
        "analysis_id": analysis.id,
        "status": "draft",
        "origin": "manual",
        "goal": (
            "Add and execute one bounded fixture README contract test, then stop "
            "for human review."
        ),
        "scope": "Only tests/__init__.py and tests/test_fixture_readme.py.",
        "out_of_scope": (
            "All other files; Production; credentials; Docker; services; commit; "
            "push; PR; merge; deployment; external messages; cleanup."
        ),
        "proposed_changes": (
            "Create a stdlib unittest module that reads README.md without changing it."
        ),
        "affected_components": "tests/__init__.py\ntests/test_fixture_readme.py",
        "migration_impact": "None.",
        "security_impact": (
            "Worker is lease-fenced and may write only two exact Test files."
        ),
        "test_plan": (
            "python3 -m unittest -v tests.test_fixture_readme; "
            "python3 -m unittest discover -s tests -v"
        ),
        "rollback_plan": (
            "Human may discard the two uncommitted allowlisted test files. No "
            "automatic cleanup."
        ),
        "dependencies": "Python 3 standard library.",
        "risks": "Scope expansion, stale lease, or main-worktree drift must fail closed.",
        "acceptance_criteria": (
            "Two tests pass; only allowlisted files change; main worktree remains "
            "unchanged; workspace stops at review_required."
        ),
    }
)
steps = [
    ("P1", "Inspect fixture contract", "Confirm README and execution boundaries."),
    (
        "P2",
        "Implement test-only contract",
        "Create exactly tests/__init__.py and tests/test_fixture_readme.py.",
    ),
    (
        "P3",
        "Run targeted test and pause",
        "Targeted unittest passes, checkpoint is captured, and worker pauses.",
    ),
    (
        "P4",
        "Resume and run regression",
        "Same worktree resumes under a new lease and discovery suite passes.",
    ),
    (
        "P5",
        "Prepare human review",
        "Verify isolation and produce the review handoff without Git publication.",
    ),
]
for sequence, (key, title, description) in enumerate(steps, 1):
    env["dev.work.plan.step"].create(
        {
            "plan_id": plan.id,
            "step_key": key,
            "sequence": sequence,
            "title": title,
            "description": description,
            "acceptance_evidence": description,
            "assignee_type": "agent",
        }
    )
plan.action_submit_for_approval()
approval = plan.action_approve_exact(
    plan.content_hash,
    comment="First bounded Phase 5 worker pilot approved exactly",
    policy_version="phase5-pilot-v1",
)
env.cr.commit()
print(
    json.dumps(
        {
            "work_item_id": work.id,
            "work_uuid": work.uuid,
            "analysis_id": analysis.id,
            "plan_id": plan.id,
            "plan_revision": plan.revision,
            "plan_hash": plan.content_hash,
            "approval_id": approval.id,
            "repository_id": repository.id,
            "environment_id": environment.id,
            "base_head": repository.head_cache,
        },
        sort_keys=True,
    )
)
