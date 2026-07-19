"""Create the single new Human-Approved Git Push UAT Work Item."""

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
    [("provider", "=", "manual"), ("provider_message_id", "=", "phase5-human-push-20260719")]
):
    raise RuntimeError("Human Push UAT fixture already exists")
prior = env["dev.execution.workspace"].browse(10)
if prior.state != "committed_reviewed":
    raise RuntimeError("DW-6 committed review evidence is not preserved")

repository.write({"approved_push_root": "/srv/devhub-uat/remotes"})
remote = env["dev.git.remote"].search(
    [("repository_id", "=", repository.id), ("name", "=", "devhub-uat")], limit=1
)
if not remote:
    remote = env["dev.git.remote"].create(
        {
            "name": "devhub-uat",
            "repository_id": repository.id,
            "remote_url": "/srv/devhub-uat/remotes/petspot-human-push-uat.git",
            "protocol": "file",
            "approved": True,
            "non_production": True,
            "allowed_branch_prefix": "devhub/",
            "protected_branch_patterns": "main\nmaster\nproduction\nrelease/*",
            "credential_profile_reference": "worker-owned-local-uat-bare-repository",
        }
    )

odoo_project = env["project.project"].create(
    {"name": "Phase 5 Human-Approved Push UAT"}
)
odoo_task = env["project.task"].create(
    {
        "name": "Human-approved Push of one reviewed Test branch",
        "project_id": odoo_project.id,
        "op_backend_id": backend.id,
        "op_work_package_id": 990005,
        "op_url": "https://openproject.uat.invalid/work_packages/990005",
    }
)
source = env["dev.work.source.message"].create(
    {
        "provider": "manual",
        "provider_message_id": "phase5-human-push-20260719",
        "message_timestamp": fields.Datetime.now(),
        "text_snapshot": (
            "Add one harmless Test contract, create one separately approved "
            "local commit, then push that exact branch to the registered UAT remote."
        ),
    }
)
work = env["dev.work.item"].create(
    {
        "name": "Add human-approved Push contract test",
        "dev_project_id": project.id,
        "odoo_project_id": odoo_project.id,
        "odoo_task_id": odoo_task.id,
        "op_backend_id": backend.id,
        "op_work_package_id": 990005,
        "op_reference": "UAT WP #990005",
        "op_url": "https://openproject.uat.invalid/work_packages/990005",
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
        "problem_summary": "Reviewed local commits cannot yet be delivered by exact human-approved Push.",
        "original_request_snapshot": "Validate one human-approved normal Push only.",
        "reproduction_context": "Disposable worker-owned UAT repository and local non-production bare remote.",
        "current_behavior": "Workspace stops at committed_reviewed.",
        "expected_behavior": "Human approves one exact branch/commit/remote binding and confirms one Push.",
        "technical_findings": "Remote refs, target, commit, policy, contract, and approver require immutable binding.",
        "affected_components": "tests/__init__.py\ntests/test_human_push_contract.py",
        "risks": "Remote drift, protected target, force mode, or local drift must block Push.",
        "dependencies": "Git and Python 3 standard library.",
        "open_questions": "None.",
        "evidence_references": "uat://phase5-human-push/20260719",
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
        "goal": "Add one Test contract, create one reviewed commit, and Push exactly one branch.",
        "scope": "Two Test files, one local commit, and one normal Push to devhub-uat.",
        "out_of_scope": "PR, merge, deployment, Production, force Push, tags, cleanup, services, and Docker.",
        "proposed_changes": "Create a stdlib unittest for the disposable fixture.",
        "affected_components": "tests/__init__.py\ntests/test_human_push_contract.py",
        "migration_impact": "None.",
        "security_impact": "Immutable exact-state approval and complete remote reconciliation.",
        "test_plan": "python3 -m unittest -v tests.test_human_push_contract; python3 -m unittest discover -s tests -v",
        "rollback_plan": "Preserve local commit and branch; require fresh human review after failure.",
        "dependencies": "Python 3, local Git, and registered local UAT bare remote.",
        "risks": "Any local or remote drift invalidates approval.",
        "acceptance_criteria": "Tests pass; commit reviewed; one branch pushed; remote exact; no PR/merge/deploy.",
    }
)
for sequence, (key, title) in enumerate(
    [
        ("P1", "Inspect controlled fixture"),
        ("P2", "Implement Push contract Test"),
        ("P3", "Run targeted tests"),
        ("P4", "Run regression and verify isolation"),
        ("P5", "Stop for human review"),
    ],
    1,
):
    env["dev.work.plan.step"].create(
        {
            "plan_id": plan.id,
            "step_key": key,
            "sequence": sequence,
            "title": title,
            "description": title,
            "acceptance_evidence": title,
            "assignee_type": "agent",
        }
    )
plan.action_submit_for_approval()
approval = plan.action_approve_exact(
    plan.content_hash,
    comment="Human-approved Push UAT Plan approved exactly",
    policy_version="phase5-human-push-v1",
)
env.cr.commit()
print(
    json.dumps(
        {
            "work_item_id": work.id,
            "plan_id": plan.id,
            "plan_hash": plan.content_hash,
            "approval_id": approval.id,
            "repository_id": repository.id,
            "environment_id": environment.id,
            "remote_id": remote.id,
            "remote_name": remote.name,
            "remote_url": remote.remote_url,
            "base_head": repository.head_cache,
        },
        sort_keys=True,
    )
)
