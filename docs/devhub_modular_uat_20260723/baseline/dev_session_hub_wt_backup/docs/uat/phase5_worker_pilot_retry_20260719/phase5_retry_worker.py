"""Bounded Phase 5 retry worker with strict porcelain allowlist enforcement."""

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
    _parse_git_porcelain_v1_z,
)
from odoo.exceptions import AccessError


STATE_FILE = pathlib.Path("/srv/devhub-uat/runtime/phase5-pilot-retry-state.json")
ALLOWED_FILES = {"tests/__init__.py", "tests/test_fixture_readme_retry.py"}
CLIENT_NAME = "Playwright UAT Client"
TEST_MODULE = """from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TestFixtureReadmeRetryContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_declares_exact_uat_fixture_heading(self):
        self.assertIn("# PetSpot Isolation UAT Fixture", self.readme)

    def test_remains_explicitly_non_production(self):
        self.assertIn("Isolation UAT Fixture", self.readme)
        self.assertNotIn("production", self.readme.casefold())


if __name__ == "__main__":
    unittest.main()
"""


def emit(**values):
    values["effective_uid"] = os.geteuid()
    values["effective_user"] = pwd.getpwuid(os.geteuid()).pw_name
    print(json.dumps(values, sort_keys=True))


def save_state(values):
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(values, sort_keys=True), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(STATE_FILE)


def load_state():
    if not STATE_FILE.is_file() or STATE_FILE.stat().st_mode & 0o077:
        raise RuntimeError("Secure retry worker state is missing or unsafe")
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def git(worktree, *args, text=True):
    return subprocess.run(
        ["git", "-c", "safe.directory=%s" % worktree, "-C", worktree, *args],
        check=True,
        capture_output=True,
        text=text,
        timeout=15,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": "/nonexistent",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
        },
    )


def validate_identity_and_target(workspace):
    if os.geteuid() != 1001 or pwd.getpwuid(os.geteuid()).pw_name != "devworker":
        raise RuntimeError("Unexpected worker OS identity")
    if subprocess.run(
        ["sudo", "-n", "true"], capture_output=True, timeout=5
    ).returncode == 0:
        raise RuntimeError("Worker unexpectedly has non-interactive sudo")
    if os.access("/var/run/docker.sock", os.R_OK | os.W_OK):
        raise RuntimeError("Worker unexpectedly has Docker socket access")
    if os.access("/home/sabry", os.R_OK):
        raise RuntimeError("Worker unexpectedly has Sabry home access")
    if os.access("/srv/devhub-uat/manual", os.W_OK):
        raise RuntimeError("Worker unexpectedly has manual-worktree write access")
    root = os.path.realpath(workspace.repository_id.worker_worktree_root)
    worktree = os.path.realpath(workspace.worktree_path)
    if os.path.commonpath((root, worktree)) != root or worktree == root:
        raise RuntimeError("Workspace escaped the registered worker root")
    if os.getcwd() != worktree:
        os.chdir(worktree)
    if git(worktree, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() != (
        workspace.execution_branch
    ):
        raise RuntimeError("Worker branch mismatch")
    if git(worktree, "rev-parse", "HEAD").stdout.strip() != workspace.base_head:
        raise RuntimeError("Unexpected worker HEAD")
    return worktree


def controlled_workspace(state):
    workspace = env["dev.execution.workspace"].browse(state["workspace_id"]).exists()
    if not workspace:
        raise RuntimeError("Execution Workspace not found")
    exact = {
        "plan_id": workspace.plan_id.id,
        "plan_hash": workspace.approved_plan_hash,
        "policy_hash": workspace.policy_hash,
        "contract_hash": workspace.execution_contract_hash,
        "repository_id": workspace.repository_id.id,
        "environment_id": workspace.environment_id.id,
    }
    for name, value in exact.items():
        if state.get(name) != value:
            raise RuntimeError("Controlled reference mismatch: %s" % name)
    validate_identity_and_target(workspace)
    return workspace


def step(workspace, key):
    record = workspace.plan_id.step_ids.filtered(lambda item: item.step_key == key)
    if len(record) != 1:
        raise RuntimeError("Expected exactly one approved step %s" % key)
    return record


def token(state):
    value = state.get("lease_token")
    if not value:
        raise RuntimeError("Worker lease is not available")
    return value, int(state["lease_version"])


def transition(workspace, state, key, status, summary=None):
    workspace.worker_update_step(
        *token(state),
        step(workspace, key),
        status,
        result_summary=summary,
    )


def checkpoint(workspace, state, summary, test_result=None):
    return workspace.worker_checkpoint(
        *token(state), summary, test_result=test_result
    )


def validate_allowlist(workspace, state):
    workspace._assert_worker_execution(*token(state))
    raw = git(
        workspace.worktree_path,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        text=False,
    ).stdout
    paths = _assert_git_changes_allowlisted(
        raw, workspace.worktree_path, ALLOWED_FILES
    )
    records = _parse_git_porcelain_v1_z(raw, workspace.worktree_path)
    workspace._assert_worker_execution(*token(state))
    return {
        "normalized_paths": paths,
        "status_codes": [record["status"] for record in records],
    }


def run_tests(workspace, state, reference, args):
    workspace._assert_worker_execution(*token(state))
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, *args],
        cwd=workspace.worktree_path,
        capture_output=True,
        text=True,
        timeout=60,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": "/nonexistent",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )
    duration = time.monotonic() - started
    workspace._assert_worker_execution(*token(state))
    if result.returncode:
        raise RuntimeError("%s failed: %s" % (reference, result.stderr[-1000:]))
    matched = re.search(r"Ran (\d+) test", result.stderr)
    passed = int(matched.group(1)) if matched else 0
    return {
        "run": passed,
        "passed": passed,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "duration": round(duration, 3),
        "command": reference,
        "evidence": "phase5-retry://worker-tests/%s" % reference,
        "summary": "%s passed (%s tests)." % (reference, passed),
    }


stage = os.environ.get("PHASE5_STAGE")

if stage == "start":
    if STATE_FILE.exists():
        raise RuntimeError("A retry worker state already exists")
    state = {
        "workspace_id": int(os.environ["PHASE5_WORKSPACE_ID"]),
        "plan_id": int(os.environ["PHASE5_PLAN_ID"]),
        "plan_hash": os.environ["PHASE5_PLAN_HASH"],
        "policy_hash": os.environ["PHASE5_POLICY_HASH"],
        "contract_hash": os.environ["PHASE5_CONTRACT_HASH"],
        "repository_id": int(os.environ["PHASE5_REPOSITORY_ID"]),
        "environment_id": int(os.environ["PHASE5_ENVIRONMENT_ID"]),
    }
    workspace = controlled_workspace(state)
    client = env["dev.client"].search([("name", "=", CLIENT_NAME)], limit=1)
    state.update(
        workspace.start_worker("phase5-pilot-retry-devworker", client, seconds=900)
    )
    save_state(state)
    transition(workspace, state, "P1", "in_progress")
    workspace._assert_worker_execution(*token(state))
    readme = pathlib.Path(workspace.worktree_path, "README.md").read_text(
        encoding="utf-8"
    )
    if readme.strip() != "# PetSpot Isolation UAT Fixture":
        raise RuntimeError("Fixture README is not the approved baseline")
    transition(
        workspace,
        state,
        "P1",
        "done",
        "Identity, workspace, hashes, lease, Base HEAD, and README validated.",
    )
    checkpoint(workspace, state, "P1 controlled inspection completed.")
    env.cr.commit()
    emit(
        stage=stage,
        workspace_id=workspace.id,
        state=workspace.state,
        lease_version=state["lease_version"],
        completed=["P1"],
    )

elif stage == "implement":
    state = load_state()
    workspace = controlled_workspace(state)
    transition(workspace, state, "P2", "in_progress")
    workspace._assert_worker_execution(*token(state))
    tests_dir = pathlib.Path(workspace.worktree_path, "tests")
    tests_dir.mkdir(mode=0o770)
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")
    (tests_dir / "test_fixture_readme_retry.py").write_text(
        TEST_MODULE, encoding="utf-8"
    )
    normalized = validate_allowlist(workspace, state)
    if set(normalized["normalized_paths"]) != ALLOWED_FILES:
        raise RuntimeError("Normalized paths differ from the exact allowlist")
    transition(
        workspace,
        state,
        "P2",
        "done",
        "Strict porcelain parser accepted exactly two allowlisted paths.",
    )
    checkpoint(workspace, state, "P2 normalized allowlist validation passed.")
    transition(workspace, state, "P3", "in_progress")
    targeted = run_tests(
        workspace,
        state,
        "targeted-readme-retry-contract",
        ["-m", "unittest", "-v", "tests.test_fixture_readme_retry"],
    )
    if targeted["passed"] != 2:
        raise RuntimeError("Targeted test count differs from expectation")
    transition(
        workspace, state, "P3", "done", "Targeted retry tests passed: 2/2."
    )
    checkpoint(workspace, state, "P3 targeted tests completed.", targeted)
    state["targeted"] = targeted
    state["normalization"] = normalized
    save_state(state)
    env.cr.commit()
    emit(
        stage=stage,
        workspace_id=workspace.id,
        state=workspace.state,
        completed=["P1", "P2", "P3"],
        targeted_tests=2,
        raw_status_codes=normalized["status_codes"],
        normalized_paths=normalized["normalized_paths"],
    )

elif stage == "pause":
    state = load_state()
    workspace = controlled_workspace(state)
    transition(workspace, state, "P4", "in_progress")
    pause_checkpoint = workspace.worker_pause(
        *token(state),
        "P1-P3 passed; P4 paused with exact dirty digest.",
        test_result=state["targeted"],
    )
    state["expected_dirty_digest"] = workspace.dirty_digest
    state["pause_checkpoint_id"] = pause_checkpoint.id
    state["lease_token"] = None
    save_state(state)
    env.cr.commit()
    emit(
        stage=stage,
        workspace_id=workspace.id,
        state=workspace.state,
        checkpoint_id=pause_checkpoint.id,
        fenced_version=state["lease_version"],
    )

elif stage == "resume":
    state = load_state()
    workspace = controlled_workspace(state)
    client = env["dev.client"].search([("name", "=", CLIENT_NAME)], limit=1)
    state.update(
        workspace.worker_resume(
            "phase5-pilot-retry-devworker",
            client,
            state["expected_dirty_digest"],
            seconds=900,
        )
    )
    rejected = False
    try:
        workspace.acquire_lease("phase5-retry-second-writer", client, seconds=60)
    except AccessError:
        rejected = True
    if not rejected:
        raise RuntimeError("Concurrent writer unexpectedly acquired the workspace")
    workspace.assert_lease(*token(state))
    workspace._event(
        "concurrent_writer_rejected",
        "Second retry writer denied by lease fencing",
        {"authoritative_version": state["lease_version"]},
    )
    transition(
        workspace,
        state,
        "P4",
        "done",
        "Same worktree resumed; second writer rejected.",
    )
    checkpoint(workspace, state, "P4 Pause/Resume and fencing completed.")
    save_state(state)
    env.cr.commit()
    emit(
        stage=stage,
        workspace_id=workspace.id,
        state=workspace.state,
        lease_version=state["lease_version"],
        concurrent_writer="rejected",
        same_worktree=True,
        completed=["P1", "P2", "P3", "P4"],
    )

elif stage == "finish":
    state = load_state()
    workspace = controlled_workspace(state)
    transition(workspace, state, "P5", "in_progress")
    regression = run_tests(
        workspace,
        state,
        "fixture-retry-regression-discovery",
        ["-m", "unittest", "discover", "-s", "tests", "-v"],
    )
    if regression["passed"] != 2:
        raise RuntimeError("Regression test count differs from expectation")
    normalized = validate_allowlist(workspace, state)
    if set(normalized["normalized_paths"]) != ALLOWED_FILES:
        raise RuntimeError("Final normalized paths differ from allowlist")
    main = workspace._main_snapshot(workspace.repository_id)
    expected_main = {
        "branch": workspace.main_branch_before,
        "head": workspace.main_head_before,
        "dirty": workspace.main_dirty_summary_before,
        "digest": workspace.main_dirty_digest_before,
    }
    if main != expected_main:
        raise RuntimeError("Manual worktree changed during retry")
    if git(workspace.worktree_path, "rev-parse", "HEAD").stdout.strip() != (
        workspace.base_head
    ):
        raise RuntimeError("Worker created an unauthorized commit")
    transition(
        workspace,
        state,
        "P5",
        "done",
        "Regression, normalized scope, and main-worktree isolation passed.",
    )
    total = {
        "run": 4,
        "passed": 4,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "duration": state["targeted"]["duration"] + regression["duration"],
        "command": (
            "targeted-readme-retry-contract; fixture-retry-regression-discovery"
        ),
        "evidence": "phase5-retry://worker-tests/targeted-and-regression",
        "summary": "Targeted 2/2 and regression 2/2 tests passed.",
    }
    handoff = (
        "Work Item: %s\nWorkspace: %s\nBranch: %s\nBase HEAD: %s\n"
        "Current HEAD: %s\nChanged files: tests/__init__.py, "
        "tests/test_fixture_readme_retry.py\nDiff summary: Added a stdlib "
        "retry contract for the disposable fixture README.\nCompleted steps: "
        "P1, P2, P3, P4, P5\nTests: targeted 2/2; regression 2/2\n"
        "Parser: porcelain v1 -z normalized two untracked paths; exact allowlist "
        "passed.\nWarnings: Changes are uncommitted and retained.\nBlockers: "
        "none\nHuman review: inspect the two files and decide whether to "
        "authorize a separate commit."
        % (
            workspace.work_item_id.id,
            workspace.id,
            workspace.execution_branch,
            workspace.base_head,
            workspace.current_head,
        )
    )
    workspace.worker_mark_review_required(*token(state), handoff, total)
    env.cr.commit()
    STATE_FILE.unlink()
    emit(
        stage=stage,
        workspace_id=workspace.id,
        state=workspace.state,
        work_phase=workspace.work_item_id.current_phase,
        normalized_paths=normalized["normalized_paths"],
        targeted_tests=2,
        regression_tests=2,
        policy_violations=0,
    )

else:
    raise RuntimeError("Unsupported fixed Phase 5 retry worker stage")
