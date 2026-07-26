"""Create one new GitHub-backed Human-Approved PR UAT workspace."""

import json

from odoo import fields


project = env["dev.project"].search([("code", "=", "PETSPOT-UAT")], limit=1)
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
if not project or not environment or not backend:
    raise RuntimeError("Validated non-production UAT registry is incomplete")

repository = env["dev.repository"].search(
    [
        ("project_id", "=", project.id),
        ("working_directory", "=", "/srv/devhub-pr-uat/manual/veterinarian_19"),
    ],
    limit=1,
)
if not repository:
    repository = env["dev.repository"].create(
        {
            "name": "Veterinarian 19 GitHub PR UAT",
            "project_id": project.id,
            "git_remote": "github:sabryyoussef/veterinarian_19",
            "canonical_remote_path": "/srv/devhub-pr-uat/manual/veterinarian_19",
            "working_directory": "/srv/devhub-pr-uat/manual/veterinarian_19",
            "default_branch": "staging",
            "repository_role": "primary",
            "current_branch_cache": "staging",
            "head_cache": "66344b2e09e2049c39942114029253e919bc6709",
            "dirty_state_summary": "clean",
            "last_git_snapshot_at": fields.Datetime.now(),
            "execution_classification": "safe_for_isolated_worktree",
            "agent_execution_allowed": True,
            "worker_git_common_dir": "/srv/devhub-pr-uat/repos/veterinarian_19.git",
            "worker_worktree_root": "/srv/devhub-pr-uat/worktrees-veterinarian",
            "worker_identity": "devworker",
            "production_runtime_coupled": False,
            "test_runtime_coupled": False,
            "execution_audit_summary": "Dedicated GitHub-backed Test repository; protected main worktree.",
            "execution_audited_at": fields.Datetime.now(),
        }
    )

remote = env["dev.git.remote"].search(
    [("repository_id", "=", repository.id), ("name", "=", "devhub-github")],
    limit=1,
)
if not remote:
    remote = env["dev.git.remote"].create(
        {
            "name": "devhub-github",
            "repository_id": repository.id,
            "remote_url": "git@github.com:sabryyoussef/veterinarian_19.git",
            "protocol": "ssh",
            "approved": True,
            "non_production": True,
            "allowed_branch_prefix": "devhub/",
            "protected_branch_patterns": "main\nmaster\nproduction\nrelease/*",
            "allowed_ssh_user": "git",
            "credential_profile_reference": (
                "/srv/devhub/credentials/github/push_ssh_config"
            ),
        }
    )

target = env["dev.git.pr.target"].search(
    [
        ("repository_id", "=", repository.id),
        ("source_remote_id", "=", remote.id),
        ("github_repository", "=", "sabryyoussef/veterinarian_19"),
        ("target_branch", "=", "staging"),
    ],
    limit=1,
)
if not target:
    target = env["dev.git.pr.target"].create(
        {
            "name": "Veterinarian 19 staging via sabry-uat-agent",
            "repository_id": repository.id,
            "source_remote_id": remote.id,
            "target_repository_id": repository.id,
            "github_repository": "sabryyoussef/veterinarian_19",
            "target_branch": "staging",
            "allowed_target_branches": "staging",
            "credential_profile_reference": (
                "/srv/devhub/credentials/github/gh-profile"
            ),
            "credential_broker_reference": (
                "/srv/devhub/credentials/github/mint-devhub-pr-token"
            ),
            "credential_type": "github_app",
            "github_app_slug": "sabry-uat-agent",
            "github_app_id": 4340040,
            "github_installation_id": 147639376,
            "credential_owner_reference": "github-app:sabry-uat-agent",
            "credential_repository_restriction": (
                "sabryyoussef/veterinarian_19"
            ),
            "credential_permission_summary": (
                "contents:read\nmetadata:read\npull_requests:write"
            ),
            "approved": True,
            "non_production": True,
            "active": True,
        }
    )

source_key = "phase5-human-pr-live-20260719"
if env["dev.work.source.message"].search(
    [("provider", "=", "manual"), ("provider_message_id", "=", source_key)]
):
    raise RuntimeError("Live Human-Approved PR UAT fixture already exists")

odoo_project = env["project.project"].create(
    {"name": "Phase 5 Human-Approved PR Live UAT"}
)
task = env["project.task"].create(
    {
        "name": "Create one reviewed PR to staging",
        "project_id": odoo_project.id,
        "op_backend_id": backend.id,
        "op_work_package_id": 990008,
        "op_url": "https://openproject.uat.invalid/work_packages/990008",
    }
)
source = env["dev.work.source.message"].create(
    {
        "provider": "manual",
        "provider_message_id": source_key,
        "message_timestamp": fields.Datetime.now(),
        "text_snapshot": (
            "Test-only marker: human-approved commit, exact Push, and one open PR "
            "to the non-production staging branch."
        ),
    }
)
work = env["dev.work.item"].create(
    {
        "name": "Validate human-approved PR creation",
        "dev_project_id": project.id,
        "odoo_project_id": odoo_project.id,
        "odoo_task_id": task.id,
        "op_backend_id": backend.id,
        "op_work_package_id": 990008,
        "op_reference": "UAT WP #990008",
        "op_url": "https://openproject.uat.invalid/work_packages/990008",
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
        "problem_summary": "Validate one controlled PR with a scoped GitHub App.",
        "original_request_snapshot": "Create exactly one reviewed UAT PR to staging.",
        "reproduction_context": "Dedicated GitHub-backed isolated Test worktree.",
        "current_behavior": "PR controls pass automated tests.",
        "expected_behavior": "One open, unmerged PR; no auto-merge or deployment.",
        "technical_findings": "Scoped App and separate repository deploy key are available.",
        "affected_components": (
            "dev_session_hub/docs/uat/phase5_human_pr_20260719/UAT_LIVE_MARKER.md"
        ),
        "risks": "Credential, branch, SHA, title, or body drift must fail closed.",
        "dependencies": "GitHub App, repository deploy key, Git, and GitHub API.",
        "open_questions": "None.",
        "evidence_references": "uat://phase5-human-pr/20260719/live",
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
        "goal": "Add one harmless UAT marker and create one reviewed PR to staging.",
        "scope": "One documentation marker, one commit, one Push, and one PR.",
        "out_of_scope": "Merge, auto-merge, deployment, Production, deletion, cleanup.",
        "proposed_changes": "Add a sanitized UAT marker under Dev Hub evidence.",
        "affected_components": (
            "dev_session_hub/docs/uat/phase5_human_pr_20260719/UAT_LIVE_MARKER.md"
        ),
        "migration_impact": "None.",
        "security_impact": "Least-privileged App, exact approval bindings, no secret storage.",
        "test_plan": "Verify exact marker content and clean bounded change set.",
        "rollback_plan": "Leave branch and PR open for human review; do not merge.",
        "dependencies": "Registered SSH remote and repository-only GitHub App.",
        "risks": "Any remote or approval drift blocks delivery.",
        "acceptance_criteria": "One open PR to staging; no duplicate, merge, or deployment.",
    }
)
for sequence, key in enumerate(("P1", "P2", "P3", "P4", "P5"), 1):
    env["dev.work.plan.step"].create(
        {
            "plan_id": plan.id,
            "step_key": key,
            "sequence": sequence,
            "title": "PR UAT %s" % key,
            "description": "Bounded Human-Approved PR UAT step %s." % key,
            "acceptance_evidence": "Step %s completed." % key,
            "assignee_type": "agent",
        }
    )
plan.action_submit_for_approval()
plan_approval = plan.action_approve_exact(
    plan.content_hash,
    comment="Human-Approved PR live UAT Plan approved exactly",
    policy_version="phase5-human-pr-v1",
)
workspace = env["dev.execution.workspace"].create_proposal(work)
workspace.action_confirm_prepare()
workspace._internal_write({"pr_target_id": target.id})
env.cr.commit()
print(
    json.dumps(
        {
            "work_item_id": work.id,
            "workspace_id": workspace.id,
            "plan_id": plan.id,
            "plan_hash": plan.content_hash,
            "plan_approval_id": plan_approval.id,
            "policy_hash": workspace.policy_hash,
            "contract_hash": workspace.execution_contract_hash,
            "repository_id": repository.id,
            "remote_id": remote.id,
            "pr_target_id": target.id,
            "branch": workspace.execution_branch,
            "base_head": workspace.base_head,
            "state": workspace.state,
        },
        sort_keys=True,
    )
)
