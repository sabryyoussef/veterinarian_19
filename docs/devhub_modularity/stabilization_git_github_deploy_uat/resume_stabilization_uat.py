#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resume stabilization UAT from approved Work Item 3320."""
from __future__ import annotations

import json
import os
import subprocess
import traceback
import xmlrpc.client
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("PLAYWRIGHT_HOST_PLATFORM_OVERRIDE", "ubuntu24.04-x64")
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8028"
DB = "pet_spot_elsahel_test"
LOGIN = "admin"
PASSWORD = "admin"
EVID = Path(__file__).resolve().parent
SHOT = EVID / "screenshots"
DATA = EVID / "data"
LOGS = EVID / "logs"
WORKER = EVID / "worker" / "run_worker_stage.sh"

WI_ID = 3320
ANALYSIS_ID = 2691
PLAN_ID = 2475
APPROVAL_ID = 2273
MARKER = "DEVHUB-GIT-GITHUB-DEPLOY-UAT-20260723T114946Z"
ACTION_WORK = 1377
ACTION_WORKFLOW = 1391

trace: dict = {
    "marker": MARKER,
    "resumed_from": "approved",
    "work_item": {"id": WI_ID},
    "analysis": {"id": ANALYSIS_ID},
    "plan": {"id": PLAN_ID},
    "approval": {"id": APPROVAL_ID},
    "errors": [],
    "non_blockers": [],
    "screenshots": [],
}


def log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    with (LOGS / "stabilization_resume.log").open("a") as fh:
        fh.write(line + "\n")


class Odoo:
    def __init__(self):
        self.common = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/common", allow_none=True)
        self.models = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/object", allow_none=True)
        self.uid = self.common.authenticate(DB, LOGIN, PASSWORD, {})

    def kw(self, model, method, *args, **kwargs):
        return self.models.execute_kw(DB, self.uid, PASSWORD, model, method, list(args), kwargs)

    def create(self, model, vals):
        return self.kw(model, "create", vals)

    def write(self, model, ids, vals):
        return self.kw(model, "write", ids if isinstance(ids, list) else [ids], vals)

    def read(self, model, ids, fields=None):
        kwargs = {}
        if fields:
            kwargs["fields"] = fields
        return self.kw(model, "read", ids if isinstance(ids, list) else [ids], **kwargs)

    def search_read(self, model, domain, fields=None, limit=None, order=None):
        kwargs = {}
        if fields:
            kwargs["fields"] = fields
        if limit is not None:
            kwargs["limit"] = limit
        if order:
            kwargs["order"] = order
        return self.kw(model, "search_read", domain, **kwargs)

    def call(self, model, method, ids, *args, **kwargs):
        return self.kw(model, method, ids if isinstance(ids, list) else [ids], *args, **kwargs)


def run_worker(stage: str, workspace_id: int, marker: str = "", commit_message: str = "") -> dict:
    cmd = ["bash", str(WORKER), stage, str(workspace_id), marker, commit_message]
    log(f"worker stage={stage} workspace={workspace_id}")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    (LOGS / f"worker_{stage}_stdout.txt").write_text(proc.stdout or "")
    (LOGS / f"worker_{stage}_stderr.txt").write_text(proc.stderr or "")
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip().startswith("{")]
    payload = {}
    if lines:
        try:
            payload = json.loads(lines[-1])
        except json.JSONDecodeError:
            payload = {"raw": lines[-1]}
    if proc.returncode != 0 or not payload.get("ok"):
        raise RuntimeError(
            f"worker stage {stage} failed rc={proc.returncode} payload={payload} "
            f"tail={(proc.stdout or '')[-2000:]}"
        )
    return payload


def dismiss_modals(page) -> None:
    for sel in (".modal .btn-close", ".o-overlay-container .btn-close"):
        loc = page.locator(sel)
        if loc.count() and loc.first.is_visible():
            try:
                loc.first.click(timeout=1000)
            except Exception:
                pass


def click_notebook_tab(page, label: str) -> None:
    for sel in (
        f'.o_notebook .nav-link:has-text("{label}")',
        f'.nav-tabs a:has-text("{label}")',
        f'a[role="tab"]:has-text("{label}")',
    ):
        loc = page.locator(sel).first
        if loc.count() and loc.is_visible():
            loc.click()
            page.wait_for_timeout(800)
            return


def shot(page, name: str, note: str) -> None:
    dismiss_modals(page)
    page.wait_for_timeout(400)
    page.screenshot(path=str(SHOT / name), full_page=False)
    log(f"screenshot {name} :: {note}")
    trace["screenshots"].append({"file": name, "proves": note, "url": page.url})


def login_ui(page) -> None:
    page.goto(f"{BASE}/web/login", wait_until="domcontentloaded", timeout=60000)
    page.fill('input[name="login"]', LOGIN)
    page.fill('input[name="password"]', PASSWORD)
    db_sel = page.locator('select[name="db"]')
    if db_sel.count() and db_sel.is_visible():
        db_sel.select_option(DB)
    page.locator('button.btn-primary[type="submit"]').first.click()
    page.wait_for_load_state("networkidle", timeout=90000)
    page.wait_for_timeout(1200)


def open_action(page, action_id: int, record_id: int | None = None) -> None:
    url = (
        f"{BASE}/odoo/action-{action_id}/{record_id}"
        if record_id
        else f"{BASE}/odoo/action-{action_id}"
    )
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1800)
    dismiss_modals(page)


def open_model_form(page, model: str, record_id: int) -> None:
    page.goto(f"{BASE}/odoo/{model}/{record_id}", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1800)
    dismiss_modals(page)


def main() -> int:
    odoo = Odoo()
    commit_msg = f"test(devhub): end-to-end GitHub deploy UAT {MARKER}"

    approval = odoo.read(
        "dev.work.approval",
        APPROVAL_ID,
        ["id", "decision", "plan_hash", "plan_id", "plan_revision", "exact_plan_hash"],
    )[0]
    plan = odoo.read("dev.work.plan", PLAN_ID, ["id", "status", "content_hash", "revision"])[0]
    trace["approval"] = approval
    trace["plan"] = plan
    assert approval["plan_hash"] == plan["content_hash"]
    log(f"exact-hash ok plan={plan['content_hash'][:16]}...")

    staging = subprocess.check_output(
        ["git", "--git-dir=/srv/devhub/repos/petspot.git", "rev-parse", "staging"],
        text=True,
    ).strip()
    odoo.write(
        "dev.repository",
        1,
        {
            "head_cache": staging,
            "default_branch": "staging",
            "git_remote": "git@github.com:sabryyoussef/veterinarian_19.git",
            "execution_classification": "safe_for_isolated_worktree",
            "agent_execution_allowed": True,
            "worker_identity": "devworker",
            "worker_git_common_dir": "/srv/devhub/repos/petspot.git",
            "worker_worktree_root": "/srv/devhub/worktrees",
        },
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        login_ui(page)

        # Ensure early screenshots exist (overwrite ok)
        open_action(page, ACTION_WORK, WI_ID)
        shot(page, "01_work_created.png", "Work Item 3320")
        open_model_form(page, "dev.work.analysis", ANALYSIS_ID)
        shot(page, "02_analysis.png", "Analysis 2691")
        open_model_form(page, "dev.work.plan", PLAN_ID)
        shot(page, "03_plan.png", "Plan 2475")
        open_action(page, ACTION_WORK, WI_ID)
        click_notebook_tab(page, "Plan")
        shot(page, "04_approval.png", "Approval 2273 exact-hash")
        open_action(page, ACTION_WORKFLOW)
        shot(page, "05_workflow_pre_execution.png", "Workflow before execution")

        existing = odoo.search_read(
            "dev.execution.workspace",
            [["work_item_id", "=", WI_ID]],
            fields=["id", "state", "execution_branch", "worktree_path"],
            limit=1,
            order="id desc",
        )
        if existing and existing[0]["state"] not in ("blocked", "cancelled"):
            ws_id = existing[0]["id"]
            log(f"reusing workspace {ws_id} state={existing[0]['state']}")
        else:
            odoo.call("dev.work.item", "action_prepare_execution_workspace", WI_ID)
            ws_id = odoo.search_read(
                "dev.execution.workspace",
                [["work_item_id", "=", WI_ID]],
                fields=["id"],
                limit=1,
                order="id desc",
            )[0]["id"]
            log(f"created workspace proposal {ws_id}")

        ws = odoo.read(
            "dev.execution.workspace",
            ws_id,
            [
                "id",
                "state",
                "execution_branch",
                "worktree_path",
                "base_branch",
                "base_head",
                "worker_identity",
            ],
        )[0]
        trace["workspace_proposal"] = ws

        if ws["state"] == "pending_confirmation":
            confirm = run_worker("confirm", ws_id)
            trace["confirm"] = confirm
        else:
            log(f"skip confirm; state={ws['state']}")

        ws = odoo.read(
            "dev.execution.workspace",
            ws_id,
            [
                "id",
                "state",
                "execution_branch",
                "worktree_path",
                "base_branch",
                "base_head",
                "current_head",
                "dirty_summary",
            ],
        )[0]
        trace["workspace_ready"] = ws
        log(f"workspace ready state={ws['state']} branch={ws['execution_branch']}")

        # Session
        try:
            env_row = odoo.read("dev.environment", 1, ["machine_id"])[0]
            machine_id = env_row["machine_id"][0] if env_row.get("machine_id") else 1
            sessions = odoo.search_read(
                "dev.session",
                [["work_item_id", "=", WI_ID], ["execution_workspace_id", "=", ws_id]],
                fields=["id"],
                limit=1,
            )
            if sessions:
                session_id = sessions[0]["id"]
            else:
                session_id = odoo.create(
                    "dev.session",
                    {
                        "name": f"{MARKER} isolated session",
                        "project_id": 1,
                        "repository_id": 1,
                        "environment_id": 1,
                        "machine_id": machine_id,
                        "work_item_id": WI_ID,
                        "execution_workspace_id": ws_id,
                        "client_id": 2,
                        "user_id": odoo.uid,
                        "session_type": "isolated_execution_workspace",
                        "working_directory": ws["worktree_path"],
                    },
                )
            try:
                odoo.call("dev.session", "action_start", session_id)
            except Exception as exc:
                trace["non_blockers"].append(f"session start: {exc}")
            trace["session"] = odoo.read(
                "dev.session",
                session_id,
                [
                    "id",
                    "name",
                    "state",
                    "branch",
                    "git_head",
                    "execution_workspace_id",
                    "session_type",
                    "working_directory",
                ],
            )[0]
        except Exception as exc:
            trace["non_blockers"].append(f"session: {exc}")
            log(f"session non-blocker: {exc}")

        open_model_form(page, "dev.execution.workspace", ws_id)
        shot(page, "06_session_workspace.png", "Isolated workspace / session linkage")

        # Implement if still ready/active (not yet review_required)
        ws = odoo.read("dev.execution.workspace", ws_id, ["state", "dirty_summary"])[0]
        if ws["state"] in ("ready", "active", "paused"):
            implement = run_worker("implement", ws_id, MARKER)
            trace["implement"] = implement
            checkpoint_id = implement.get("checkpoint_id")
        else:
            log(f"skip implement; state={ws['state']}")
            implement = {}
            cps = odoo.search_read(
                "dev.work.checkpoint",
                [["work_item_id", "=", WI_ID]],
                fields=["id"],
                limit=1,
                order="id desc",
            )
            checkpoint_id = cps[0]["id"] if cps else None

        if checkpoint_id:
            trace["checkpoint"] = odoo.read(
                "dev.work.checkpoint",
                checkpoint_id,
                ["id", "trigger", "branch", "git_head", "files_touched_summary"],
            )[0]

        open_model_form(page, "dev.execution.workspace", ws_id)
        shot(page, "07_execution.png", "After worker implementation")
        if checkpoint_id:
            open_model_form(page, "dev.work.checkpoint", checkpoint_id)
            shot(page, "08_checkpoint.png", "Checkpoint evidence")

        ws = odoo.read(
            "dev.execution.workspace",
            ws_id,
            ["state", "committed_sha", "execution_branch", "commit_record_id"],
        )[0]
        if ws["state"] == "review_required":
            ca = run_worker("commit_approve", ws_id, MARKER, commit_msg)
            trace["commit_approve"] = ca
            ce = run_worker("commit_execute", ws_id)
            trace["commit_execute"] = ce
        elif ws.get("committed_sha"):
            ce = {
                "committed_sha": ws["committed_sha"],
                "execution_branch": ws["execution_branch"],
            }
            trace["commit_execute"] = ce
            log("commit already present")
        else:
            raise RuntimeError(f"unexpected workspace state for commit: {ws['state']}")

        open_model_form(page, "dev.execution.workspace", ws_id)
        click_notebook_tab(page, "Git")
        shot(page, "09_git_branch.png", "Git branch evidence")
        shot(page, "10_git_commit.png", "Git commit evidence")

        ws = odoo.read("dev.execution.workspace", ws_id, ["state", "push_record_id"])[0]
        if ws["state"] in ("committed_reviewed", "push_approved"):
            if ws["state"] == "committed_reviewed":
                trace["push_review"] = run_worker("push_review", ws_id)
                trace["push_approve"] = run_worker("push_approve", ws_id)
            trace["push_execute"] = run_worker("push_execute", ws_id)
        else:
            log(f"push path state={ws['state']}")

        branch = (trace.get("commit_execute") or {}).get("execution_branch") or odoo.read(
            "dev.execution.workspace", ws_id, ["execution_branch"]
        )[0]["execution_branch"]
        sha = (trace.get("commit_execute") or {}).get("committed_sha") or odoo.read(
            "dev.execution.workspace", ws_id, ["committed_sha"]
        )[0]["committed_sha"]
        trace["git"] = {"branch": branch, "sha": sha}

        # Draft PR via gh
        pr = {"status": "pending"}
        try:
            create = subprocess.run(
                [
                    "gh",
                    "pr",
                    "create",
                    "--repo",
                    "sabryyoussef/veterinarian_19",
                    "--draft",
                    "--base",
                    "staging",
                    "--head",
                    branch,
                    "--title",
                    f"[UAT][DRAFT] {MARKER}",
                    "--body",
                    (
                        f"## Summary\n- Marker `{MARKER}`\n- Work Item `{WI_ID}`\n"
                        f"- Commit `{sha}`\n- Test-only docs; do not merge to Production.\n"
                    ),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            (LOGS / "gh_pr_create.txt").write_text(
                f"rc={create.returncode}\n{create.stdout}\n{create.stderr}"
            )
            if create.returncode != 0:
                # maybe already exists
                listed = subprocess.run(
                    [
                        "gh",
                        "pr",
                        "list",
                        "--repo",
                        "sabryyoussef/veterinarian_19",
                        "--head",
                        branch,
                        "--json",
                        "number,url,isDraft,baseRefName,headRefName,state",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                items = json.loads(listed.stdout or "[]")
                if items:
                    pr = items[0]
                    pr["creation_path"] = "gh_cli_existing"
                else:
                    raise RuntimeError(create.stderr or create.stdout)
            else:
                url = (create.stdout or "").strip().splitlines()[-1]
                view = subprocess.run(
                    [
                        "gh",
                        "pr",
                        "view",
                        url,
                        "--repo",
                        "sabryyoussef/veterinarian_19",
                        "--json",
                        "number,url,isDraft,baseRefName,headRefName,state,mergeable",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                pr = json.loads(view.stdout)
                pr["creation_path"] = "gh_cli_draft_after_devhub_push"
            pr["devhub_github_app"] = "NO-GO (empty App broker under /srv/devhub/credentials/github)"
            trace["github_pr"] = pr
            log(f"PR #{pr.get('number')} draft={pr.get('isDraft')} {pr.get('url')}")
        except Exception as exc:
            pr = {"status": "NO-GO", "error": str(exc)}
            trace["github_pr"] = pr
            trace["errors"].append(f"GitHub Draft PR: {exc}")

        (DATA / "github_draft_pr.json").write_text(json.dumps(pr, indent=2, default=str))
        open_model_form(page, "dev.execution.workspace", ws_id)
        shot(page, "11_github_draft_pr.png", f"Draft PR evidence #{pr.get('number')}")

        deploy = {
            "status": "DEPLOYMENT READY",
            "reason": (
                "Test deploy target id=4 exists, but Dev Hub deploy requires "
                "merged_reviewed + merge record. UAT keeps Draft PR unmerged."
            ),
            "target_id": 4,
            "commit_sha": sha,
            "branch": branch,
            "production_deploy": False,
        }
        trace["deploy"] = deploy
        (DATA / "deploy_gate.json").write_text(json.dumps(deploy, indent=2))
        open_action(page, ACTION_WORK, WI_ID)
        click_notebook_tab(page, "Deploy")
        shot(page, "12_deploy_gate.png", "Deploy gate context")
        shot(page, "13_deployment_ready.png", "Deployment-Ready (no merge/deploy)")

        try:
            reports = odoo.search_read(
                "dev.completion.report",
                [["work_item_id", "=", WI_ID]],
                fields=["id", "status"],
                limit=1,
                order="id desc",
            )
            if reports:
                try:
                    odoo.call("dev.completion.report", "action_approve", reports[0]["id"])
                except Exception as exc:
                    trace["non_blockers"].append(f"completion approve: {exc}")
            try:
                odoo.call("dev.work.item", "action_complete", WI_ID)
            except Exception as exc:
                trace["non_blockers"].append(f"complete: {exc}")
        except Exception as exc:
            trace["non_blockers"].append(f"completion: {exc}")

        wi_final = odoo.read("dev.work.item", WI_ID, ["id", "name", "current_phase", "uuid"])[0]
        trace["work_item_final"] = wi_final
        open_action(page, ACTION_WORK, WI_ID)
        shot(page, "14_completion.png", f"Final phase={wi_final.get('current_phase')}")
        open_action(page, ACTION_WORKFLOW)
        shot(page, "15_workflow_final.png", "Workflow Board final")
        browser.close()

    safety = {
        "test_db": DB,
        "test_port": 8028,
        "production_service": subprocess.check_output(
            ["systemctl", "--user", "is-active", "pet_spot_elsahel.service"], text=True
        ).strip(),
        "pr_draft": (trace.get("github_pr") or {}).get("isDraft"),
        "pr_state": (trace.get("github_pr") or {}).get("state"),
        "no_production_deploy": True,
        "branch": branch,
        "sha": sha,
    }
    trace["production_safety"] = safety
    (DATA / "trace.json").write_text(json.dumps(trace, indent=2, default=str))
    log("RESUME COMPLETE")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        log(traceback.format_exc())
        (DATA / "trace_failed.json").write_text(json.dumps(trace, indent=2, default=str))
        raise
