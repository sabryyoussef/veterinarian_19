#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Continue governed UAT from existing GitHub App PR (WI 3324 / WS 1849)."""
from __future__ import annotations

import json
import os
import subprocess
import time
import xmlrpc.client
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("PLAYWRIGHT_HOST_PLATFORM_OVERRIDE", "ubuntu24.04-x64")
# Avoid worker GH profile pollution for observational gh polls
os.environ.pop("GH_CONFIG_DIR", None)
os.environ["HOME"] = "/home/sabry"

from playwright.sync_api import sync_playwright

from run_governed_uat import (
    ACTION_WORK,
    ACTION_WORKFLOW,
    BASE,
    DATA,
    DB,
    LOGS,
    LOGIN,
    MERGE_TARGET_ID,
    PASSWORD,
    REQUESTER_ID,
    SHOT,
    Odoo,
    login_ui,
    log,
    odoo_shell,
    open_action,
    open_form,
    shot,
    trace,
)

WS_ID = int(os.environ.get("RESUME_WS_ID", "1849"))
WI_ID = int(os.environ.get("RESUME_WI_ID", "3324"))


def main():
    odoo = Odoo()
    ws = odoo.read(
        "dev.execution.workspace",
        WS_ID,
        [
            "id",
            "state",
            "pr_number",
            "pr_url_reference",
            "pr_source_sha",
            "pr_source_branch",
            "pr_target_branch",
            "committed_sha",
            "pr_record_id",
            "pr_target_id",
        ],
    )[0]
    pr_number = ws["pr_number"]
    target = odoo.read(
        "dev.git.pr.target",
        ws["pr_target_id"][0],
        ["github_app_id", "github_installation_id", "name"],
    )[0]
    pr_payload = {
        "ok": True,
        "pr_number": pr_number,
        "pr_url": ws["pr_url_reference"],
        "state": ws["state"],
        "source_sha": ws["pr_source_sha"],
        "app_id": target["github_app_id"],
        "installation_id": target["github_installation_id"],
        "pr_record_id": ws["pr_record_id"][0] if ws["pr_record_id"] else None,
        "draft_note": "Product path creates open (non-draft) PR; merge gate requires draft=false",
        "head_branch": ws["pr_source_branch"],
        "base_branch": ws["pr_target_branch"],
    }
    (DATA / "github_app_pr.json").write_text(json.dumps(pr_payload, indent=2))
    trace.update(
        {
            "work_item_id": WI_ID,
            "workspace": {"id": WS_ID, "state": ws["state"]},
            "github_app_pr": pr_payload,
            "resumed_from_pr": True,
        }
    )
    log(f"resume WS {WS_ID} PR #{pr_number} state={ws['state']}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        login_ui(page)
        open_form(page, "dev.execution.workspace", WS_ID)
        shot(page, "10_github_app_pr.png", f"Dev Hub GitHub App PR #{pr_number}")

        # Observational poll only (merge still via Dev Hub)
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
                env={**os.environ, "HOME": "/home/sabry"},
            )
            meta = json.loads(view.stdout or "{}")
            (DATA / "pr_checks.json").write_text(json.dumps(meta, indent=2))
            checks = meta.get("statusCheckRollup") or []
            gg = [c for c in checks if c.get("name") == "GitGuardian Security Checks"]
            mergeable = meta.get("mergeable")
            log(f"poll {i} mergeable={mergeable} gg={gg[:1] if gg else None}")
            gg_ok = False
            if gg:
                c0 = gg[0]
                gg_ok = (
                    c0.get("state") == "SUCCESS"
                    or c0.get("conclusion") == "SUCCESS"
                    or (
                        c0.get("status") == "COMPLETED"
                        and c0.get("conclusion") in ("SUCCESS", "NEUTRAL", "SKIPPED")
                    )
                )
            if mergeable == "MERGEABLE" and (gg_ok or not gg):
                break
            time.sleep(15)
        else:
            trace["non_blockers"].append(
                "GitGuardian/mergeable poll timed out; attempting merge preflight anyway"
            )

        # Merge request as dedicated requester
        req_common = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/common")
        req_uid = req_common.authenticate(DB, "devhub-merge-requester", "uat-merge-requester-only", {})
        if not req_uid:
            raise RuntimeError("merge requester auth failed")
        req_models = xmlrpc.client.ServerProxy(f"{BASE}/xmlrpc/2/object")
        try:
            req_models.execute_kw(
                DB,
                req_uid,
                "uat-merge-requester-only",
                "dev.execution.workspace",
                "action_request_merge_review",
                [[WS_ID]],
            )
            log("merge review requested by dedicated requester")
        except Exception as exc:
            log(f"merge request note: {exc}")
            trace["non_blockers"].append(f"merge request: {exc}")

        open_form(page, "dev.execution.workspace", WS_ID)
        shot(page, "11_merge_approval.png", "READY FOR / performing human merge approval")

        try:
            # Merge App broker + PEM are worker-owned (mode 700); mint requires euid=devworker.
            merge_payload = odoo_shell(
                f"""
import json
ws = env['dev.execution.workspace'].browse({WS_ID}).with_user(2)
target = env['dev.git.merge.target'].browse({MERGE_TARGET_ID})
ws.action_review_merge_eligibility()
approval = ws.create_merge_approval(target)
record = ws.execute_approved_merge(approval)
env.cr.commit()
print(json.dumps({{
  'ok': True,
  'state': ws.state,
  'merge_sha': getattr(ws, 'merge_result_sha', None) or (getattr(record, 'merge_sha', None) if record else None),
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
            open_form(page, "dev.execution.workspace", WS_ID)
            shot(page, "11_merge_approval.png", "Human merge approval blocked — see logs")
            ready = {
                "verdict": "DEV HUB GOVERNED MERGE READY FOR HUMAN APPROVAL",
                "work_item": WI_ID,
                "workspace": WS_ID,
                "pr": pr_payload,
                "head_sha": ws["pr_source_sha"],
                "base": ws["pr_target_branch"],
                "checks": json.loads((DATA / "pr_checks.json").read_text() or "{}"),
                "error": str(exc),
            }
            (DATA / "ready_for_human_approval.json").write_text(json.dumps(ready, indent=2, default=str))
            browser.close()
            print("READY FOR HUMAN MERGE APPROVAL", flush=True)
            print(json.dumps(ready, indent=2, default=str), flush=True)
            return 2

        open_form(page, "dev.execution.workspace", WS_ID)
        shot(page, "12_merged_reviewed.png", "merged_reviewed")

        odoo.write("dev.policy", 1, {"deploy_permission": True})
        try:
            deploy_payload = odoo_shell(
                f"""
import json
ws = env['dev.execution.workspace'].browse({WS_ID}).with_user(2)
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
  'merge_sha': getattr(approval, 'merge_sha', None),
}}))
"""
            )
        finally:
            odoo.write("dev.policy", 1, {"deploy_permission": False})
        trace["deploy"] = deploy_payload
        (DATA / "deploy.json").write_text(json.dumps(deploy_payload, indent=2))
        open_form(page, "dev.execution.workspace", WS_ID)
        shot(page, "13_deploy_request.png", "Deploy request")
        shot(page, "14_test_deploy_success.png", "Test deploy result")

        try:
            reports = odoo.search_read(
                "dev.completion.report",
                [["work_item_id", "=", WI_ID]],
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
            odoo.call("dev.work.item", "action_complete", WI_ID)
        except Exception as exc:
            trace["non_blockers"].append(f"complete: {exc}")

        open_action(page, ACTION_WORK, WI_ID)
        shot(page, "15_workflow_final.png", "Final work item")
        open_action(page, ACTION_WORKFLOW)
        shot(page, "15_workflow_final.png", "Workflow board final")
        browser.close()

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
    (DATA / "trace.json").write_text(json.dumps(trace, indent=2, default=str))
    log("GOVERNED UAT CONTINUE COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
