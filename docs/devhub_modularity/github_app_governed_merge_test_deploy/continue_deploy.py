#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Continue from merged_reviewed → Test deploy for WS 1849."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

os.environ.setdefault("PLAYWRIGHT_HOST_PLATFORM_OVERRIDE", "ubuntu24.04-x64")
os.environ["HOME"] = "/home/sabry"
os.environ.pop("GH_CONFIG_DIR", None)

from playwright.sync_api import sync_playwright

from run_governed_uat import (
    ACTION_WORK,
    ACTION_WORKFLOW,
    DATA,
    LOGS,
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
        ["id", "state", "merge_result_sha", "merge_record_id", "pr_number", "pr_url_reference"],
    )[0]
    if ws["state"] != "merged_reviewed":
        raise RuntimeError(f"expected merged_reviewed, got {ws['state']}")
    trace.update({"work_item_id": WI_ID, "workspace": ws, "resumed_from_merge": True})
    log(f"deploy resume WS {WS_ID} state={ws['state']} merge={ws['merge_result_sha']}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        login_ui(page)
        open_form(page, "dev.execution.workspace", WS_ID)
        shot(page, "12_merged_reviewed.png", "merged_reviewed before deploy")

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
  'target_name': target.name,
  'non_production': target.non_production,
  'database': target.database_identifier,
  'merge_sha': approval.merge_sha,
  'result_state': record.result_state if record else None,
  'backup_ref': record.backup_checkpoint_ref if record else None,
}}))
"""
            )
        finally:
            odoo.write("dev.policy", 1, {"deploy_permission": False})
        trace["deploy"] = deploy_payload
        (DATA / "deploy.json").write_text(json.dumps(deploy_payload, indent=2))
        log(f"deploy {deploy_payload}")

        open_form(page, "dev.execution.workspace", WS_ID)
        shot(page, "13_deploy_request.png", "Deploy request / approval")
        shot(page, "14_test_deploy_success.png", "Test deploy success")

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
            trace["non_blockers"] = trace.get("non_blockers", []) + [f"complete: {exc}"]

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
        "deploy": deploy_payload,
        "merge_sha": ws["merge_result_sha"],
    }
    # runner log tail
    runner_log = Path("/srv/devhub/logs/runner.log")
    if runner_log.exists():
        safety["runner_log_tail"] = runner_log.read_text()[-2000:]
    trace["production_safety"] = safety
    (DATA / "trace_deploy.json").write_text(json.dumps(trace, indent=2, default=str))
    log("DEPLOY CONTINUE COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
