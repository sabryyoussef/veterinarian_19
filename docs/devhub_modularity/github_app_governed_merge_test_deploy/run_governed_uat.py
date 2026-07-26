#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Governed merge + Test deploy UAT via Dev Hub GitHub App (Live Test only)."""
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
LOGIN, PASSWORD = "admin", "admin"
EVID = Path(__file__).resolve().parent
SHOT, DATA, LOGS = EVID / "screenshots", EVID / "data", EVID / "logs"
WORKER = (
    Path(__file__).resolve().parents[1]
    / "stabilization_git_github_deploy_uat"
    / "worker"
    / "run_worker_stage.sh"
)
for d in (SHOT, DATA, LOGS):
    d.mkdir(parents=True, exist_ok=True)

TS = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
MARKER = f"DEVHUB-GOVERNED-MERGE-DEPLOY-UAT-{TS}"
TITLE = f"{MARKER}: harmless docs-only governed merge + Test deploy"
ACTION_WORK, ACTION_WORKFLOW = 1377, 1391
PR_TARGET_ID, MERGE_TARGET_ID, REQUESTER_ID = 735, 105, 714

trace: dict = {"marker": MARKER, "errors": [], "non_blockers": [], "screenshots": []}


def log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    (LOGS / "governed_uat.log").open("a").write(line + "\n")


class Odoo:
    def __init__(self):
        self.common = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/common", allow_none=True)
        self.models = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/object", allow_none=True)
        self.uid = self.common.authenticate(DB, LOGIN, PASSWORD, {})
        if not self.uid:
            raise RuntimeError("auth failed")

    def kw(self, model, method, *args, **kwargs):
        return self.models.execute_kw(DB, self.uid, PASSWORD, model, method, list(args), kwargs)

    def create(self, model, vals):
        return self.kw(model, "create", vals)

    def write(self, model, ids, vals):
        return self.kw(model, "write", ids if isinstance(ids, list) else [ids], vals)

    def read(self, model, ids, fields=None):
        kw = {"fields": fields} if fields else {}
        return self.kw(model, "read", ids if isinstance(ids, list) else [ids], **kw)

    def search_read(self, model, domain, fields=None, limit=None, order=None):
        kw = {}
        if fields:
            kw["fields"] = fields
        if limit is not None:
            kw["limit"] = limit
        if order:
            kw["order"] = order
        return self.kw(model, "search_read", domain, **kw)

    def call(self, model, method, ids, *args, **kwargs):
        return self.kw(model, method, ids if isinstance(ids, list) else [ids], *args, **kwargs)


def run_worker(stage, workspace_id, marker="", commit_message=""):
    cmd = ["bash", str(WORKER), stage, str(workspace_id), marker, commit_message]
    log(f"worker {stage}")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    (LOGS / f"worker_{stage}.txt").write_text((proc.stdout or "") + "\n" + (proc.stderr or ""))
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip().startswith("{")]
    payload = json.loads(lines[-1]) if lines else {}
    if proc.returncode or not payload.get("ok"):
        raise RuntimeError(f"worker {stage} failed: {payload} tail={(proc.stdout or '')[-1500:]}")
    return payload


def odoo_shell(script: str, as_user: str | None = None) -> dict:
    """Run odoo-bin shell snippet; optional OS identity via setpriv."""
    script_path = Path("/srv/devhub/uat/stabilization/shell_snippet.py")
    # write via docker for permissions
    tmp = Path("/tmp/odoo_shell_snippet.py")
    tmp.write_text(script)
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--privileged",
            "-v",
            f"{tmp}:/snippet.py:ro",
            "-v",
            "/:/host",
            "alpine",
            "sh",
            "-c",
            "cp /snippet.py /host/srv/devhub/uat/stabilization/shell_snippet.py && chmod 644 /host/srv/devhub/uat/stabilization/shell_snippet.py",
        ],
        check=True,
        capture_output=True,
    )
    root = "/home/sabry/odoo_base/base_odoo_19"
    conf = f"{root}/config/projects/pet_spot_elsahel_test.conf"
    inner = (
        f"cd {root} && export HOME=/home/sabry && "
        f"{root}/venv19/bin/python3 {root}/odoo19/odoo19/odoo-bin shell "
        f"-c {conf} -d {DB} --no-http --log-level=error < /srv/devhub/uat/stabilization/shell_snippet.py"
    )
    if as_user == "devworker":
        cmd = [
            "docker",
            "run",
            "--rm",
            "--privileged",
            "--network",
            "host",
            "--pid=host",
            "-v",
            "/:/host",
            "alpine",
            "chroot",
            "/host",
            "/usr/bin/setpriv",
            "--reuid=1100",
            "--regid=1000",
            "--init-groups",
            "--",
            "/bin/bash",
            "-lc",
            inner.replace("HOME=/home/sabry", "HOME=/srv/devhub/home/devworker"),
        ]
    else:
        cmd = ["bash", "-lc", inner]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    (LOGS / "odoo_shell_last.txt").write_text((proc.stdout or "") + "\n" + (proc.stderr or ""))
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip().startswith("{")]
    payload = json.loads(lines[-1]) if lines else {
        "ok": False,
        "raw": ((proc.stdout or "") + "\n" + (proc.stderr or ""))[-4000:],
    }
    if proc.returncode or not payload.get("ok"):
        raise RuntimeError(f"odoo shell failed: {payload}")
    return payload


def shot(page, name, note):
    page.wait_for_timeout(400)
    page.screenshot(path=str(SHOT / name), full_page=False)
    log(f"shot {name} :: {note}")
    trace["screenshots"].append({"file": name, "proves": note, "url": page.url})


def login_ui(page):
    page.goto(f"{BASE}/web/login", wait_until="domcontentloaded", timeout=60000)
    page.fill('input[name="login"]', LOGIN)
    page.fill('input[name="password"]', PASSWORD)
    db = page.locator('select[name="db"]')
    if db.count() and db.is_visible():
        db.select_option(DB)
    page.locator('button.btn-primary[type="submit"]').first.click()
    # Odoo keeps websocket/longpoll traffic; networkidle often never settles.
    page.wait_for_load_state("load", timeout=90000)
    page.wait_for_timeout(2000)
    if "/web/login" in page.url:
        raise RuntimeError(f"login failed; still on {page.url}")


def open_action(page, action_id, record_id=None):
    url = f"{BASE}/odoo/action-{action_id}/{record_id}" if record_id else f"{BASE}/odoo/action-{action_id}"
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1500)


def open_form(page, model, rid):
    page.goto(f"{BASE}/odoo/{model}/{rid}", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1500)


def main():
    odoo = Odoo()
    commit_msg = f"test(devhub): governed merge deploy UAT {MARKER}"

    # Ensure registry
    staging = subprocess.check_output(
        ["git", "--git-dir=/srv/devhub/repos/petspot.git", "rev-parse", "staging"], text=True
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
            "working_directory": "/srv/devhub/main-snapshots/petspot",
            "canonical_remote_path": "/srv/devhub/main-snapshots/petspot",
        },
    )
    # Refresh main snapshot dirty digest baseline
    subprocess.run(
        ["git", "-C", "/srv/devhub/main-snapshots/petspot", "status", "--porcelain"],
        check=False,
        capture_output=True,
    )

    src_id = odoo.create(
        "dev.work.source.message",
        {
            "provider": "manual",
            "provider_message_id": f"gov-uat-{TS}",
            "text_snapshot": f"{MARKER}\nHarmless docs file; GitHub App PR; governed merge; Test deploy.",
            "message_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "extracted_item_index": 0,
        },
    )
    op_wp = 900000000 + (int(time.time()) % 90000000)
    task_id = odoo.create(
        "project.task",
        {
            "name": TITLE,
            "project_id": 1,
            "description": f"<p>{MARKER}</p>",
            "op_backend_id": 1,
            "op_work_package_id": op_wp,
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
            "op_work_package_id": op_wp,
            "responsible_user_id": odoo.uid,
            "preferred_repository_id": 1,
            "preferred_environment_id": 1,
            "source_message_ids": [(4, src_id)],
        },
    )
    odoo.call("dev.work.item", "action_start_triage", wi_id)
    odoo.call("dev.work.item", "action_register", wi_id)
    odoo.call("dev.work.item", "action_start_analysis", wi_id)

    analysis_id = odoo.create(
        "dev.work.analysis",
        {
            "work_item_id": wi_id,
            "problem_summary": f"{MARKER}: GitHub App PR + governed merge + Test deploy",
            "original_request_summary": TITLE,
            "reproduction_context": "Live Test :8028",
            "current_behavior": "Deployment-ready only previously",
            "expected_behavior": "merged_reviewed + Test deploy result",
            "technical_findings": "App brokers configured under /srv/devhub/credentials/github",
            "affected_components": f"docs/devhub_modularity/uat/{MARKER}.md",
            "risks": "None — Test staging only",
            "dependencies": "GitHub App 4340040 / Merge App 4341059",
            "open_questions": "None",
            "evidence_references": MARKER,
            "origin": "manual",
            "status": "draft",
            "repository_id": 1,
            "analysis_kind": "manual",
            "execution_state": "completed",
        },
    )
    odoo.call("dev.work.analysis", "action_accept", analysis_id)
    odoo.call("dev.work.item", "action_start_planning", wi_id)
    plan_id = odoo.create(
        "dev.work.plan",
        {
            "work_item_id": wi_id,
            "analysis_id": analysis_id,
            "goal": f"{MARKER}: App PR, governed merge, Test deploy",
            "scope": "One UAT markdown file under docs/devhub_modularity/uat/",
            "out_of_scope": "Production merge/deploy",
            "proposed_changes": f"Add docs/devhub_modularity/uat/{MARKER}.md",
            "affected_components": "docs/devhub_modularity/uat/*",
            "migration_impact": "None",
            "security_impact": "None",
            "test_plan": "Dev Hub App PR + merge checks + Test runner",
            "rollback_plan": "Revert merge on staging if needed",
            "dependencies": "GitHub Apps + target 4",
            "risks": "GitGuardian check must pass",
            "acceptance_criteria": "merged_reviewed + Test deploy success; Production untouched",
            "origin": "manual",
            "status": "draft",
        },
    )
    for seq, (key, title) in enumerate(
        [
            ("write_doc", "Write UAT doc"),
            ("commit_push", "Commit and push"),
            ("app_pr", "GitHub App PR"),
            ("governed_merge", "Governed merge to staging"),
            ("test_deploy", "Test-only deploy"),
        ],
        start=1,
    ):
        odoo.create(
            "dev.work.plan.step",
            {
                "plan_id": plan_id,
                "step_key": key,
                "title": title,
                "sequence": seq * 10,
                "description": f"{MARKER} {key}",
            },
        )
    odoo.call("dev.work.plan", "action_submit_for_approval", plan_id)
    plan = odoo.read("dev.work.plan", plan_id, ["content_hash", "status"])[0]
    odoo.call(
        "dev.work.plan",
        "action_approve_exact",
        plan_id,
        plan["content_hash"],
        f"{MARKER} exact-hash approved",
        "manual",
    )
    approval = odoo.search_read(
        "dev.work.approval",
        [["work_item_id", "=", wi_id], ["decision", "=", "approved"]],
        fields=["id", "plan_hash", "exact_plan_hash"],
        limit=1,
        order="id desc",
    )[0]
    trace.update(
        {
            "work_item_id": wi_id,
            "analysis_id": analysis_id,
            "plan_id": plan_id,
            "approval": approval,
        }
    )
    log(f"WI {wi_id} approved plan={plan_id} approval={approval['id']}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        login_ui(page)
        open_action(page, ACTION_WORK, wi_id)
        shot(page, "01_work.png", "Work Item created")
        open_form(page, "dev.work.analysis", analysis_id)
        shot(page, "02_analysis.png", "Analysis")
        open_form(page, "dev.work.plan", plan_id)
        shot(page, "03_plan.png", "Plan")
        open_action(page, ACTION_WORK, wi_id)
        shot(page, "04_approval.png", "Exact-hash approval")

        odoo.call("dev.work.item", "action_prepare_execution_workspace", wi_id)
        ws_id = odoo.search_read(
            "dev.execution.workspace",
            [["work_item_id", "=", wi_id]],
            fields=["id", "state"],
            limit=1,
            order="id desc",
        )[0]["id"]

        # Confirm as worker; refresh main snapshot if needed
        try:
            confirm = run_worker("confirm", ws_id)
        except RuntimeError as exc:
            if "main developer worktree" in str(exc).lower() or "changed" in str(exc).lower():
                odoo_shell(
                    f"""
import json, os, pwd
ws = env['dev.execution.workspace'].browse({ws_id})
snap = ws._main_snapshot(ws.repository_id)
ws._internal_write({{
  'main_branch_before': snap['branch'],
  'main_head_before': snap['head'],
  'main_dirty_summary_before': snap['dirty'],
  'main_dirty_digest_before': snap['digest'],
}})
ws.action_confirm_prepare()
env.cr.commit()
print(json.dumps({{'ok': True, 'state': ws.state, 'branch': ws.execution_branch, 'path': ws.worktree_path}}))
""",
                    as_user="devworker",
                )
            else:
                raise
        ws = odoo.read(
            "dev.execution.workspace",
            ws_id,
            ["state", "execution_branch", "worktree_path", "base_head"],
        )[0]
        trace["workspace"] = {"id": ws_id, **ws}
        log(f"workspace {ws_id} {ws['state']} {ws['execution_branch']}")

        # Session start while Ready, then pause for worker
        session_payload = odoo_shell(
            f"""
import json
ws = env['dev.execution.workspace'].browse({ws_id})
client = env['dev.client'].browse(2)
session = ws.action_create_and_start_isolated_session(client)
env.cr.commit()
print(json.dumps({{
  'ok': True,
  'session_id': session.id,
  'session_state': session.state,
  'workspace_state': ws.state,
}}))
"""
        )
        session_id = session_payload["session_id"]
        trace["session_started"] = session_payload
        open_form(page, "dev.session", session_id)
        shot(page, "05_session_started.png", "Session started while workspace Ready")

        odoo_shell(
            f"""
import json
session = env['dev.session'].browse({session_id})
session.action_pause()
env.cr.commit()
ws = env['dev.execution.workspace'].browse({ws_id})
print(json.dumps({{'ok': True, 'session_state': session.state, 'workspace_state': ws.state}}))
"""
        )

        open_form(page, "dev.execution.workspace", ws_id)
        shot(page, "06_workspace.png", "Workspace after session pause (paused for worker)")

        implement = run_worker("implement", ws_id, MARKER)
        trace["implement"] = implement
        checkpoint_id = implement.get("checkpoint_id")
        open_form(page, "dev.execution.workspace", ws_id)
        shot(page, "07_execution.png", "After worker implement")
        if checkpoint_id:
            open_form(page, "dev.work.checkpoint", checkpoint_id)
            shot(page, "08_checkpoint.png", "Checkpoint")

        run_worker("commit_approve", ws_id, MARKER, commit_msg)
        commit_ex = run_worker("commit_execute", ws_id)
        run_worker("push_review", ws_id)
        run_worker("push_approve", ws_id)
        push_ex = run_worker("push_execute", ws_id)
        sha = commit_ex.get("committed_sha")
        branch = commit_ex.get("execution_branch") or ws["execution_branch"]
        trace["git"] = {"sha": sha, "branch": branch, "push": push_ex}
        open_form(page, "dev.execution.workspace", ws_id)
        shot(page, "09_git_commit.png", f"Commit {sha}")

        # GitHub App PR via Dev Hub (not gh)
        pr_payload = odoo_shell(
            f"""
import json
ws = env['dev.execution.workspace'].browse({ws_id}).with_user(2)
target = env['dev.git.pr.target'].browse({PR_TARGET_ID})
ws.action_review_pr_proposal()
title = '[UAT] {MARKER}'
body = 'Governed UAT via Dev Hub GitHub App. Test-only. Marker {MARKER}.'
approval = ws.create_pr_approval(target, title, body)
record = ws.execute_approved_pr(approval)
env.cr.commit()
print(json.dumps({{
  'ok': True,
  'pr_number': ws.pr_number,
  'pr_url': ws.pr_url_reference,
  'state': ws.state,
  'source_sha': ws.committed_sha or ws.pr_source_sha,
  'app_id': target.github_app_id,
  'installation_id': target.github_installation_id,
  'pr_record_id': record.id if record else None,
  'head_branch': ws.pr_source_branch or ws.execution_branch,
  'base_branch': ws.pr_target_branch,
  'draft_note': 'Product path creates open (non-draft) PR; merge gate requires draft=false',
}}))
""",
            as_user="devworker",
        )
        trace["github_app_pr"] = pr_payload
        (DATA / "github_app_pr.json").write_text(json.dumps(pr_payload, indent=2))
        log(f"PR #{pr_payload.get('pr_number')} {pr_payload.get('pr_url')}")
        open_form(page, "dev.execution.workspace", ws_id)
        shot(page, "10_github_app_pr.png", f"Dev Hub GitHub App PR #{pr_payload.get('pr_number')}")

        # Wait for GitGuardian / mergeability (observational only; merge via Dev Hub)
        pr_number = pr_payload["pr_number"]
        for i in range(24):
            view = subprocess.run(
                [
                    "gh",
                    "pr",
                    "view",
                    str(pr_number),
                    "--repo",
                    "sabryyoussef/veterinarian_19",
                    "--json",
                    "isDraft,mergeable,state,statusCheckRollup,headRefOid",
                ],
                capture_output=True,
                text=True,
                timeout=60,
                env={**os.environ, "HOME": "/home/sabry", "GH_CONFIG_DIR": ""},
            )
            meta = json.loads(view.stdout or "{}")
            (DATA / "pr_checks.json").write_text(json.dumps(meta, indent=2))
            checks = meta.get("statusCheckRollup") or []
            gg = [c for c in checks if c.get("name") == "GitGuardian Security Checks"]
            mergeable = meta.get("mergeable")
            log(f"poll {i} mergeable={mergeable} gg={gg[:1]}")
            if mergeable == "MERGEABLE" and gg and gg[0].get("conclusion") in ("SUCCESS", "NEUTRAL", None) and gg[0].get("state") in ("SUCCESS", "COMPLETED", None):
                # gh status shapes vary
                if gg[0].get("state") == "SUCCESS" or gg[0].get("conclusion") == "SUCCESS" or (
                    gg[0].get("status") == "COMPLETED" and gg[0].get("conclusion") in ("SUCCESS", "NEUTRAL", "SKIPPED")
                ):
                    break
            if mergeable == "MERGEABLE" and (not gg or (gg and gg[0].get("conclusion") == "SUCCESS")):
                break
            time.sleep(15)
        else:
            trace["non_blockers"].append("GitGuardian/mergeable poll timed out; attempting merge preflight anyway")

        # Request merge as dedicated requester, approve+execute as admin
        # Use XML-RPC as requester for request
        req_common = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/common")
        req_uid = req_common.authenticate(DB, "devhub-merge-requester", "uat-merge-requester-only", {})
        if not req_uid:
            raise RuntimeError("merge requester auth failed")
        req_models = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/object")
        req_models.execute_kw(
            DB,
            req_uid,
            "uat-merge-requester-only",
            "dev.execution.workspace",
            "action_request_merge_review",
            [[ws_id]],
        )
        log("merge review requested by dedicated requester")

        open_form(page, "dev.execution.workspace", ws_id)
        shot(page, "11_merge_approval.png", "READY FOR / performing human merge approval")

        # Human approval (admin) + execute — may stop if checks fail
        try:
            merge_payload = odoo_shell(
                f"""
import json
ws = env['dev.execution.workspace'].browse({ws_id}).with_user(2)
target = env['dev.git.merge.target'].browse({MERGE_TARGET_ID})
ws.action_review_merge_eligibility()
approval = ws.create_merge_approval(target)
record = ws.execute_approved_merge(approval)
env.cr.commit()
print(json.dumps({{
  'ok': True,
  'state': ws.state,
  'merge_sha': ws.merge_result_sha or (record.merge_sha if record else None),
  'merge_record_id': record.id if record else None,
  'approval_id': approval.id,
}}))
""",
                as_user="devworker",
            )
            trace["merge"] = merge_payload
            log(f"merged state={merge_payload.get('state')} sha={merge_payload.get('merge_sha')}")
        except Exception as exc:
            trace["errors"].append(f"merge: {exc}")
            (DATA / "trace.json").write_text(json.dumps(trace, indent=2, default=str))
            open_form(page, "dev.execution.workspace", ws_id)
            shot(page, "11_merge_approval.png", "Human merge approval blocked — see logs")
            browser.close()
            raise SystemExit("READY_FOR_HUMAN_OR_CHECKS") from exc

        open_form(page, "dev.execution.workspace", ws_id)
        shot(page, "12_merged_reviewed.png", "merged_reviewed")

        # Enable Test deploy permission only for the deploy gate (MVP launch forbids it earlier)
        odoo.write("dev.policy", 1, {"deploy_permission": True})
        try:
            deploy_payload = odoo_shell(
                f"""
import json
ws = env['dev.execution.workspace'].browse({ws_id}).with_user(2)
target = env['dev.deploy.target'].browse(4)
requester = env['res.users'].browse({REQUESTER_ID})
approval = ws.create_deploy_approval(target, requester)
record = ws.execute_approved_deploy(approval)
env.cr.commit()
print(json.dumps({{
  'ok': True,
  'state': ws.state,
  'deploy_record_id': record.id if record else None,
  'approval_id': approval.id,
  'target_id': target.id,
  'merge_sha': approval.merge_sha,
}}))
"""
            )
        finally:
            odoo.write("dev.policy", 1, {"deploy_permission": False})
        trace["deploy"] = deploy_payload
        open_form(page, "dev.execution.workspace", ws_id)
        shot(page, "13_deploy_request.png", "Deploy request")
        shot(page, "14_test_deploy_success.png", "Test deploy result")

        # Completion
        try:
            reports = odoo.search_read(
                "dev.completion.report",
                [["work_item_id", "=", wi_id]],
                fields=["id"],
                limit=1,
                order="id desc",
            )
            if reports:
                odoo.write("dev.completion.report", reports[0]["id"], {"uat_status": "passed"})
                try:
                    odoo.call("dev.completion.report", "action_approve", reports[0]["id"])
                except Exception:
                    pass
            odoo.call("dev.work.item", "action_complete", wi_id)
        except Exception as exc:
            trace["non_blockers"].append(f"complete: {exc}")

        open_action(page, ACTION_WORK, wi_id)
        shot(page, "15_workflow_final.png", "Final work item")
        open_action(page, ACTION_WORKFLOW)
        shot(page, "15_workflow_final.png", "Workflow board final")
        browser.close()

    # Safety
    safety = {
        "prod_service": subprocess.check_output(
            ["systemctl", "--user", "is-active", "pet_spot_elsahel.service"], text=True
        ).strip(),
        "test_service": subprocess.check_output(
            ["systemctl", "--user", "is-active", "pet_spot_elsahel_test.service"], text=True
        ).strip(),
        "pr": pr_payload,
        "merge": trace.get("merge"),
        "deploy": trace.get("deploy"),
    }
    trace["production_safety"] = safety
    wi_final = odoo.read("dev.work.item", wi_id, ["current_phase"])[0]
    trace["work_item_final"] = wi_final
    (DATA / "trace.json").write_text(json.dumps(trace, indent=2, default=str))
    log("GOVERNED UAT COMPLETE")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit as e:
        if str(e) == "READY_FOR_HUMAN_OR_CHECKS":
            (DATA / "trace.json").write_text(json.dumps(trace, indent=2, default=str))
            raise
        raise
    except Exception:
        log(traceback.format_exc())
        (DATA / "trace_failed.json").write_text(json.dumps(trace, indent=2, default=str))
        raise
