"""Create the new, bounded Phase 5 retry Work Item."""

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
        ("provider_message_id", "=", "phase5-worker-pilot-retry-20260719"),
    ]
):
    raise RuntimeError("Phase 5 retry fixture already exists")

odoo_project = env["project.project"].create(
    {"name": "Phase 5 Worker Pilot Retry — Test Contract"}
)
odoo_task = env["project.task"].create(
    {
        "name": "Phase 5 retry: add fixture README contract test",
        "project_id": odoo_project.id,
        "op_backend_id": backend.id,
        "op_work_package_id": 990003,
        "op_url": "https://openproject.uat.invalid/work_packages/990003",
    }
)
source = env["dev.work.source.message"].create(
    {
        "provider": "manual",
        "provider_message_id": "phase5-worker-pilot-retry-20260719",
        "message_timestamp": fields.Datetime.now(),
        "text_snapshot": (
            "Retry the bounded fixture README test after strict Git porcelain "
            "path normalization. Stop at human review."
        ),
    }
)
work = env["dev.work.item"].create(
    {
        "name": "Phase5 Retry: add fixture README contract test",
        "dev_project_id": project.id,
        "odoo_project_id": odoo_project.id,
        "odoo_task_id": odoo_task.id,
        "op_backend_id": backend.id,
        "op_work_package_id": 990003,
        "op_reference": "UAT WP #990003",
        "op_url": "https://openproject.uat.invalid/work_packages/990003",
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
            "DW-4 failed closed because raw Git porcelain status prefixes were "
            "compared with path-only allowlist entries."
        ),
        "original_request_snapshot": (
            "Run a new bounded pilot after strict parser and regression tests pass."
        ),
        "reproduction_context": (
            "DW-4 produced two untracked records prefixed with question-mark "
            "status columns; actual paths were authorized."
        ),
        "current_behavior": (
            "The corrected parser emits canonical repository-relative paths."
        ),
        "expected_behavior": (
            "The exact two retry Test files pass allowlist validation; any extra "
            "path remains denied."
        ),
        "technical_findings": (
            "Porcelain v1 -z is parsed by XY columns and NUL records. Rename/copy "
            "source and destination are validated."
        ),
        "affected_components": (
            "tests/__init__.py\ntests/test_fixture_readme_retry.py"
        ),
        "risks": (
            "No policy broadening. Malformed, escaping, undecodable, or "
            "disallowed paths fail closed."
        ),
        "dependencies": "Python 3 standard library only.",
        "open_questions": "None.",
        "evidence_references": (
            "uat://phase5-worker-pilot/DW-4; "
            "uat://phase5-worker-pilot-retry/20260719"
        ),
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
            "Execute one corrected, bounded fixture README test addition and "
            "stop at Review Required."
        ),
        "scope": (
            "Only tests/__init__.py and tests/test_fixture_readme_retry.py."
        ),
        "out_of_scope": (
            "All other files; DW-3/DW-4; Production; credentials; Docker; "
            "services; commit; push; PR; merge; deployment; messages; cleanup."
        ),
        "proposed_changes": (
            "Create a stdlib unittest and enforce normalized Git path allowlisting."
        ),
        "affected_components": (
            "tests/__init__.py\ntests/test_fixture_readme_retry.py"
        ),
        "migration_impact": "None.",
        "security_impact": (
            "Strict parser corrects representation only; policy remains exact."
        ),
        "test_plan": (
            "python3 -m unittest -v tests.test_fixture_readme_retry; "
            "python3 -m unittest discover -s tests -v"
        ),
        "rollback_plan": (
            "Human may discard the two uncommitted retry files. No automatic cleanup."
        ),
        "dependencies": "Python 3 standard library.",
        "risks": "Any parser, lease, hash, path, or isolation mismatch fails closed.",
        "acceptance_criteria": (
            "Parser accepts exactly two files; tests pass; Pause/Resume and "
            "concurrency fencing pass; final state is review_required."
        ),
    }
)
steps = [
    (
        "P1",
        "Inspect target Test files",
        "Validate controlled references, identity, workspace, Base HEAD, and README.",
    ),
    (
        "P2",
        "Implement and normalize allowlist",
        "Create exactly two files and pass normalized porcelain allowlist validation.",
    ),
    (
        "P3",
        "Run targeted tests",
        "Run the approved targeted unittest and record 2/2 passing.",
    ),
    (
        "P4",
        "Pause and Resume",
        "Checkpoint, fence the lease, resume the same worktree, reject second writer.",
    ),
    (
        "P5",
        "Regression and Review Handoff",
        "Run discovery, verify isolation, and stop at review_required.",
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
    comment="Phase 5 parser-fix re-attempt approved exactly",
    policy_version="phase5-pilot-retry-v1",
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
            "dw4_state": env["dev.execution.workspace"].browse(8).state,
        },
        sort_keys=True,
    )
)
