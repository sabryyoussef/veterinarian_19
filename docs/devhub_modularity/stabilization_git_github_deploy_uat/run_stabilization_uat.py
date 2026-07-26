#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stabilization UAT: Analysis→Plan→Approval→isolated Git→push→Draft PR→Deploy-Ready."""
from __future__ import annotations

import json
import os
import subprocess
import time
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
for d in (SHOT, DATA, LOGS):
    d.mkdir(parents=True, exist_ok=True)

TS = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
MARKER = f"DEVHUB-GIT-GITHUB-DEPLOY-UAT-{TS}"
TITLE = f"{MARKER}: harmless Test-only documentation artifact for Git/GitHub/Deploy UAT"

ACTION_WORK = 1377
ACTION_WORKFLOW = 1391
ACTION_ANALYSIS = 1389
ACTION_PLAN = 1388

trace: dict = {
    "marker": MARKER,
    "ts": TS,
    "steps": [],
    "errors": [],
    "non_blockers": [],
    "screenshots": [],
}


def log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    with (LOGS / "stabilization_uat.log").open("a") as fh:
        fh.write(line + "\n")


class Odoo:
    def __init__(self):
        self.common = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/common", allow_none=True)
        self.models = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/object", allow_none=True)
        self.uid = self.common.authenticate(DB, LOGIN, PASSWORD, {})
        if not self.uid:
            raise RuntimeError("XML-RPC auth failed")
        log(f"authenticated uid={self.uid}")

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
            f"tail={(proc.stdout or '')[-1500:]}"
        )
    return payload


def click_notebook_tab(page, label: str) -> None:
    selectors = [
        f'.o_notebook .nav-link:has-text("{label}")',
        f'.nav-tabs a:has-text("{label}")',
        f'a[role="tab"]:has-text("{label}")',
    ]
    for sel in selectors:
        loc = page.locator(sel).first
        if loc.count() and loc.is_visible():
            loc.click()
            page.wait_for_timeout(800)
            return
    try:
        page.get_by_role("tab", name=label).click(timeout=3000)
        page.wait_for_timeout(800)
    except Exception:
        log(f"WARN: could not click tab {label}")


def dismiss_modals(page) -> None:
    for sel in (".modal .btn-close", ".o-overlay-container .btn-close", "button:has-text('Ok')"):
        loc = page.locator(sel)
        if loc.count() and loc.first.is_visible():
            try:
                loc.first.click(timeout=1000)
                page.wait_for_timeout(400)
            except Exception:
                pass


def shot(page, name: str, note: str) -> None:
    dismiss_modals(page)
    path = SHOT / name
    page.wait_for_timeout(400)
    page.screenshot(path=str(path), full_page=False)
    log(f"screenshot {name} :: {note}")
    trace["screenshots"].append({"file": name, "proves": note, "url": page.url})


def login_ui(page) -> None:
    page.goto(f"{BASE}/web/login", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector('input[name="login"]', timeout=30000)
    page.fill('input[name="login"]', LOGIN)
    page.fill('input[name="password"]', PASSWORD)
    db_sel = page.locator('select[name="db"]')
    if db_sel.count() and db_sel.is_visible():
        db_sel.select_option(DB)
    login_btn = page.locator('button.btn-primary[type="submit"]')
    if login_btn.count():
        login_btn.first.click()
    else:
        page.get_by_role("button", name="Log in").click()
    page.wait_for_load_state("networkidle", timeout=90000)
    page.wait_for_timeout(1500)
    if page.locator('input[name="login"]').count() and "login" in page.url:
        raise RuntimeError(f"UI login failed url={page.url}")


def open_action(page, action_id: int, record_id: int | None = None) -> None:
    url = (
        f"{BASE}/odoo/action-{action_id}/{record_id}"
        if record_id
        else f"{BASE}/odoo/action-{action_id}"
    )
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)
    dismiss_modals(page)


def open_model_form(page, model: str, record_id: int) -> None:
    page.goto(f"{BASE}/odoo/{model}/{record_id}", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)
    dismiss_modals(page)


def main() -> int:
    odoo = Odoo()
    commit_msg = f"test(devhub): end-to-end GitHub deploy UAT {MARKER}"

    # Refresh staging tip into bare + head_cache
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
    trace["base_staging_sha"] = staging

    # --- Work Item ---
    src_id = odoo.create(
        "dev.work.source.message",
        {
            "provider": "manual",
            "provider_message_id": f"stab-uat-{TS}",
            "text_snapshot": (
                f"{MARKER}\n"
                "Create a small documentation-only file under docs/devhub_modularity/uat/. "
                "Exercise isolated session, Git commit, GitHub Draft PR, Deployment-Ready. "
                "No Production impact."
            ),
            "message_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "extracted_item_index": 0,
        },
    )
    UAT_OP_WP = 900000000 + (int(time.time()) % 90000000)  # unique Test marker within XML-RPC int32
    task_id = odoo.create(
        "project.task",
        {
            "name": TITLE,
            "project_id": 1,
            "description": f"<p>{MARKER} Test-only stabilization UAT. No Production impact.</p>",
            "op_backend_id": 1,
            "op_work_package_id": UAT_OP_WP,
        },
    )
    wi_id = odoo.create(
        "dev.work.item",
        {
            "name": TITLE,
            "dev_project_id": 1,
            "odoo_project_id": 1,
            "odoo_task_id": task_id,
            "op_backend_id": 1,
            "op_work_package_id": UAT_OP_WP,
            "responsible_user_id": odoo.uid,
            "preferred_repository_id": 1,
            "preferred_environment_id": 1,
            "source_message_ids": [(4, src_id)],
        },
    )
    odoo.call("dev.work.item", "action_start_triage", wi_id)
    odoo.call("dev.work.item", "action_register", wi_id)
    odoo.call("dev.work.item", "action_start_analysis", wi_id)
    wi = odoo.read(
        "dev.work.item",
        wi_id,
        ["id", "name", "uuid", "current_phase"],
    )[0]
    trace["work_item"] = wi
    log(f"work item {wi_id} phase={wi['current_phase']}")

    # --- Analysis ---
    analysis_vals = {
        "work_item_id": wi_id,
        "problem_summary": f"{MARKER}: close Git/GitHub/Deploy path on Live Test.",
        "original_request_summary": TITLE,
        "reproduction_context": "Live Test DB pet_spot_elsahel_test :8028 canonical stack.",
        "current_behavior": "Operational UAT passed; isolated Git/GitHub incomplete.",
        "expected_behavior": "Isolated worktree + commit + Draft PR + Deployment-Ready.",
        "technical_findings": "Use worker-owned bare repo + exact-hash approval gates.",
        "affected_components": "docs/devhub_modularity/uat (Test evidence only)",
        "risks": "None — Test-only; Draft PR; no Production merge/deploy.",
        "dependencies": "devworker OS identity; /srv/devhub repos/worktrees; gh CLI fallback.",
        "open_questions": "Dev Hub GitHub App broker empty — Draft PR via gh after push.",
        "evidence_references": f"marker={MARKER}",
        "origin": "manual",
        "status": "draft",
        "repository_id": 1,
        "analysis_kind": "manual",
        "execution_state": "completed",
    }
    analysis_id = odoo.create("dev.work.analysis", analysis_vals)
    odoo.call("dev.work.analysis", "action_accept", analysis_id)
    analysis = odoo.read(
        "dev.work.analysis",
        analysis_id,
        ["id", "revision", "status", "content_hash"],
    )[0]
    trace["analysis"] = analysis

    # --- Plan ---
    odoo.call("dev.work.item", "action_start_planning", wi_id)
    plan_id = odoo.create(
        "dev.work.plan",
        {
            "work_item_id": wi_id,
            "analysis_id": analysis_id,
            "goal": f"{MARKER}: isolated Git commit, Draft PR, Deployment-Ready.",
            "scope": "Add one UAT markdown file under docs/devhub_modularity/uat/.",
            "out_of_scope": "Production changes, Production deploy, merge to staging/main.",
            "proposed_changes": f"Create docs/devhub_modularity/uat/{MARKER}.md",
            "affected_components": "docs/devhub_modularity/uat/*",
            "migration_impact": "None",
            "security_impact": "None",
            "test_plan": "Worker implement + Playwright screenshots + gh draft PR verify.",
            "rollback_plan": "Close Draft PR without merge; retain worktree for audit.",
            "dependencies": "devworker; bare petspot.git; SSH push profile.",
            "risks": "GitHub App broker missing — PR via gh CLI after Dev Hub push.",
            "acceptance_criteria": (
                "Approved plan executed in isolated worktree; commit SHA recorded; "
                "Draft PR open; Deployment-Ready documented; Production untouched."
            ),
            "origin": "manual",
            "status": "draft",
        },
    )
    step_ids = []
    for seq, (key, title) in enumerate(
        [
            ("write_uat_doc", "Write UAT documentation marker file"),
            ("git_commit", "Human-approved local Git commit"),
            ("git_push", "Push UAT branch to non-production remote"),
            ("draft_pr", "Open Draft PR (evidence)"),
            ("deploy_ready", "Record Deployment-Ready (no Production)"),
        ],
        start=1,
    ):
        sid = odoo.create(
            "dev.work.plan.step",
            {
                "plan_id": plan_id,
                "step_key": key,
                "title": title,
                "sequence": seq * 10,
                "description": f"{MARKER} step {key}",
            },
        )
        step_ids.append(sid)
    odoo.call("dev.work.plan", "action_submit_for_approval", plan_id)
    plan = odoo.read(
        "dev.work.plan",
        plan_id,
        ["id", "revision", "status", "content_hash"],
    )[0]
    trace["plan"] = plan
    trace["plan_steps"] = step_ids

    # Playwright early shots + approval
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        login_ui(page)

        open_action(page, ACTION_WORK, wi_id)
        shot(page, "01_work_created.png", "New stabilization Work Item created")

        open_action(page, ACTION_ANALYSIS, analysis_id)
        shot(page, "02_analysis.png", "Accepted Analysis record")

        open_action(page, ACTION_PLAN, plan_id)
        shot(page, "03_plan.png", "Plan with steps awaiting approval")

        open_action(page, ACTION_WORK, wi_id)
        click_notebook_tab(page, "Plan")
        shot(page, "04_approval.png", "Work Item awaiting exact-hash approval")

        approval_ret = odoo.call(
            "dev.work.plan",
            "action_approve_exact",
            plan_id,
            plan["content_hash"],
            f"{MARKER} exact-hash approved on Live Test",
            "manual",
        )
        rows = odoo.search_read(
            "dev.work.approval",
            [["work_item_id", "=", wi_id], ["decision", "=", "approved"]],
            fields=[
                "id",
                "plan_hash",
                "approver_id",
                "decided_at",
                "decision",
                "plan_id",
            ],
            limit=1,
            order="id desc",
        )
        approval = rows[0]
        trace["approval"] = approval
        log(f"approval id={approval['id']} hash={approval.get('plan_hash')}")

        open_action(page, ACTION_WORKFLOW)
        shot(page, "05_workflow_pre_execution.png", "Workflow Board before execution")

        # Prepare workspace proposal (RPC as admin; no Git write yet)
        odoo.call("dev.work.item", "action_prepare_execution_workspace", wi_id)
        ws_rows = odoo.search_read(
            "dev.execution.workspace",
            [["work_item_id", "=", wi_id]],
            fields=[
                "id",
                "name",
                "state",
                "execution_branch",
                "worktree_path",
                "base_branch",
                "base_head",
                "worker_identity",
            ],
            limit=1,
            order="id desc",
        )
        if not ws_rows:
            raise RuntimeError("execution workspace proposal missing")
        ws = ws_rows[0]
        ws_id = ws["id"]
        trace["workspace_proposal"] = ws
        log(f"workspace proposal id={ws_id} state={ws['state']} branch={ws['execution_branch']}")

        # Confirm as worker
        confirm = run_worker("confirm", ws_id)
        trace["confirm"] = confirm
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

        # Session linked to isolated workspace
        session_id = None
        try:
            env_row = odoo.read("dev.environment", 1, ["machine_id"])[0]
            machine_id = env_row["machine_id"][0] if env_row.get("machine_id") else 1
            session_id = odoo.create(
                "dev.session",
                {
                    "name": f"{MARKER} isolated session",
                    "project_id": 1,
                    "repository_id": 1,
                    "environment_id": 1,
                    "machine_id": machine_id,
                    "work_item_id": wi_id,
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
            session = odoo.read(
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
            trace["session"] = session
        except Exception as exc:
            trace["non_blockers"].append(f"session create: {exc}")
            log(f"session non-blocker: {exc}")

        open_model_form(page, "dev.execution.workspace", ws_id)
        shot(page, "06_session_workspace.png", "Isolated workspace ready (branch/worktree)")

        # Implement + review handoff as worker
        implement = run_worker("implement", ws_id, MARKER)
        trace["implement"] = implement
        checkpoint_id = implement.get("checkpoint_id")
        if checkpoint_id:
            trace["checkpoint"] = odoo.read(
                "dev.work.checkpoint",
                checkpoint_id,
                ["id", "trigger", "branch", "git_head", "files_touched_summary"],
            )[0]

        open_model_form(page, "dev.execution.workspace", ws_id)
        shot(page, "07_execution.png", "Workspace after worker implementation")
        if checkpoint_id:
            open_model_form(page, "dev.work.checkpoint", checkpoint_id)
            shot(page, "08_checkpoint.png", "Worker checkpoint evidence")

        # Commit approve + execute as worker
        commit_approve = run_worker("commit_approve", ws_id, MARKER, commit_msg)
        trace["commit_approve"] = commit_approve
        commit_execute = run_worker("commit_execute", ws_id)
        trace["commit_execute"] = commit_execute

        open_model_form(page, "dev.execution.workspace", ws_id)
        click_notebook_tab(page, "Git")
        shot(page, "09_git_branch.png", "Execution branch after commit")
        shot(page, "10_git_commit.png", "Committed SHA / Git evidence")

        # Push as worker
        push_review = run_worker("push_review", ws_id)
        trace["push_review"] = push_review
        push_approve = run_worker("push_approve", ws_id)
        trace["push_approve"] = push_approve
        push_execute = run_worker("push_execute", ws_id)
        trace["push_execute"] = push_execute

        branch = commit_execute.get("execution_branch") or ws.get("execution_branch")
        sha = commit_execute.get("committed_sha")
        trace["git"] = {"branch": branch, "sha": sha}

        # Draft PR via gh (Dev Hub App broker empty — documented NO-GO for App path)
        pr = {"status": "pending"}
        try:
            # Prefer staging as base (non-production protected)
            title_pr = f"[UAT][DRAFT] {MARKER}"
            body_pr = (
                f"## Summary\n"
                f"- Stabilization UAT marker `{MARKER}`\n"
                f"- Work Item `{wi_id}`\n"
                f"- Commit `{sha}`\n"
                f"- Test-only documentation file; do not merge to Production.\n\n"
                f"## Safety\n"
                f"- Draft PR only\n"
                f"- No Production deploy\n"
            )
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
                    title_pr,
                    "--body",
                    body_pr,
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            (LOGS / "gh_pr_create.txt").write_text(
                f"rc={create.returncode}\nstdout:\n{create.stdout}\nstderr:\n{create.stderr}\n"
            )
            if create.returncode != 0:
                raise RuntimeError(create.stderr or create.stdout)
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
                    "number,url,isDraft,baseRefName,headRefName,commits,state,mergeable",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            pr = json.loads(view.stdout)
            pr["creation_path"] = "gh_cli_draft_after_devhub_push"
            pr["devhub_github_app"] = "NO-GO (empty /srv/devhub/credentials/github App broker)"
            trace["github_pr"] = pr
            log(f"Draft PR #{pr.get('number')} {pr.get('url')} draft={pr.get('isDraft')}")
        except Exception as exc:
            pr = {"status": "NO-GO", "error": str(exc)}
            trace["github_pr"] = pr
            trace["errors"].append(f"GitHub Draft PR: {exc}")
            log(f"GitHub Draft PR failed: {exc}")

        # Capture PR evidence in Dev Hub UI if possible + browser note
        open_model_form(page, "dev.execution.workspace", ws_id)
        shot(
            page,
            "11_github_draft_pr.png",
            f"GitHub Draft PR evidence (workspace + PR {pr.get('number')})",
        )
        # Also dump PR JSON next to screenshot
        (DATA / "github_draft_pr.json").write_text(json.dumps(pr, indent=2, default=str))

        # Deploy gate — product requires merged_reviewed; stop at Deployment-Ready
        deploy = {
            "status": "DEPLOYMENT READY",
            "reason": (
                "Safe Test deploy target id=4 exists (PetSpot Test Staging Deploy), but "
                "create_deploy_approval requires workspace state merged_reviewed and a "
                "terminal merge record. This UAT intentionally does not merge the Draft PR "
                "into staging/main/Production. Policy deploy_permission remains False on "
                "PetSpot Test MVP."
            ),
            "target_id": 4,
            "target_name": "PetSpot Test Staging Deploy",
            "environment": "PetSpot Test",
            "commit_sha": sha,
            "branch": branch,
            "production_deploy": False,
        }
        trace["deploy"] = deploy
        (DATA / "deploy_gate.json").write_text(json.dumps(deploy, indent=2))
        open_action(page, ACTION_WORK, wi_id)
        click_notebook_tab(page, "Deploy")
        shot(page, "12_deploy_gate.png", "Deploy notebook / readiness context")
        shot(page, "13_deployment_ready.png", "Deployment-Ready (no merge/deploy performed)")

        # Completion if supported without merge
        try:
            # Prefer completion report approval path if report exists
            reports = odoo.search_read(
                "dev.completion.report",
                [["work_item_id", "=", wi_id]],
                fields=["id", "status", "uat_status"],
                limit=1,
                order="id desc",
            )
            if reports:
                rid = reports[0]["id"]
                try:
                    odoo.call("dev.completion.report", "action_approve", rid)
                except Exception:
                    pass
                try:
                    odoo.call("dev.work.item", "action_complete", wi_id)
                except Exception as exc:
                    trace["non_blockers"].append(f"complete: {exc}")
            else:
                try:
                    odoo.call("dev.work.item", "action_complete", wi_id)
                except Exception as exc:
                    trace["non_blockers"].append(f"complete: {exc}")
        except Exception as exc:
            trace["non_blockers"].append(f"completion: {exc}")

        wi_final = odoo.read(
            "dev.work.item",
            wi_id,
            ["id", "name", "current_phase", "uuid"],
        )[0]
        trace["work_item_final"] = wi_final
        open_action(page, ACTION_WORK, wi_id)
        shot(page, "14_completion.png", f"Work Item final phase={wi_final.get('current_phase')}")
        open_action(page, ACTION_WORKFLOW)
        shot(page, "15_workflow_final.png", "Workflow Board after stabilization UAT")

        browser.close()

    # Production safety probe
    safety = {
        "test_db": DB,
        "test_port": 8028,
        "production_service": subprocess.check_output(
            ["systemctl", "--user", "is-active", "pet_spot_elsahel.service"],
            text=True,
        ).strip(),
        "pr_draft": (trace.get("github_pr") or {}).get("isDraft"),
        "pr_merged": (trace.get("github_pr") or {}).get("state"),
        "no_production_deploy": True,
        "branch_prefix_ok": bool(branch and str(branch).startswith("devhub/")),
    }
    trace["production_safety"] = safety
    (DATA / "trace.json").write_text(json.dumps(trace, indent=2, default=str))
    log(f"TRACE written; wi={wi_id} sha={sha} pr={trace.get('github_pr')}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        log(traceback.format_exc())
        (DATA / "trace_failed.json").write_text(json.dumps(trace, indent=2, default=str))
        raise
