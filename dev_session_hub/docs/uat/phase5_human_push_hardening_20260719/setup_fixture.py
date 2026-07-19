"""Create DW-8 success and DW-9 controlled-failure Push hardening fixtures."""

import json

from odoo import fields
from odoo.exceptions import ValidationError


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
remote = env["dev.git.remote"].search(
    [("repository_id", "=", repository.id), ("name", "=", "devhub-uat")], limit=1
)
if not project or not repository or not environment or not backend or not remote:
    raise RuntimeError("Validated hardening UAT registry is incomplete")
remote.assert_push_allowed("devhub/DW-8-hardening-validation")

denied_urls = [
    "https://user@github.com/org/repo.git",
    "https://user:password@github.com/org/repo.git",
    "https://github.com/org/repo.git?access_token=SECRET",
    "https://github.com/org/repo.git#credential",
]
for index, denied_url in enumerate(denied_urls):
    try:
        with env.cr.savepoint():
            env["dev.git.remote"].create(
                {
                    "name": "hardening-denied-%s" % index,
                    "repository_id": repository.id,
                    "remote_url": denied_url,
                    "protocol": "https",
                    "approved": True,
                }
            )
    except ValidationError:
        continue
    raise RuntimeError("Credential-bearing remote URL was persisted")


def create_pilot(label, wp_id):
    source_key = "phase5-human-push-hardening-%s-20260719" % label
    if env["dev.work.source.message"].search(
        [("provider", "=", "manual"), ("provider_message_id", "=", source_key)]
    ):
        raise RuntimeError("Hardening UAT fixture already exists: %s" % label)
    odoo_project = env["project.project"].create(
        {"name": "Push Hardening UAT %s" % label.title()}
    )
    task = env["project.task"].create(
        {
            "name": "Human-approved Push hardening %s" % label,
            "project_id": odoo_project.id,
            "op_backend_id": backend.id,
            "op_work_package_id": wp_id,
            "op_url": "https://openproject.uat.invalid/work_packages/%s" % wp_id,
        }
    )
    source = env["dev.work.source.message"].create(
        {
            "provider": "manual",
            "provider_message_id": source_key,
            "message_timestamp": fields.Datetime.now(),
            "text_snapshot": "Test-only Push hardening %s pilot." % label,
        }
    )
    work = env["dev.work.item"].create(
        {
            "name": "Validate Push hardening %s path" % label,
            "dev_project_id": project.id,
            "odoo_project_id": odoo_project.id,
            "odoo_task_id": task.id,
            "op_backend_id": backend.id,
            "op_work_package_id": wp_id,
            "op_reference": "UAT WP #%s" % wp_id,
            "op_url": "https://openproject.uat.invalid/work_packages/%s" % wp_id,
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
            "problem_summary": "Harden credential, force, and failed-Push controls.",
            "original_request_snapshot": "Validate the bounded Push hardening sprint.",
            "reproduction_context": "Disposable local bare non-production remote.",
            "current_behavior": "Functional Push UAT passed before hardening.",
            "expected_behavior": "Exact normal Push or explicit reconciled failure state.",
            "technical_findings": "Structured URLs, canonical Push args, and ref digest evidence.",
            "affected_components": "tests/__init__.py\ntests/test_human_push_contract.py",
            "risks": "Credential leak, force syntax, or ambiguous failed delivery.",
            "dependencies": "Git and Python standard library.",
            "open_questions": "None.",
            "evidence_references": "uat://phase5-human-push-hardening/%s" % label,
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
            "goal": "Validate one bounded Push hardening %s path." % label,
            "scope": "Two Test files; human commit and Push gates; non-production only.",
            "out_of_scope": "PR, merge, deployment, Production, force Push, tags, cleanup.",
            "proposed_changes": "Add the existing harmless Push Test contract.",
            "affected_components": "tests/__init__.py\ntests/test_human_push_contract.py",
            "migration_impact": "None.",
            "security_impact": "Credential-free URL and explicit reconciliation state.",
            "test_plan": "python3 -m unittest -v tests.test_human_push_contract",
            "rollback_plan": "Retain branch and require human review.",
            "dependencies": "Python, Git, registered devhub-uat remote.",
            "risks": "Any local or remote drift blocks delivery.",
            "acceptance_criteria": "Exact success or explicit failed reconciliation; no retry.",
        }
    )
    for sequence, key in enumerate(("P1", "P2", "P3", "P4", "P5"), 1):
        env["dev.work.plan.step"].create(
            {
                "plan_id": plan.id,
                "step_key": key,
                "sequence": sequence,
                "title": "Hardening %s" % key,
                "description": "Bounded hardening step %s" % key,
                "acceptance_evidence": "Step %s completed" % key,
                "assignee_type": "agent",
            }
        )
    plan.action_submit_for_approval()
    approval = plan.action_approve_exact(
        plan.content_hash,
        comment="Push hardening %s UAT Plan approved exactly" % label,
        policy_version="phase5-human-push-hardening-v1",
    )
    workspace = env["dev.execution.workspace"].create_proposal(work)
    workspace.action_confirm_prepare()
    return {
        "work_item_id": work.id,
        "workspace_id": workspace.id,
        "plan_id": plan.id,
        "plan_hash": plan.content_hash,
        "approval_id": approval.id,
        "policy_hash": workspace.policy_hash,
        "contract_hash": workspace.execution_contract_hash,
        "branch": workspace.execution_branch,
    }


result = {
    "success": create_pilot("success", 990006),
    "failure": create_pilot("failure", 990007),
}
env.cr.commit()
print(json.dumps(result, sort_keys=True))
