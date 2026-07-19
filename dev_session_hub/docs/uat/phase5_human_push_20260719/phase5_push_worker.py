"""Bounded worker for the Human-Approved Push UAT; stops at review_required."""

import json
import os
import pathlib
import pwd
import subprocess
import sys

from odoo.addons.dev_session_hub.models.dev_execution import (
    _assert_git_changes_allowlisted,
)


ALLOWED = {"tests/__init__.py", "tests/test_human_push_contract.py"}
TEST_MODULE = """from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TestHumanPushContract(unittest.TestCase):
    def test_fixture_is_test_only(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Isolation UAT Fixture", text)

    def test_delivery_capabilities_are_not_fixture_content(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8").casefold()
        self.assertNotIn("production", text)
        self.assertNotIn("deployment", text)


if __name__ == "__main__":
    unittest.main()
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
worktree = os.path.realpath(workspace.worktree_path)
if git(worktree, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() != workspace.execution_branch:
    raise RuntimeError("Branch mismatch")
if git(worktree, "rev-parse", "HEAD").stdout.strip() != workspace.base_head:
    raise RuntimeError("Base HEAD mismatch")

client = env["dev.client"].search([("name", "=", "Playwright UAT Client")], limit=1)
lease = workspace.start_worker("phase5-human-push-worker", client, seconds=900)


def step(key, status, summary=None):
    target = workspace.plan_id.step_ids.filtered(lambda item: item.step_key == key)
    workspace.worker_update_step(
        lease["lease_token"], lease["lease_version"], target, status, result_summary=summary
    )


step("P1", "in_progress")
if pathlib.Path(worktree, "README.md").read_text(encoding="utf-8").strip() != "# PetSpot Isolation UAT Fixture":
    raise RuntimeError("Unexpected fixture")
step("P1", "done", "Controlled fixture and exact branch validated.")

step("P2", "in_progress")
pathlib.Path(worktree, "tests").mkdir(mode=0o770)
pathlib.Path(worktree, "tests/__init__.py").write_text("", encoding="utf-8")
pathlib.Path(worktree, "tests/test_human_push_contract.py").write_text(
    TEST_MODULE, encoding="utf-8"
)
raw = git(
    worktree,
    "status",
    "--porcelain=v1",
    "-z",
    "--untracked-files=all",
    text=False,
).stdout
normalized = _assert_git_changes_allowlisted(raw, worktree, ALLOWED)
if set(normalized) != ALLOWED:
    raise RuntimeError("Worker change set escaped exact allowlist")
step("P2", "done", "Exactly two allowlisted Test files created.")

def run_tests(args):
    result = subprocess.run(
        [sys.executable, *args],
        cwd=worktree,
        capture_output=True,
        text=True,
        timeout=60,
        env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode:
        raise RuntimeError(result.stderr[-1000:])


step("P3", "in_progress")
run_tests(["-m", "unittest", "-v", "tests.test_human_push_contract"])
step("P3", "done", "Targeted tests passed 2/2.")
step("P4", "in_progress")
run_tests(["-m", "unittest", "discover", "-s", "tests", "-v"])
if workspace._main_snapshot(workspace.repository_id) != {
    "branch": workspace.main_branch_before,
    "head": workspace.main_head_before,
    "dirty": workspace.main_dirty_summary_before,
    "digest": workspace.main_dirty_digest_before,
}:
    raise RuntimeError("Main worktree changed")
step("P4", "done", "Regression passed 2/2; main worktree unchanged.")
step("P5", "in_progress")
step("P5", "done", "Ready for human commit review, then Push review.")
handoff = (
    "Work Item: %s\nWorkspace: %s\nBranch: %s\nHEAD: %s\n"
    "Files: tests/__init__.py, tests/test_human_push_contract.py\n"
    "Tests: targeted 2/2; regression 2/2\nPlan: P1-P5 complete\n"
    "Next: human-approved commit, then separately approved Push.\n"
    "PR/Merge/Deployment/Production: none."
    % (workspace.work_item_id.id, workspace.id, workspace.execution_branch, workspace.base_head)
)
workspace.worker_mark_review_required(
    lease["lease_token"],
    lease["lease_version"],
    handoff,
    {
        "run": 4,
        "passed": 4,
        "failed": 0,
        "errors": 0,
        "command": "targeted-push-contract; push-contract-regression",
        "evidence": "phase5-human-push://worker-tests",
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
            "tests": "4/4",
        },
        sort_keys=True,
    )
)
