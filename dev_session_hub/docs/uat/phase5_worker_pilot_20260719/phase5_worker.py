"""Bounded first-pilot Dev Worker.

Execute only through ``odoo-bin shell`` as OS user ``devworker``. The stage is
selected by the fixed ``PHASE5_STAGE`` environment variable. No task text,
filesystem path, or shell command is accepted as input.
"""

import json
import os
import pathlib
import pwd
import subprocess
import sys
import time

from odoo.exceptions import AccessError


STATE_FILE = pathlib.Path("/srv/devhub-uat/runtime/phase5-pilot-state.json")
ALLOWED_FILES = {"tests/__init__.py", "tests/test_fixture_readme.py"}
CLIENT_NAME = "Playwright UAT Client"
TEST_MODULE = """from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TestFixtureReadmeContract(unittest.TestCase):
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
    if not STATE_FILE.is_file():
        raise RuntimeError("Secure worker state is missing")
    if STATE_FILE.stat().st_mode & 0o077:
        raise RuntimeError("Secure worker state permissions are too broad")
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def git(worktree, *args):
    result = subprocess.run(
        ["git", "-c", "safe.directory=%s" % worktree, "-C", worktree, *args],
        check=True,
        capture_output=True,
        text=True,
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
    return result.stdout.strip()


def changed_files(workspace):
    workspace._validate_physical()
    return {
        line.strip()
        for line in (workspace.changed_files_summary or "").splitlines()
        if line.strip()
    }


def validate_identity_and_target(workspace):
    if os.geteuid() != 1001 or pwd.getpwuid(os.geteuid()).pw_name != "devworker":
        raise RuntimeError("Unexpected worker OS identity")
    if subprocess.run(
        ["sudo", "-n", "true"],
        capture_output=True,
        timeout=5,
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
    if git(worktree, "rev-parse", "--abbrev-ref", "HEAD") != workspace.execution_branch:
        raise RuntimeError("Worker branch mismatch")
    if git(worktree, "rev-parse", "HEAD") != workspace.base_head:
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


def checkpoint(workspace, state, summary, test_result=None):
    lease_token, lease_version = token(state)
    return workspace.worker_checkpoint(
        lease_token,
        lease_version,
        summary,
        test_result=test_result,
    )


def transition(workspace, state, key, status, summary=None):
    lease_token, lease_version = token(state)
    workspace.worker_update_step(
        lease_token,
        lease_version,
        step(workspace, key),
        status,
        result_summary=summary,
    )


def run_tests(workspace, state, command_reference, args):
    lease_token, lease_version = token(state)
    workspace._assert_worker_execution(lease_token, lease_version)
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
    workspace._assert_worker_execution(lease_token, lease_version)
    if result.returncode != 0:
        raise RuntimeError(
            "%s failed: %s" % (command_reference, (result.stderr or "")[-1000:])
        )
    passed = sum(
        int(value)
        for value in __import__("re").findall(r"Ran (\d+) test", result.stderr)
    )
    return {
        "run": passed,
        "passed": passed,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "duration": round(duration, 3),
        "command": command_reference,
        "evidence": "phase5://worker-tests/%s" % command_reference,
        "summary": "%s passed (%s tests)." % (command_reference, passed),
    }


stage = os.environ.get("PHASE5_STAGE")

if stage == "start":
    if STATE_FILE.exists():
        raise RuntimeError("A pilot worker state already exists")
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
    lease = workspace.start_worker("phase5-pilot-devworker", client, seconds=900)
    state.update(lease)
    save_state(state)
    transition(workspace, state, "P1", "in_progress")
    workspace._assert_worker_execution(*token(state))
    readme = pathlib.Path(workspace.worktree_path, "README.md").read_text(
        encoding="utf-8"
    )
    if readme.strip() != "# PetSpot Isolation UAT Fixture":
        raise RuntimeError("Fixture README contract is not the approved baseline")
    transition(
        workspace,
        state,
        "P1",
        "done",
        "Validated identity, workspace, hashes, lease, Base HEAD, and README.",
    )
    checkpoint(workspace, state, "P1 boundary inspection completed.")
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
    (tests_dir / "test_fixture_readme.py").write_text(
        TEST_MODULE, encoding="utf-8"
    )
    workspace._assert_worker_execution(*token(state))
    if changed_files(workspace) != ALLOWED_FILES:
        raise RuntimeError("Changed files exceed the approved allowlist")
    transition(
        workspace,
        state,
        "P2",
        "done",
        "Created exactly the two approved Python unittest files.",
    )
    checkpoint(workspace, state, "P2 allowlisted implementation completed.")
    transition(workspace, state, "P3", "in_progress")
    targeted = run_tests(
        workspace,
        state,
        "targeted-readme-contract",
        ["-m", "unittest", "-v", "tests.test_fixture_readme"],
    )
    if targeted["passed"] != 2:
        raise RuntimeError("Targeted test count differed from the approved expectation")
    transition(
        workspace,
        state,
        "P3",
        "done",
        "Targeted README contract tests passed: 2/2.",
    )
    checkpoint(
        workspace,
        state,
        "P3 targeted tests completed before controlled pause.",
        targeted,
    )
    state["targeted"] = targeted
    save_state(state)
    env.cr.commit()
    emit(
        stage=stage,
        workspace_id=workspace.id,
        state=workspace.state,
        completed=["P1", "P2", "P3"],
        targeted_tests=targeted["passed"],
        changed_files=sorted(ALLOWED_FILES),
    )

elif stage == "pause":
    state = load_state()
    workspace = controlled_workspace(state)
    pause_checkpoint = workspace.worker_pause(
        *token(state),
        "P1-P3 completed; targeted tests passed; pause requested.",
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
    lease = workspace.worker_resume(
        "phase5-pilot-devworker",
        client,
        state["expected_dirty_digest"],
        seconds=900,
    )
    state.update(lease)
    rejected = False
    try:
        workspace.acquire_lease("phase5-second-writer", client, seconds=60)
    except AccessError:
        rejected = True
    if not rejected:
        raise RuntimeError("Concurrent writer unexpectedly acquired the workspace")
    workspace.assert_lease(*token(state))
    workspace._event(
        "concurrent_writer_rejected",
        "Second Phase 5 writer was denied by lease fencing",
        {"authoritative_version": state["lease_version"]},
    )
    save_state(state)
    env.cr.commit()
    emit(
        stage=stage,
        workspace_id=workspace.id,
        state=workspace.state,
        lease_version=state["lease_version"],
        concurrent_writer="rejected",
        same_worktree=True,
    )

elif stage == "finish":
    state = load_state()
    workspace = controlled_workspace(state)
    transition(workspace, state, "P4", "in_progress")
    regression = run_tests(
        workspace,
        state,
        "fixture-regression-discovery",
        ["-m", "unittest", "discover", "-s", "tests", "-v"],
    )
    if regression["passed"] != 2:
        raise RuntimeError("Regression test count differed from expectation")
    transition(
        workspace,
        state,
        "P4",
        "done",
        "Regression discovery passed: 2/2.",
    )
    checkpoint(workspace, state, "P4 regression tests completed.", regression)
    transition(workspace, state, "P5", "in_progress")
    workspace._assert_worker_execution(*token(state))
    if changed_files(workspace) != ALLOWED_FILES:
        raise RuntimeError("Final changed files exceed the approved allowlist")
    main = workspace._main_snapshot(workspace.repository_id)
    expected_main = {
        "branch": workspace.main_branch_before,
        "head": workspace.main_head_before,
        "dirty": workspace.main_dirty_summary_before,
        "digest": workspace.main_dirty_digest_before,
    }
    if main != expected_main:
        raise RuntimeError("Manual worktree changed during worker execution")
    if git(workspace.worktree_path, "rev-parse", "HEAD") != workspace.base_head:
        raise RuntimeError("Worker created an unauthorized commit")
    transition(
        workspace,
        state,
        "P5",
        "done",
        "Isolation verified and bounded review handoff prepared.",
    )
    total = {
        "run": state["targeted"]["run"] + regression["run"],
        "passed": state["targeted"]["passed"] + regression["passed"],
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "duration": state["targeted"]["duration"] + regression["duration"],
        "command": "targeted-readme-contract; fixture-regression-discovery",
        "evidence": "phase5://worker-tests/targeted-and-regression",
        "summary": "Targeted 2/2 and regression 2/2 tests passed.",
    }
    handoff = (
        "Work Item: %s\nWorkspace: %s\nBranch: %s\nBase HEAD: %s\n"
        "Current HEAD: %s\nChanged files: tests/__init__.py, "
        "tests/test_fixture_readme.py\nDiff summary: Added a stdlib unittest "
        "contract for the disposable fixture README.\nCompleted steps: "
        "P1, P2, P3, P4, P5\nTests: targeted 2/2; regression 2/2\n"
        "Warnings: Changes are uncommitted and intentionally retained.\n"
        "Blockers: none\nHuman review: inspect the two allowlisted files and "
        "decide whether to authorize a separate commit."
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
        changed_files=sorted(ALLOWED_FILES),
        targeted_tests=2,
        regression_tests=2,
        policy_violations=0,
    )

else:
    raise RuntimeError("Unsupported fixed Phase 5 worker stage")
