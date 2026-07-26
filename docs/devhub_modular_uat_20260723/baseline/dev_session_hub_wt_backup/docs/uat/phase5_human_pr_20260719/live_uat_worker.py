"""Run the bounded PR UAT worker and stop at review_required."""

import json
import os
import pathlib
import pwd
import subprocess

from odoo.addons.dev_session_hub.models.dev_execution import (
    _assert_git_changes_allowlisted,
)


RELATIVE_PATH = (
    "dev_session_hub/docs/uat/phase5_human_pr_20260719/UAT_LIVE_MARKER.md"
)
MARKER = """# Human-Approved PR Live UAT Marker

This test-only documentation marker validates one reviewed commit, one exact
non-force Push, and one human-approved open Pull Request to `staging`.

It authorizes no merge, auto-merge, deployment, Production access, branch
deletion, or worktree cleanup.
"""


def git(worktree, *args, text=True):
    return subprocess.run(
        ["git", "-c", "safe.directory=%s" % worktree, "-C", worktree, *args],
        check=True,
        capture_output=True,
        text=text,
        timeout=30,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": "/nonexistent",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
        },
    )


workspace = env["dev.execution.workspace"].browse(
    int(os.environ["PHASE5_WORKSPACE_ID"])
).exists()
expected = {
    "plan_id": int(os.environ["PHASE5_PLAN_ID"]),
    "plan_hash": os.environ["PHASE5_PLAN_HASH"],
    "policy_hash": os.environ["PHASE5_POLICY_HASH"],
    "contract_hash": os.environ["PHASE5_CONTRACT_HASH"],
}
actual = {
    "plan_id": workspace.plan_id.id,
    "plan_hash": workspace.approved_plan_hash,
    "policy_hash": workspace.policy_hash,
    "contract_hash": workspace.execution_contract_hash,
}
if expected != actual:
    raise RuntimeError("Controlled execution references do not match")
if pwd.getpwuid(os.geteuid()).pw_name != "devworker":
    raise RuntimeError("Unexpected worker identity")
if workspace.state != "ready":
    raise RuntimeError("Workspace is not ready for bounded implementation")

worktree = os.path.realpath(workspace.worktree_path)
if (
    git(worktree, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    != workspace.execution_branch
):
    raise RuntimeError("Branch mismatch")
if git(worktree, "rev-parse", "HEAD").stdout.strip() != workspace.base_head:
    raise RuntimeError("Base HEAD mismatch")

client = env["dev.client"].search(
    [("name", "=", "Playwright UAT Client")], limit=1
)
lease = workspace.start_worker("phase5-human-pr-live-worker", client, seconds=900)


def step(key, status, summary=None):
    target = workspace.plan_id.step_ids.filtered(lambda item: item.step_key == key)
    workspace.worker_update_step(
        lease["lease_token"],
        lease["lease_version"],
        target,
        status,
        result_summary=summary,
    )


step("P1", "in_progress")
if git(worktree, "status", "--porcelain").stdout:
    raise RuntimeError("Initial UAT worktree is not clean")
step("P1", "done", "Clean dedicated branch and exact staging base verified.")

step("P2", "in_progress")
path = pathlib.Path(worktree, RELATIVE_PATH)
path.parent.mkdir(parents=True, exist_ok=True)
if path.exists():
    raise RuntimeError("Live UAT marker already exists")
path.write_text(MARKER, encoding="utf-8")
raw = git(
    worktree,
    "status",
    "--porcelain=v1",
    "-z",
    "--untracked-files=all",
    text=False,
).stdout
normalized = _assert_git_changes_allowlisted(raw, worktree, {RELATIVE_PATH})
if normalized != [RELATIVE_PATH]:
    raise RuntimeError("Worker change set escaped the exact allowlist")
step("P2", "done", "Exactly one allowlisted sanitized documentation marker created.")

step("P3", "in_progress")
if path.read_text(encoding="utf-8") != MARKER:
    raise RuntimeError("UAT marker content mismatch")
if any(
    forbidden in MARKER.casefold()
    for forbidden in ("access_token=", "authorization:", "private key")
):
    raise RuntimeError("Credential-like content detected")
step("P3", "done", "Marker content and credential-safety checks passed 2/2.")

step("P4", "in_progress")
main = workspace._main_snapshot(workspace.repository_id)
expected_main = {
    "branch": workspace.main_branch_before,
    "head": workspace.main_head_before,
    "dirty": workspace.main_dirty_summary_before,
    "digest": workspace.main_dirty_digest_before,
}
if main != expected_main:
    raise RuntimeError("Protected main worktree changed")
step("P4", "done", "Protected main worktree remains unchanged and clean.")

step("P5", "in_progress")
step("P5", "done", "Ready for separate human Commit, Push, and PR approvals.")
handoff = (
    "Work Item: %s\nWorkspace: %s\nBranch: %s\nHEAD: %s\n"
    "Changed file: %s\nTests: marker and credential-safety 2/2\n"
    "Target: sabryyoussef/veterinarian_19:staging\n"
    "Next: separate human Commit, Push, and PR approvals.\n"
    "Merge/Auto-merge/Deployment/Production: none."
    % (
        workspace.work_item_id.id,
        workspace.id,
        workspace.execution_branch,
        workspace.base_head,
        RELATIVE_PATH,
    )
)
workspace.worker_mark_review_required(
    lease["lease_token"],
    lease["lease_version"],
    handoff,
    {
        "run": 2,
        "passed": 2,
        "failed": 0,
        "errors": 0,
        "command": "live-pr-uat-marker-and-credential-safety",
        "evidence": "phase5-human-pr://live-worker-tests",
    },
)
env.cr.commit()
print(
    json.dumps(
        {
            "workspace_id": workspace.id,
            "state": workspace.state,
            "branch": workspace.execution_branch,
            "normalized_paths": normalized,
            "tests": "2/2",
        },
        sort_keys=True,
    )
)
