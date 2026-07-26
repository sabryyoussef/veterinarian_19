"""Create DW-11 and request Merge review; never approve or execute the merge."""
import json
import os

from odoo import fields


APP_ID = int(os.environ["DEVHUB_MERGE_APP_ID"])
INSTALLATION_ID = int(os.environ["DEVHUB_MERGE_INSTALLATION_ID"])
SOURCE_WORKSPACE_ID = int(os.environ.get("PHASE6_SOURCE_WORKSPACE_ID", "14"))
REPOSITORY_NAME = "sabryyoussef/veterinarian_19"

workspace = env["dev.execution.workspace"].browse(SOURCE_WORKSPACE_ID).exists()
if (
    not workspace
    or workspace.state != "pr_created_reviewed"
    or workspace.pr_number != 2
    or workspace.pr_record_id.result_state not in ("created", "reconciled_existing")
    or workspace.pr_record_id.github_repository != REPOSITORY_NAME
):
    raise RuntimeError("Source workspace is not the verified open PR #2 workspace")

repository = workspace.repository_id
pr_target = workspace.pr_record_id.target_id
admin = env.ref("base.user_admin")
user_group = env.ref("dev_session_hub.group_dev_hub_user")
manager_group = env.ref("dev_session_hub.group_dev_hub_manager")

requester = env["res.users"].search(
    [("login", "=", "devhub-merge-requester")], limit=1
)
if not requester:
    requester = env["res.users"].with_context(no_reset_password=True).create(
        {
            "name": "Dev Hub Merge Requester",
            "login": "devhub-merge-requester",
            "email": "devhub-merge-requester@invalid.local",
            "group_ids": [(6, 0, [user_group.id])],
            "company_id": env.company.id,
            "company_ids": [(6, 0, [env.company.id])],
        }
    )
if requester.has_group("dev_session_hub.group_dev_hub_manager"):
    requester.write({"group_ids": [(3, manager_group.id)]})
project = workspace.work_item_id.dev_project_id
if requester not in project.member_ids:
    project.write({"member_ids": [(4, requester.id)]})

target = env["dev.git.merge.target"].search(
    [
        ("repository_id", "=", repository.id),
        ("github_repository", "=", REPOSITORY_NAME),
        ("base_branch", "=", "staging"),
    ],
    limit=1,
)
values = {
    "name": "Veterinarian 19 staging via sabry-uat-merge-agent",
    "repository_id": repository.id,
    "pr_target_id": pr_target.id,
    "github_repository": REPOSITORY_NAME,
    "base_branch": "staging",
    "merge_method": "squash",
    "requester_user_id": requester.id,
    "required_check_name": "GitGuardian Security Checks",
    "required_check_app_id": 46505,
    "credential_profile_reference": (
        "/srv/devhub/credentials/github/merge-gh-profile"
    ),
    "credential_broker_reference": (
        "/srv/devhub/credentials/github/mint-devhub-merge-token"
    ),
    "github_app_slug": "sabry-uat-merge-agent",
    "github_app_id": APP_ID,
    "github_installation_id": INSTALLATION_ID,
    "credential_repository_restriction": REPOSITORY_NAME,
    "credential_permission_summary": (
        "checks:read\ncontents:write\nmetadata:read\n"
        "pull_requests:read\nstatuses:read"
    ),
    "approved": True,
    "non_production": True,
    "active": True,
}
if target:
    target.write(values)
else:
    target = env["dev.git.merge.target"].create(values)

backend = workspace.work_item_id.op_backend_id
source = env["dev.work.source.message"].search(
    [
        ("provider", "=", "manual"),
        ("provider_message_id", "=", "phase6-human-merge-stop-gate-20260719"),
    ],
    limit=1,
)
if not source:
    source = env["dev.work.source.message"].create(
        {
            "provider": "manual",
            "provider_message_id": "phase6-human-merge-stop-gate-20260719",
            "message_timestamp": fields.Datetime.now(),
            "text_snapshot": (
                "Request read-only eligibility review and dedicated approval for PR #2. "
                "Do not perform the irreversible remote merge."
            ),
        }
    )
merge_work = env["dev.work.item"].search(
    [
        ("op_backend_id", "=", backend.id),
        ("op_work_package_id", "=", 990011),
    ],
    limit=1,
)
if not merge_work:
    odoo_project = env["project.project"].create(
        {"name": "Phase 6 Human-Approved Merge Readiness UAT"}
    )
    task = env["project.task"].create(
        {
            "name": "Review PR #2 for a separately approved squash merge",
            "project_id": odoo_project.id,
            "op_backend_id": backend.id,
            "op_work_package_id": 990011,
            "op_url": "https://openproject.uat.invalid/work_packages/990011",
        }
    )
    merge_work = env["dev.work.item"].create(
        {
            "name": "Validate human-approved Merge readiness",
            "dev_project_id": workspace.work_item_id.dev_project_id.id,
            "odoo_project_id": odoo_project.id,
            "odoo_task_id": task.id,
            "op_backend_id": backend.id,
            "op_work_package_id": 990011,
            "op_reference": "DW-11 / UAT WP #990011",
            "op_url": "https://openproject.uat.invalid/work_packages/990011",
            "responsible_user_id": requester.id,
            "preferred_repository_id": repository.id,
            "preferred_environment_id": workspace.environment_id.id,
            "source_message_ids": [(4, source.id)],
        }
    )
workspace._internal_write({"merge_request_work_item_id": merge_work.id})
if not workspace.merge_requested_at:
    workspace.with_user(requester).action_request_merge_review()
env.cr.commit()

print(
    json.dumps(
        {
            "merge_work_item_id": merge_work.id,
            "source_workspace_id": workspace.id,
            "source_work_item_id": workspace.work_item_id.id,
            "pr_number": workspace.pr_number,
            "pr_url": workspace.pr_url_reference,
            "requester_id": requester.id,
            "merge_target_id": target.id,
            "state": workspace.state,
            "merge_requested_at": fields.Datetime.to_string(
                workspace.merge_requested_at
            ),
            "remote_merge_performed": False,
        },
        sort_keys=True,
    )
)
