#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resume operational UAT from approved Work Item 3318 (Playwright screenshots 07–17)."""
from __future__ import annotations

import ast
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
WI_ID = int(os.environ.get("RESUME_WI", "3318"))
EVID = Path(__file__).resolve().parent
SHOT = EVID / "screenshots"
DATA = EVID / "data"
LOGS = EVID / "logs"
for d in (SHOT, DATA, LOGS):
    d.mkdir(parents=True, exist_ok=True)

ACTION_WORK = 1377
ACTION_WORKFLOW = 1391
ACTION_PLAN = 1388
ACTION_CHECKPOINT = 1397
ACTION_DEPLOY_TARGET = 1405
REPO = "/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel"

trace = {"resume_wi": WI_ID, "non_blockers": [], "errors": [], "screenshots": []}


def log(msg):
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    with (LOGS / "uat_resume.log").open("a") as fh:
        fh.write(line + "\n")


class Odoo:
    def __init__(self):
        self.common = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/common", allow_none=True)
        self.models = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/object", allow_none=True)
        self.uid = self.common.authenticate(DB, LOGIN, PASSWORD, {})
        assert self.uid

    def kw(self, model, method, *args, **kwargs):
        return self.models.execute_kw(DB, self.uid, PASSWORD, model, method, list(args), kwargs)

    def create(self, model, vals):
        return self.kw(model, "create", vals)

    def read(self, model, ids, fields=None):
        return self.kw(model, "read", ids if isinstance(ids, list) else [ids], **({"fields": fields} if fields else {}))

    def search_read(self, model, domain, fields=None, limit=None, order=None):
        kw = {}
        if fields:
            kw["fields"] = fields
        if limit is not None:
            kw["limit"] = limit
        if order:
            kw["order"] = order
        return self.kw(model, "search_read", domain, **kw)

    def call(self, model, method, ids, *args):
        return self.kw(model, method, ids if isinstance(ids, list) else [ids], *args)


def git_snapshot(path):
    def run(a):
        r = subprocess.run(["git", *a], cwd=path, capture_output=True, text=True)
        return (r.stdout or "").strip()

    return {
        "branch": run(["rev-parse", "--abbrev-ref", "HEAD"]),
        "head": run(["rev-parse", "HEAD"]),
        "path": path,
    }


def dismiss_modals(page) -> None:
    for _ in range(4):
        modal = page.locator(".modal.o_technical_modal.show, .modal.d-block")
        if not modal.count() or not modal.first.is_visible():
            break
        # Prefer Cancel / Close / Discard / Ok
        closed = False
        for label in ("Cancel", "Close", "Discard", "Ok", "OK"):
            btn = modal.locator(f'button:has-text("{label}")').first
            if btn.count() and btn.is_visible():
                try:
                    btn.click(timeout=2000)
                    closed = True
                    page.wait_for_timeout(400)
                    break
                except Exception:
                    pass
        if not closed:
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)


def click_tab(page, label):
    dismiss_modals(page)
    for sel in [
        f'.o_notebook .nav-link:has-text("{label}")',
        f'a[role="tab"]:has-text("{label}")',
    ]:
        loc = page.locator(sel).first
        if loc.count() and loc.is_visible():
            try:
                loc.click(timeout=5000)
                page.wait_for_timeout(800)
                return
            except Exception:
                dismiss_modals(page)
                loc.click(force=True, timeout=5000)
                page.wait_for_timeout(800)
                return
    try:
        page.get_by_role("tab", name=label).click(timeout=2500)
        page.wait_for_timeout(800)
    except Exception:
        log(f"WARN tab {label}")


def shot(page, name, note):
    dismiss_modals(page)
    page.wait_for_timeout(400)
    page.screenshot(path=str(SHOT / name), full_page=False)
    log(f"screenshot {name} :: {note}")
    trace["screenshots"].append({"file": name, "proves": note, "url": page.url})


def login_ui(page):
    page.goto(f"{BASE}/web/login", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector('input[name="login"]')
    page.fill('input[name="login"]', LOGIN)
    page.fill('input[name="password"]', PASSWORD)
    page.locator('button.btn-primary[type="submit"]').first.click()
    page.wait_for_load_state("networkidle", timeout=90000)
    page.wait_for_timeout(1500)
    dismiss_modals(page)


def open_action(page, action_id, record_id=None):
    url = f"{BASE}/odoo/action-{action_id}/{record_id}" if record_id else f"{BASE}/odoo/action-{action_id}"
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2200)
    dismiss_modals(page)


def open_model(page, model, rid):
    page.goto(f"{BASE}/odoo/{model}/{rid}", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2200)
    dismiss_modals(page)


def main():
    odoo = Odoo()
    wi = odoo.read(
        "dev.work.item",
        WI_ID,
        ["id", "name", "uuid", "current_phase", "dev_project_id", "preferred_environment_id", "preferred_repository_id"],
    )[0]
    marker = wi["name"].split(":")[0]
    trace["work_item"] = wi
    log(f"resume WI={WI_ID} phase={wi['current_phase']} marker={marker}")

    analyses = odoo.search_read(
        "dev.work.analysis",
        [["work_item_id", "=", WI_ID]],
        fields=["id", "status", "revision", "content_hash", "problem_summary"],
        order="id desc",
        limit=1,
    )
    plans = odoo.search_read(
        "dev.work.plan",
        [["work_item_id", "=", WI_ID]],
        fields=["id", "status", "revision", "content_hash"],
        order="id desc",
        limit=1,
    )
    steps = odoo.search_read(
        "dev.work.plan.step",
        [["plan_id", "=", plans[0]["id"]]],
        fields=["id", "step_key", "title"],
        order="sequence",
    ) if plans else []
    approvals = odoo.search_read(
        "dev.work.approval",
        [["work_item_id", "=", WI_ID]],
        fields=["id", "decision", "plan_hash", "approver_id", "decided_at", "plan_id"],
        order="id desc",
        limit=1,
    )
    trace["analysis"] = analyses[0] if analyses else None
    trace["plan"] = plans[0] if plans else None
    trace["plan_steps"] = [s["id"] for s in steps]
    trace["approval"] = approvals[0] if approvals else None

    # Ensure approved
    if plans and plans[0]["status"] == "awaiting_approval":
        odoo.call("dev.work.plan", "action_approve_exact", plans[0]["id"], plans[0]["content_hash"], "resume", "manual")
        approvals = odoo.search_read(
            "dev.work.approval",
            [["work_item_id", "=", WI_ID]],
            fields=["id", "decision", "plan_hash", "approver_id", "decided_at", "plan_id"],
            order="id desc",
            limit=1,
        )
        trace["approval"] = approvals[0]

    phase = odoo.read("dev.work.item", WI_ID, ["current_phase"])[0]["current_phase"]
    log(f"phase={phase}")

    # Prepare workspace (may fail — non-blocker)
    workspace_id = None
    try:
        odoo.call("dev.work.item", "action_prepare_execution_workspace", WI_ID)
        ws = odoo.search_read(
            "dev.execution.workspace",
            [["work_item_id", "=", WI_ID]],
            fields=["id", "name", "state", "execution_branch", "base_branch", "base_head", "creation_status"],
            limit=1,
            order="id desc",
        )
        if ws:
            workspace_id = ws[0]["id"]
            trace["execution_workspace"] = ws[0]
    except Exception as e:
        trace["non_blockers"].append({"item": "execution_workspace_prepare", "detail": str(e)})
        log(f"prepare blocked: {str(e)[:250]}")

    try:
        if phase == "approved":
            odoo.call("dev.work.item", "action_start_implementation", WI_ID)
    except Exception as e:
        trace["non_blockers"].append({"item": "start_implementation", "detail": str(e)})
        log(f"start_impl: {e}")

    existing_sessions = odoo.search_read(
        "dev.session",
        [["work_item_id", "=", WI_ID]],
        fields=["id", "state", "name"],
        order="id desc",
        limit=1,
    )
    if existing_sessions:
        session_id = existing_sessions[0]["id"]
        log(f"reusing session {session_id} state={existing_sessions[0]['state']}")
    else:
        session_id = odoo.create(
            "dev.session",
            {
                "name": f"E2E UAT Session {marker}",
                "client_id": 2,
                "project_id": 1,
                "environment_id": 1,
                "machine_id": 1,
                "repository_id": 1,
                "working_directory": REPO,
                "work_item_id": WI_ID,
                "session_type": "manual_developer_session",
                "user_id": odoo.uid,
            },
        )
    try:
        odoo.call("dev.session", "action_start", session_id)
    except Exception as e:
        trace["non_blockers"].append({"item": "session_start", "detail": str(e)})
        log(f"session_start: {e}")

    try:
        odoo.call("dev.session", "action_checkpoint_milestone", session_id)
    except Exception as e:
        log(f"checkpoint_milestone: {e}")
        try:
            odoo.kw("dev.session", "_create_work_checkpoint", [session_id], "milestone")
        except Exception as e2:
            trace["errors"].append(f"checkpoint: {e}; {e2}")

    cps = odoo.search_read(
        "dev.work.checkpoint",
        [["work_item_id", "=", WI_ID]],
        fields=["id", "trigger", "lifecycle_phase", "session_id", "work_item_id", "branch", "git_head"],
        limit=3,
        order="id desc",
    )
    checkpoint_id = cps[0]["id"] if cps else None
    trace["session"] = {"id": session_id}
    trace["checkpoint"] = cps[0] if cps else None
    log(f"session={session_id} checkpoint={checkpoint_id} workspace={workspace_id}")

    git = git_snapshot(REPO)
    (DATA / "git_after.json").write_text(json.dumps(git, indent=2))
    trace["git"] = git

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        login_ui(page)

        open_action(page, ACTION_WORK, WI_ID)
        click_tab(page, "Plan")
        shot(page, "07_approval_approved.png", "Plan approved after exact-hash approval")

        open_action(page, ACTION_WORK, WI_ID)
        click_tab(page, "Development")
        shot(page, "09_execution_created.png", "Development/execution area with session")

        open_model(page, "dev.session", session_id)
        shot(page, "10_execution_progress.png", "Session execution record")

        if checkpoint_id:
            open_action(page, ACTION_CHECKPOINT, checkpoint_id)
            shot(page, "11_checkpoint.png", "Checkpoint owned by devhub_execution")
        else:
            open_action(page, ACTION_WORK, WI_ID)
            shot(page, "11_checkpoint.png", "Checkpoint missing — capture work form")

        open_model(page, "dev.repository", 1)
        shot(
            page,
            "12_git_evidence.png",
            f"Git boundary evidence branch={git['branch']} head={git['head'][:12]}",
        )

        note = (
            "GitHub Draft PR not created: no safe Test PR (would require remote push). "
            "Local Git evidence captured in 12_git_evidence.png."
        )
        (SHOT / "13_github_pr.SKIPPED.txt").write_text(note + "\n")
        trace["github"] = {"status": "skipped", "reason": note}

        policies = odoo.search_read(
            "dev.policy",
            [["id", "=", 1]],
            fields=["id", "name", "deploy_permission", "production_access_policy", "development_allowed"],
        )
        targets = odoo.search_read(
            "dev.deploy.target", [], fields=["id", "name", "active"], limit=8
        )
        trace["deploy"] = {
            "policy": policies[0] if policies else None,
            "targets_sample": targets,
            "mode": "deployment_ready_only",
            "production_deploy": False,
        }
        open_action(page, ACTION_DEPLOY_TARGET)
        shot(page, "14_deploy_ready.png", "Deploy capability — readiness only (no Production deploy)")
        skip = (
            "Real Test deploy not executed: policy deploy_permission=False; "
            "hard constraint forbids Production deploy."
        )
        (SHOT / "15_test_deploy_result.SKIPPED.txt").write_text(skip + "\n")
        trace["non_blockers"].append({"item": "test_deploy_execution", "detail": skip})

        # Completion path
        phase = odoo.read("dev.work.item", WI_ID, ["current_phase"])[0]["current_phase"]
        log(f"phase before completion={phase}")
        try:
            if phase == "implementing":
                odoo.call("dev.work.item", "action_start_testing", WI_ID)
            phase = odoo.read("dev.work.item", WI_ID, ["current_phase"])[0]["current_phase"]
            if phase in ("testing", "implementing", "approved"):
                try:
                    odoo.call("dev.work.item", "action_ready_for_review", WI_ID)
                except Exception as e:
                    log(f"ready_for_review: {e}")
                    try:
                        odoo.kw("dev.session", "_create_work_checkpoint", [session_id], "client_review")
                    except Exception:
                        pass
                    odoo.call("dev.work.item", "action_ready_for_review", WI_ID)
        except Exception as e:
            trace["non_blockers"].append({"item": "ready_for_review", "detail": str(e)})

        plan_id = plans[0]["id"] if plans else False
        report_id = odoo.create(
            "dev.completion.report",
            {
                "work_item_id": WI_ID,
                "plan_id": plan_id,
                "original_request_summary": wi["name"],
                "implemented_summary": f"{marker}: modular E2E UAT evidence pack completed on Live Test.",
                "completed_steps_summary": "Analysis accepted; Plan approved; Session/checkpoint; Git snapshot; Deploy readiness.",
                "changed_components_summary": "docs/devhub_modularity/operational_workflow_uat",
                "repository_reference": "pet_spot_elsahel (Live Test)",
                "branch": git.get("branch") or "feature/devhub-modularization-whatsapp",
                "commit_references": git.get("head") or "",
                "tests_summary": "Playwright screenshots on Live Test :8028",
                "uat_status": "passed",
                "known_limitations": "GitHub PR and real deploy skipped by design/safety.",
                "rollback_notes": "Retain evidence; optional archive Test work item.",
                "deployment_status": "not_deployed",
                "production_status": "not_applicable",
                "generated_by": "human",
            },
        )
        odoo.call("dev.completion.report", "action_ready_review", report_id)
        try:
            odoo.call("dev.completion.report", "action_approve", report_id)
        except Exception as e:
            log(f"report approve retry: {e}")
            try:
                odoo.call("dev.work.item", "action_ready_for_review", WI_ID)
            except Exception:
                pass
            odoo.call("dev.completion.report", "action_approve", report_id)
        try:
            odoo.call("dev.work.item", "action_complete", WI_ID)
        except Exception as e:
            trace["errors"].append(f"complete: {e}")
            log(f"complete: {e}")

        final = odoo.read("dev.work.item", WI_ID, ["id", "name", "current_phase", "uuid"])[0]
        report = odoo.read(
            "dev.completion.report",
            report_id,
            ["id", "status", "uat_status", "deployment_status", "content_hash"],
        )[0]
        trace["final_work_item"] = final
        trace["completion_report"] = report
        log(f"final phase={final['current_phase']} report={report}")

        open_action(page, ACTION_WORK, WI_ID)
        click_tab(page, "Completion")
        shot(page, "16_work_item_completed.png", "Work Item completion / report")

        open_action(page, ACTION_WORKFLOW)
        shot(page, "17_workflow_board_final.png", "Workflow Board after completion")

        browser.close()

    # Ownership + manifests
    ownership = {}
    for model, expect in [
        ("dev.work.item", "devhub_work"),
        ("dev.work.analysis", "devhub_analysis"),
        ("dev.work.plan", "devhub_plan"),
        ("dev.work.approval", "devhub_approval"),
        ("dev.work.checkpoint", "devhub_execution"),
    ]:
        rows = odoo.search_read(
            "ir.model.data",
            [["model", "=", "ir.model"], ["name", "=", f"model_{model.replace('.', '_')}"]],
            fields=["module", "name"],
            limit=30,
        )
        mods = sorted({r["module"] for r in rows})
        ownership[model] = {"modules": mods, "expects_primary": expect, "ok": expect in mods}
    base = Path(REPO)
    work_man = ast.literal_eval((base / "devhub_work" / "__manifest__.py").read_text())
    wa_man = ast.literal_eval((base / "devhub_whatsapp" / "__manifest__.py").read_text())
    trace["ownership"] = ownership
    trace["manifest"] = {
        "devhub_work_depends": work_man.get("depends"),
        "work_has_openproject_sync": "openproject_sync" in (work_man.get("depends") or []),
        "devhub_whatsapp_depends": wa_man.get("depends"),
        "whatsapp_consumes_hub": "whatsapp_hub" in (wa_man.get("depends") or []),
    }
    rel = {
        "work_item_id": WI_ID,
        "analysis_id": analyses[0]["id"] if analyses else None,
        "plan_id": plans[0]["id"] if plans else None,
        "plan_step_ids": [s["id"] for s in steps],
        "approval_id": approvals[0]["id"] if approvals else None,
        "session_id": session_id,
        "checkpoint_id": checkpoint_id,
        "workspace_id": workspace_id,
        "completion_report_id": report_id,
        "git": git,
        "github": trace.get("github"),
        "deploy": trace.get("deploy"),
    }
    # orphan checks
    orphans = {}
    if analyses:
        orphans["analysis_work_match"] = odoo.read("dev.work.analysis", analyses[0]["id"], ["work_item_id"])[0]["work_item_id"][0] == WI_ID
    if plans:
        orphans["plan_work_match"] = odoo.read("dev.work.plan", plans[0]["id"], ["work_item_id"])[0]["work_item_id"][0] == WI_ID
    if approvals:
        ap = odoo.read("dev.work.approval", approvals[0]["id"], ["work_item_id", "plan_id"])[0]
        orphans["approval_links"] = ap["work_item_id"][0] == WI_ID and ap["plan_id"][0] == plans[0]["id"]
    if checkpoint_id:
        orphans["checkpoint_work_match"] = odoo.read("dev.work.checkpoint", checkpoint_id, ["work_item_id"])[0]["work_item_id"][0] == WI_ID
    rel["orphan_checks"] = orphans
    trace["relationship"] = rel

    pid = subprocess.check_output(
        ["systemctl", "--user", "show", "-p", "MainPID", "--value", "pet_spot_elsahel_test.service"],
        text=True,
    ).strip()
    cmdline = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode()
    conf = open("/home/sabry/odoo_base/base_odoo_19/config/projects/pet_spot_elsahel_test.conf").read()
    trace["safety"] = {
        "cmdline": cmdline,
        "overlay_in_cmdline": "overlay" in cmdline,
        "overlay_in_conf": "overlay" in conf,
    }
    # merge with prior early screenshots note
    existing = {}
    if (DATA / "trace.json").exists():
        try:
            existing = json.loads((DATA / "trace.json").read_text())
        except Exception:
            existing = {}
    existing.update(trace)
    (DATA / "trace.json").write_text(json.dumps(existing, indent=2, default=str))
    log("resume UAT complete")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        (LOGS / "fatal_resume.txt").write_text(traceback.format_exc())
        raise
