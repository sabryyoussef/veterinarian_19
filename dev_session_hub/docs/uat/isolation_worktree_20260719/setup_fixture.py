"""Disposable non-production fixture for the isolated-worktree UAT.

Run only through ``odoo-bin shell`` in database ``devhub_isolation_uat``.
The script contains no credentials and refuses to replace an existing fixture.
"""

import json

from odoo import fields


admin = env.ref("base.user_admin")
admin.write({"password": "admin"})

if env["dev.project"].search([("code", "=", "PETSPOT-UAT")]):
    raise RuntimeError("Disposable UAT fixture already exists; refusing replacement")

machine = env["dev.machine"].create(
    {
        "name": "Precision 5540 Isolated UAT",
        "stable_uuid": "uat-precision-5540-20260719",
        "hostname": "sabry3-Precision-5540",
        "tailscale_name": "sabry3-precision-5540.tailcf9988.ts.net",
        "tailscale_ip_reference": "100.110.211.53",
        "tailscale_destination_verified": True,
        "tailscale_verified_at": fields.Datetime.now(),
        "pinned_host_key_fingerprint": (
            "SHA256:Uq8IW8zlSdAPxWkd7MF+eJwuvjQmUSyvJQBw6oNrtyU"
        ),
        "ssh_alias": "sabry3-precision-5540-ts",
        "os_name": "Ubuntu 24.04 LTS",
        "architecture": "x86_64",
        "role": "Disposable isolated Dev Hub UAT only",
        "trust_zone": "trusted_dev",
        "production": False,
        "allowed_path_prefixes": "/srv/devhub-uat/worktrees",
    }
)
project = env["dev.project"].create(
    {
        "name": "PetSpot Isolation UAT",
        "code": "PETSPOT-UAT",
        "owner_id": admin.id,
        "member_ids": [(4, admin.id)],
        "production_policy": "Production denied; disposable UAT fixture only.",
        "agent_instruction_summary": (
            "Validate isolation only. No production, deployment, Docker, commit, "
            "push, merge, or external communication."
        ),
    }
)
repository = env["dev.repository"].create(
    {
        "name": "PetSpot Worker-owned UAT Fixture",
        "project_id": project.id,
        "git_remote": "file:///srv/devhub-uat/repos/petspot-uat.git",
        "canonical_remote_path": "/srv/devhub-uat/manual/petspot-uat",
        "working_directory": "/srv/devhub-uat/manual/petspot-uat",
        "default_branch": "main",
        "repository_role": "primary",
        "current_branch_cache": "main",
        "head_cache": "5a7f1e1404dbbc1efeacc1a1bcaea3021d7cd7ae",
        "last_git_snapshot_at": fields.Datetime.now(),
        "execution_classification": "safe_for_isolated_worktree",
        "agent_execution_allowed": True,
        "worker_git_common_dir": "/srv/devhub-uat/repos/petspot-uat.git",
        "worker_worktree_root": "/srv/devhub-uat/worktrees",
        "worker_identity": "devworker",
        "production_runtime_coupled": False,
        "test_runtime_coupled": False,
        "execution_audit_summary": (
            "Disposable worker-owned UAT fixture; no runtime service or production "
            "path coupling."
        ),
        "execution_audited_at": fields.Datetime.now(),
    }
)
environment = env["dev.environment"].create(
    {
        "name": "Isolation UAT Test",
        "project_id": project.id,
        "environment_type": "test",
        "machine_id": machine.id,
        "odoo_version": "19.0 Enterprise UAT fixture",
        "database_identifier": "devhub_isolation_uat",
        "url": "http://127.0.0.1:18040",
        "port": 18040,
        "config_reference": "/srv/devhub-uat/config/odoo.conf",
        "service_container_reference": "disposable-process-only",
        "data_sensitivity": "internal_test",
        "production_guard_policy": (
            "Production, deployment, Docker, service restart, commit, push, and "
            "merge denied."
        ),
    }
)
project.write(
    {
        "default_repository_id": repository.id,
        "default_environment_id": environment.id,
    }
)
policy = env["dev.policy"].create(
    {
        "name": "Isolation UAT Exact Policy",
        "project_id": project.id,
        "environment_id": environment.id,
        "production_access_policy": "denied",
        "allowed_operations": (
            "Prepare exact worker branch/worktree; validate; manual marker; tests; "
            "pause; resume; review; release."
        ),
        "required_confirmation": True,
        "branch_rules": (
            "Only generated devhub/DW-* branch. No commit, push, merge, reset, "
            "clean, checkout, stash, or delete."
        ),
        "development_allowed": True,
        "agent_write_permission": True,
        "test_permission": True,
        "deploy_permission": False,
        "launch_allowed": True,
        "active": True,
    }
)
client = env["dev.client"].create(
    {
        "name": "Playwright UAT Client",
        "user_name": "uat",
        "os_name": "Linux Chromium",
        "architecture": "x86_64",
        "cursor_version": "UAT target resolution only",
        "baseline_revision": "isolation-uat-20260719",
        "compliance_status": "compliant",
        "compliance_note": "Disposable UI client; no autonomous worker launched.",
    }
)
backend = env["openproject.backend"].create(
    {
        "name": "Isolation UAT Dummy Backend",
        "api_url": "http://127.0.0.1:9",
        "public_url": "https://openproject.uat.invalid",
        "verify_ssl": True,
        "enable_pull": False,
        "enable_push": False,
    }
)
odoo_project = env["project.project"].create(
    {"name": "PetSpot Isolation UAT Odoo Project"}
)
odoo_task = env["project.task"].create(
    {
        "name": "Isolation UAT: dedicated branch and worktree",
        "project_id": odoo_project.id,
        "op_backend_id": backend.id,
        "op_work_package_id": 990001,
        "op_url": "https://openproject.uat.invalid/work_packages/990001",
    }
)
source = env["dev.work.source.message"].create(
    {
        "provider": "manual",
        "provider_message_id": "isolation-uat-20260719",
        "message_timestamp": fields.Datetime.now(),
        "text_snapshot": (
            "Validate dedicated branch, physical worker worktree, exact plan, "
            "policy binding, pause/resume, fencing, and human cleanup gates."
        ),
    }
)
work = env["dev.work.item"].create(
    {
        "name": "Isolation UAT: verify dedicated branch and worktree",
        "dev_project_id": project.id,
        "odoo_project_id": odoo_project.id,
        "odoo_task_id": odoo_task.id,
        "op_backend_id": backend.id,
        "op_work_package_id": 990001,
        "op_reference": "UAT WP #990001",
        "op_url": "https://openproject.uat.invalid/work_packages/990001",
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
            "Prove independent physical worktrees and fail-closed execution context."
        ),
        "original_request_snapshot": "Validate isolation architecture only.",
        "reproduction_context": (
            "Disposable non-production fixture on Precision 5540."
        ),
        "current_behavior": (
            "Architecture is implemented but lacks physical end-to-end UAT evidence."
        ),
        "expected_behavior": (
            "A worker-owned task worktree remains independent from the manual "
            "fixture worktree."
        ),
        "technical_findings": (
            "Exact plan, policy, path, lease, checkpoint, resume, review, and "
            "cleanup controls require UI and filesystem proof."
        ),
        "affected_components": "dev_session_hub execution workspace UAT fixture",
        "risks": "False pass could expose a shared or production-coupled path.",
        "dependencies": (
            "Disposable Git repository, restricted devworker, PostgreSQL UAT "
            "database, Playwright."
        ),
        "open_questions": "None.",
        "evidence_references": "uat://isolation-worktree/20260719",
        "origin": "manual",
        "repository_id": repository.id,
        "observed_head": repository.head_cache,
    }
)
analysis.action_accept()
work.action_start_planning()

plan_values = {
    "work_item_id": work.id,
    "analysis_id": analysis.id,
    "status": "draft",
    "origin": "manual",
    "goal": "Revision 1: prove isolated workspace lifecycle.",
    "scope": "Disposable fixture repository and Dev Hub UI only.",
    "out_of_scope": (
        "Production, autonomous coding, commit, push, merge, PR, deployment, "
        "restart, Docker, external communication."
    ),
    "proposed_changes": (
        "Create a harmless untracked UAT marker in the isolated worktree only."
    ),
    "affected_components": "dev_session_hub UAT fixture",
    "migration_impact": "None; disposable database.",
    "security_impact": (
        "Tests restricted identity, exact hashes, path boundaries, and fenced "
        "concurrency."
    ),
    "test_plan": (
        "Playwright UI assertions plus backend, Git, ownership, and filesystem "
        "verification."
    ),
    "rollback_plan": (
        "Preserve dirty worktree for audit; remove only after separate human "
        "approval; drop disposable database last."
    ),
    "dependencies": (
        "Restricted devworker, worker-owned bare repository, non-production "
        "machine, Playwright."
    ),
    "risks": (
        "Incorrect ownership, path escape, shared worktree mutation, stale "
        "contract, or accidental Git side effect."
    ),
    "acceptance_criteria": (
        "All screenshots and assertions pass; main snapshot unchanged; marker "
        "isolated; negative tests fail closed."
    ),
}
plan_v1 = env["dev.work.plan"].create(plan_values)
for sequence, (key, title) in enumerate(
    [
        ("P1", "Validate isolation boundaries"),
        ("P2", "Create harmless fixture marker"),
        ("P3", "Prove main-worktree invariants"),
        ("P4", "Prove lifecycle fencing"),
        ("P5", "Human review and release"),
    ],
    1,
):
    env["dev.work.plan.step"].create(
        {
            "plan_id": plan_v1.id,
            "step_key": key,
            "sequence": sequence,
            "title": title,
            "description": title + " without production access.",
        }
    )

plan_v2 = plan_v1.action_new_revision()
plan_v2.write(
    {
        "goal": (
            "Revision 2: prove exact approved isolated workspace lifecycle and "
            "negative gates."
        )
    }
)
plan_v2.action_submit_for_approval()
approval = plan_v2.action_approve_exact(
    plan_v2.content_hash,
    comment="UAT revision 2 exact hash approved",
    policy_version="isolation-uat-v1",
)
env.cr.commit()

print(
    json.dumps(
        {
            "project_id": project.id,
            "repository_id": repository.id,
            "environment_id": environment.id,
            "machine_id": machine.id,
            "policy_id": policy.id,
            "client_id": client.id,
            "work_item_id": work.id,
            "work_uuid": work.uuid,
            "analysis_id": analysis.id,
            "plan_v1_id": plan_v1.id,
            "plan_v2_id": plan_v2.id,
            "plan_hash": plan_v2.content_hash,
            "approval_id": approval.id,
            "base_head": repository.head_cache,
        },
        sort_keys=True,
    )
)
