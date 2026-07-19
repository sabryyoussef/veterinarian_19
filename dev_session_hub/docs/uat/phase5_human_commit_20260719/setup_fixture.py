"""Create the single new Human-Approved Git Commit UAT Work Item."""

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
        ("provider_message_id", "=", "phase5-human-commit-20260719"),
    ]
):
    raise RuntimeError("Human commit UAT fixture already exists")
if env["dev.execution.workspace"].browse(9).state != "review_required":
    raise RuntimeError("DW-5 review evidence is not preserved")

odoo_project = env["project.project"].create(
    {"name": "Phase 5 Human-Approved Commit UAT"}
)
odoo_task = env["project.task"].create(
    {
        "name": "Human-approved local commit for bounded Test change",
        "project_id": odoo_project.id,
        "op_backend_id": backend.id,
        "op_work_package_id": 990004,
        "op_url": "https://openproject.uat.invalid/work_packages/990004",
    }
)
source = env["dev.work.source.message"].create(
    {
        "provider": "manual",
        "provider_message_id": "phase5-human-commit-20260719",
        "message_timestamp": fields.Datetime.now(),
        "text_snapshot": (
            "Add one harmless Test contract, stop at review, and permit one "
            "separately confirmed local commit."
        ),
    }
)
work = env["dev.work.item"].create(
    {
        "name": "Add human-approved commit contract test",
        "dev_project_id": project.id,
        "odoo_project_id": odoo_project.id,
        "odoo_task_id": odoo_task.id,
        "op_backend_id": backend.id,
        "op_work_package_id": 990004,
        "op_reference": "UAT WP #990004",
        "op_url": "https://openproject.uat.invalid/work_packages/990004",
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
            "Validated worker changes cannot yet be converted into repository "
            "history through an exact human approval."
        ),
        "original_request_snapshot": (
            "Validate one human-approved local commit only."
        ),
        "reproduction_context": (
            "Disposable worker-owned PetSpot UAT repository and non-production host."
        ),
        "current_behavior": "Worker stops at review_required with uncommitted files.",
        "expected_behavior": (
            "Human records exact-state approval, confirms again, and creates "
            "one local commit containing only reviewed files."
        ),
        "technical_findings": (
            "Approval must bind HEAD, dirty/content/file digests, Plan, policy, "
            "contract, approver, and commit-message hash."
        ),
        "affected_components": (
            "tests/__init__.py\ntests/test_human_commit_contract.py"
        ),
        "risks": (
            "Stale approval, extra files, active lease, or non-test target must "
            "block commit."
        ),
        "dependencies": "Git and Python 3 standard library.",
        "open_questions": "None.",
        "evidence_references": "uat://phase5-human-commit/20260719",
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
        "goal": "Add one Test contract and create one human-approved local commit.",
        "scope": (
            "Only tests/__init__.py and tests/test_human_commit_contract.py; "
            "one local commit after review."
        ),
        "out_of_scope": (
            "Push, PR, merge, deployment, Production, services, Docker, prior "
            "workspaces, branch deletion, and cleanup."
        ),
        "proposed_changes": "Create a stdlib unittest for the disposable fixture.",
        "affected_components": (
            "tests/__init__.py\ntests/test_human_commit_contract.py"
        ),
        "migration_impact": "None.",
        "security_impact": "Exact-state approval and exact-path staging required.",
        "test_plan": (
            "python3 -m unittest -v tests.test_human_commit_contract; "
            "python3 -m unittest discover -s tests -v"
        ),
        "rollback_plan": "Before commit, human may reject; after commit retain branch for audit.",
        "dependencies": "Python 3 standard library and local Git.",
        "risks": "Any binding drift or unexpected path invalidates approval.",
        "acceptance_criteria": (
            "Tests pass, review_required reached, approval recorded without "
            "commit, one exact local commit created, no remote action."
        ),
    }
)
steps = [
    ("P1", "Inspect target Test files", "Validate controlled references and fixture."),
    ("P2", "Implement Test contract", "Create exactly two allowlisted Test files."),
    ("P3", "Run targeted tests", "Targeted unittest passes 2/2."),
    ("P4", "Pause and Resume", "Checkpoint, resume, and reject concurrent writer."),
    (
        "P5",
        "Regression and Review Handoff",
        "Regression passes and workspace stops at review_required.",
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
    comment="Human-approved local commit UAT Plan approved exactly",
    policy_version="phase5-human-commit-v1",
)
env.cr.commit()
print(
    json.dumps(
        {
            "work_item_id": work.id,
            "analysis_id": analysis.id,
            "plan_id": plan.id,
            "plan_hash": plan.content_hash,
            "approval_id": approval.id,
            "repository_id": repository.id,
            "environment_id": environment.id,
            "base_head": repository.head_cache,
        },
        sort_keys=True,
    )
)
