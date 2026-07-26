"""One-process bounded worker for the Human-Approved Commit UAT."""

import json
import os
import pathlib
import pwd
import re
import subprocess
import sys
import time

from odoo.addons.dev_session_hub.models.dev_execution import (
    _assert_git_changes_allowlisted,
)
from odoo.exceptions import AccessError


ALLOWED = {"tests/__init__.py", "tests/test_human_commit_contract.py"}
TEST_MODULE = """from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TestHumanCommitContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_fixture_heading_is_stable(self):
        self.assertIn("# PetSpot Isolation UAT Fixture", self.readme)

    def test_fixture_remains_non_production(self):
        self.assertIn("Isolation UAT Fixture", self.readme)
        self.assertNotIn("production", self.readme.casefold())


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
    "repository_id": int(os.environ["PHASE5_REPOSITORY_ID"]),
    "environment_id": int(os.environ["PHASE5_ENVIRONMENT_ID"]),
}
actual = {
    "plan_id": workspace.plan_id.id,
    "plan_hash": workspace.approved_plan_hash,
    "policy_hash": workspace.policy_hash,
    "contract_hash": workspace.execution_contract_hash,
    "repository_id": workspace.repository_id.id,
    "environment_id": workspace.environment_id.id,
}
if expected != actual:
    raise RuntimeError("Controlled execution references do not match")
if os.geteuid() != 1001 or pwd.getpwuid(os.geteuid()).pw_name != "devworker":
    raise RuntimeError("Unexpected worker identity")
if subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode == 0:
    raise RuntimeError("Worker unexpectedly has sudo")
if os.access("/var/run/docker.sock", os.R_OK | os.W_OK):
    raise RuntimeError("Worker unexpectedly has Docker access")
if os.access("/home/sabry", os.R_OK):
    raise RuntimeError("Worker unexpectedly has Sabry home access")
worktree = os.path.realpath(workspace.worktree_path)
root = os.path.realpath(workspace.repository_id.worker_worktree_root)
if os.path.commonpath((root, worktree)) != root:
    raise RuntimeError("Worktree escaped the registered root")
os.chdir(worktree)
if git(worktree, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() != (
    workspace.execution_branch
):
    raise RuntimeError("Branch mismatch")
if git(worktree, "rev-parse", "HEAD").stdout.strip() != workspace.base_head:
    raise RuntimeError("Base HEAD mismatch")

client = env["dev.client"].search([("name", "=", "Playwright UAT Client")], limit=1)
lease = workspace.start_worker("phase5-human-commit-worker", client, seconds=900)


def token():
    return lease["lease_token"], lease["lease_version"]


def plan_step(key):
    result = workspace.plan_id.step_ids.filtered(lambda item: item.step_key == key)
    if len(result) != 1:
        raise RuntimeError("Approved Plan step is missing")
    return result


def transition(key, status, summary=None):
    workspace.worker_update_step(
        *token(), plan_step(key), status, result_summary=summary
    )


def checkpoint(summary, test_result=None):
    workspace.worker_checkpoint(*token(), summary, test_result=test_result)


def tests(reference, args):
    workspace._assert_worker_execution(*token())
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, *args],
        cwd=worktree,
        capture_output=True,
        text=True,
        timeout=60,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": "/nonexistent",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )
    workspace._assert_worker_execution(*token())
    if result.returncode:
        raise RuntimeError("%s failed: %s" % (reference, result.stderr[-1000:]))
    matched = re.search(r"Ran (\d+) test", result.stderr)
    count = int(matched.group(1)) if matched else 0
    return {
        "run": count,
        "passed": count,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "duration": round(time.monotonic() - started, 3),
        "command": reference,
        "evidence": "phase5-human-commit://%s" % reference,
        "summary": "%s passed (%s tests)." % (reference, count),
    }


transition("P1", "in_progress")
workspace._assert_worker_execution(*token())
if pathlib.Path("README.md").read_text(encoding="utf-8").strip() != (
    "# PetSpot Isolation UAT Fixture"
):
    raise RuntimeError("Unexpected fixture README")
transition("P1", "done", "Controlled references and fixture validated.")
checkpoint("P1 inspection complete.")

transition("P2", "in_progress")
pathlib.Path("tests").mkdir(mode=0o770)
pathlib.Path("tests/__init__.py").write_text("", encoding="utf-8")
pathlib.Path("tests/test_human_commit_contract.py").write_text(
    TEST_MODULE, encoding="utf-8"
)
workspace._assert_worker_execution(*token())
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
    raise RuntimeError("Normalized files differ from exact allowlist")
transition("P2", "done", "Exactly two allowlisted Test files created.")
checkpoint("P2 implementation and scope validation complete.")

transition("P3", "in_progress")
targeted = tests(
    "targeted-human-commit-contract",
    ["-m", "unittest", "-v", "tests.test_human_commit_contract"],
)
if targeted["passed"] != 2:
    raise RuntimeError("Targeted test count mismatch")
transition("P3", "done", "Targeted tests passed 2/2.")
checkpoint("P3 targeted tests complete.", targeted)

transition("P4", "in_progress")
pause_checkpoint = workspace.worker_pause(
    *token(), "P4 controlled Pause before resume.", test_result=targeted
)
expected_dirty = workspace.dirty_digest
lease = workspace.worker_resume(
    "phase5-human-commit-worker", client, expected_dirty, seconds=900
)
rejected = False
try:
    workspace.acquire_lease("phase5-human-commit-second-writer", client, seconds=60)
except AccessError:
    rejected = True
if not rejected:
    raise RuntimeError("Concurrent writer acquired workspace")
workspace.assert_lease(*token())
workspace._event(
    "concurrent_writer_rejected",
    "Second human-commit UAT writer denied",
    {"authoritative_version": lease["lease_version"]},
)
transition("P4", "done", "Pause/Resume passed and second writer rejected.")
checkpoint("P4 Pause/Resume and fencing complete.")

transition("P5", "in_progress")
regression = tests(
    "human-commit-regression-discovery",
    ["-m", "unittest", "discover", "-s", "tests", "-v"],
)
if regression["passed"] != 2:
    raise RuntimeError("Regression test count mismatch")
main = workspace._main_snapshot(workspace.repository_id)
expected_main = {
    "branch": workspace.main_branch_before,
    "head": workspace.main_head_before,
    "dirty": workspace.main_dirty_summary_before,
    "digest": workspace.main_dirty_digest_before,
}
if main != expected_main:
    raise RuntimeError("Main worktree changed")
if git(worktree, "rev-parse", "HEAD").stdout.strip() != workspace.base_head:
    raise RuntimeError("Worker created an unauthorized commit")
transition("P5", "done", "Regression and isolation passed; review handoff ready.")
total = {
    "run": 4,
    "passed": 4,
    "failed": 0,
    "errors": 0,
    "duration": targeted["duration"] + regression["duration"],
    "command": "targeted-human-commit-contract; human-commit-regression-discovery",
    "evidence": "phase5-human-commit://worker-tests",
    "summary": "Targeted 2/2 and regression 2/2 passed.",
}
handoff = (
    "Work Item: %s\nWorkspace: %s\nBranch: %s\nBase/current HEAD: %s\n"
    "Changed files: tests/__init__.py, tests/test_human_commit_contract.py\n"
    "Tests: targeted 2/2; regression 2/2\nPlan: P1-P5 complete\n"
    "Warnings: uncommitted; human exact-state approval required.\n"
    "Blockers: none\nProhibited actions performed: none."
    % (
        workspace.work_item_id.id,
        workspace.id,
        workspace.execution_branch,
        workspace.base_head,
    )
)
workspace.worker_mark_review_required(*token(), handoff, total)
env.cr.commit()
print(
    json.dumps(
        {
            "workspace_id": workspace.id,
            "state": workspace.state,
            "work_phase": workspace.work_item_id.current_phase,
            "effective_uid": os.geteuid(),
            "normalized_paths": normalized,
            "targeted_tests": 2,
            "regression_tests": 2,
            "pause_checkpoint_id": pause_checkpoint.id,
            "lease_versions": [1, lease["lease_version"]],
            "concurrent_writer": "rejected",
        },
        sort_keys=True,
    )
)
