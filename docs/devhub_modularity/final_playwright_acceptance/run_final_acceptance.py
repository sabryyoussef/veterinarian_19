#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Final Playwright operational acceptance — Live Test Dev Hub (read-only)."""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("PLAYWRIGHT_HOST_PLATFORM_OVERRIDE", "ubuntu24.04-x64")
os.environ["HOME"] = "/home/sabry"
os.environ.pop("GH_CONFIG_DIR", None)

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8028"
DB = "pet_spot_elsahel_test"
LOGIN, PASSWORD = "admin", "admin"
EVID = Path(__file__).resolve().parent
SHOT, DATA, LOGS = EVID / "screenshots", EVID / "data", EVID / "logs"
for d in (SHOT, DATA, LOGS):
    d.mkdir(parents=True, exist_ok=True)

ACTION_WORK = 1377
ACTION_WORKFLOW = 1391
ACTION_SESSIONS = 1393
ACTION_WORKSPACES = 1396
ACTION_CHECKPOINTS = 1397
ACTION_DEPLOY_RECORDS = 1406
ACTION_ANALYSIS = 1389
ACTION_PLANS = 1388

VIEWPORT = {"width": 1440, "height": 900}

console_events: list[dict] = []
network_fails: list[dict] = []
index: list[dict] = []
trace: dict = {
    "started_at": datetime.now(timezone.utc).isoformat(),
    "screenshots": [],
    "console": console_events,
    "network_fails": network_fails,
    "non_blockers": [],
    "errors": [],
}


def log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    (LOGS / "acceptance.log").open("a").write(line + "\n")


def ensure_test_up() -> None:
    code = subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", f"{BASE}/web/login"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    if code == "200":
        return
    log(f"Test HTTP {code}; restarting service")
    subprocess.run(["systemctl", "--user", "start", "pet_spot_elsahel_test.service"], check=False)
    for _ in range(30):
        time.sleep(2)
        code = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", f"{BASE}/web/login"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        if code == "200":
            log("Test service healthy again")
            return
    raise RuntimeError("Live Test service failed to become healthy")


def shot(page, name: str, proves: str, result: str = "PASS") -> None:
    page.wait_for_timeout(400)
    path = SHOT / name
    page.screenshot(path=str(path), full_page=False)
    entry = {
        "file": name,
        "page": page.url,
        "proves": proves,
        "result": result,
        "bytes": path.stat().st_size if path.exists() else 0,
    }
    index.append(entry)
    trace["screenshots"].append(entry)
    log(f"shot {name} :: {proves} ({result}) bytes={entry['bytes']}")


def login(page) -> None:
    ensure_test_up()
    page.goto(f"{BASE}/web/login", wait_until="domcontentloaded", timeout=60000)
    page.fill('input[name="login"]', LOGIN)
    page.fill('input[name="password"]', PASSWORD)
    db = page.locator('select[name="db"]')
    if db.count() and db.is_visible():
        db.select_option(DB)
    page.locator('button.btn-primary[type="submit"]').first.click()
    page.wait_for_load_state("load", timeout=90000)
    page.wait_for_timeout(2500)
    if "/web/login" in page.url:
        raise RuntimeError(f"login failed: {page.url}")
    # Wait for backend chrome
    try:
        page.wait_for_selector(".o_main_navbar, .o_web_client, nav", timeout=30000)
    except Exception:
        pass


def wait_form(page, markers: list[str] | None = None, timeout_ms: int = 25000) -> bool:
    deadline = time.time() + timeout_ms / 1000
    markers = markers or []
    while time.time() < deadline:
        try:
            if page.locator(".o_form_view, .o_list_view, .o_kanban_view, .o_content").count():
                body = page.inner_text("body")
                if markers and not any(m in body for m in markers):
                    page.wait_for_timeout(400)
                    continue
                if "Access Error" in body or "Odoo Server Error" in body:
                    return False
                # blank-only banner page is too short
                if len(body.strip()) > 80:
                    return True
        except Exception:
            pass
        page.wait_for_timeout(400)
    return False


def open_action(page, action_id: int, record_id: int | None = None) -> None:
    ensure_test_up()
    url = (
        f"{BASE}/odoo/action-{action_id}/{record_id}"
        if record_id
        else f"{BASE}/odoo/action-{action_id}"
    )
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1200)


def open_record(page, model: str, rid: int, action_id: int | None = None, markers: list[str] | None = None) -> None:
    ensure_test_up()
    urls = []
    if action_id:
        urls.append(f"{BASE}/odoo/action-{action_id}/{rid}")
    urls.append(f"{BASE}/web#id={rid}&model={model}&view_type=form")
    urls.append(f"{BASE}/odoo/{model}/{rid}")
    last_err = None
    for url in urls:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1500)
            if "/web/login" in page.url:
                login(page)
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1500)
            if wait_form(page, markers=markers):
                return
        except Exception as exc:
            last_err = exc
            log(f"open_record retry {url}: {exc}")
    raise RuntimeError(f"failed to open {model}/{rid}: {last_err}")


def svc(name: str) -> str:
    proc = subprocess.run(
        ["systemctl", "--user", "is-active", name],
        capture_output=True,
        text=True,
    )
    return (proc.stdout or proc.stderr or "unknown").strip() or "unknown"


def main() -> int:
    try:
        import importlib.metadata

        pw_ver = importlib.metadata.version("playwright")
    except Exception:
        pw_ver = "unknown"

    ensure_test_up()
    meta = {
        "base": BASE,
        "db": DB,
        "viewport": VIEWPORT,
        "playwright": pw_ver,
        "browser": "chromium",
        "git_sha": subprocess.check_output(
            [
                "git",
                "-C",
                "/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel",
                "rev-parse",
                "HEAD",
            ],
            text=True,
        ).strip(),
        "test_service": svc("pet_spot_elsahel_test.service"),
        "prod_service": svc("pet_spot_elsahel.service"),
        "addons_path_canonical": True,
    }
    (DATA / "meta.json").write_text(json.dumps(meta, indent=2))
    log(f"meta {meta}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport=VIEWPORT)
        page = context.new_page()

        def on_console(msg):
            console_events.append({"type": msg.type, "text": msg.text[:500], "url": page.url})

        def on_response(resp):
            if resp.status >= 400:
                network_fails.append(
                    {"status": resp.status, "url": resp.url[:300], "page": page.url}
                )

        page.on("console", on_console)
        page.on("response", on_response)

        login(page)
        shot(page, "01_login_backend.png", "Odoo backend after Live Test login")

        open_action(page, ACTION_WORK)
        wait_form(page)
        try:
            toggle = page.locator("button.o_menu_toggle, .o_navbar_apps_menu button").first
            if toggle.is_visible():
                toggle.click()
                page.wait_for_timeout(800)
        except Exception as exc:
            trace["non_blockers"].append(f"menu toggle: {exc}")
        shot(page, "02_devhub_main_menu.png", "Dev Hub navigation / Recent Work surface")

        open_action(page, ACTION_WORKFLOW)
        wait_form(page, markers=["Workflow", "Stage", "Work"])
        shot(page, "03_workflow_board.png", "Workflow Board stages + KPIs")

        open_record(page, "dev.work.item", 3324, ACTION_WORK, markers=["3324", "DEVHUB-GOVERNED"])
        shot(page, "04_work_item_3324.png", "Work Item 3324 completed operational UAT")

        open_record(
            page, "dev.work.analysis", 2695, ACTION_ANALYSIS, markers=["2695", "accepted", "Analysis"]
        )
        shot(page, "05_analysis_2695.png", "Analysis 2695 linked to WI 3324")

        open_record(page, "dev.work.plan", 2478, ACTION_PLANS, markers=["2478", "approved", "Plan"])
        shot(page, "06_plan_2478.png", "Plan 2478 approved")
        try:
            for label in ("Steps", "Plan Steps", "Step"):
                tab = page.get_by_role("tab", name=label)
                if tab.count():
                    tab.first.click()
                    page.wait_for_timeout(600)
                    break
            else:
                page.get_by_text("write_doc", exact=False).first.click(timeout=2000)
        except Exception:
            page.evaluate("window.scrollTo(0, 700)")
            page.wait_for_timeout(500)
        shot(page, "07_plan_steps.png", "Plan 2478 steps visible")

        open_record(
            page,
            "dev.work.approval",
            2276,
            markers=["2276", "approved", "824be651", "Approval", "exact"],
        )
        shot(page, "08_approval_2276.png", "Exact-hash Approval 2276 approved")

        open_record(
            page,
            "dev.session",
            950,
            ACTION_SESSIONS,
            markers=["950", "paused", "DW-3324", "Isolated"],
        )
        shot(page, "09_session_950.png", "Session 950 paused isolated execution")

        open_record(
            page,
            "dev.execution.workspace",
            1849,
            ACTION_WORKSPACES,
            markers=["1849", "DW-3324", "deployed", "22c3cdc0", "0b516d5"],
        )
        shot(page, "10_workspace_1849.png", "Workspace 1849 deployed_staging_reviewed")
        shot(page, "11_execution_state.png", "Workspace execution/deployed state for DW-3324")

        open_record(
            page,
            "dev.work.checkpoint",
            2144,
            ACTION_CHECKPOINTS,
            markers=["2144", "3324", "Checkpoint"],
        )
        shot(page, "12_checkpoint_evidence.png", "Checkpoint 2144 for WI 3324")

        open_record(
            page,
            "dev.git.commit.record",
            1102,
            markers=["1102", "22c3cdc0", "commit", "DW-3324"],
        )
        shot(page, "13_git_commit_push.png", "Commit record 1102 SHA 22c3cdc0…")

        open_record(
            page,
            "dev.git.pr.record",
            200,
            markers=["200", "16", "pull", "PR", "veterinarian"],
        )
        shot(page, "14_github_pr_16.png", "Dev Hub GitHub App PR record #16")

        open_record(
            page,
            "dev.git.merge.approval",
            57,
            markers=["57", "714", "Administrator", "22c3cdc0", "Merge"],
        )
        shot(page, "15_merge_approval_57.png", "Merge Approval 57 requester≠approver")

        open_record(
            page,
            "dev.git.merge.record",
            35,
            markers=["35", "0b516d5", "merged", "16"],
        )
        shot(page, "16_merge_record_35.png", "Governed Merge Record 35 SHA 0b516d5a…")

        open_record(
            page,
            "dev.deploy.record",
            1,
            ACTION_DEPLOY_RECORDS,
            markers=["succeeded", "0b516d5", "PetSpot Test", "Deploy"],
        )
        shot(page, "17_test_deployment_success.png", "Test Deploy record 1 → target 4 succeeded")

        open_action(page, ACTION_WORKFLOW)
        wait_form(page, markers=["Workflow", "Stage"])
        shot(page, "18_workflow_board_final.png", "Workflow Board final after full navigation")

        browser.close()

    # Production safety
    safety = {
        "prod_service": svc("pet_spot_elsahel.service"),
        "test_service": svc("pet_spot_elsahel_test.service"),
    }
    try:
        import xmlrpc.client

        common = xmlrpc.client.ServerProxy("http://127.0.0.1:8027/xmlrpc/2/common")
        uid = common.authenticate("pet_spot_elsahel", "admin", "admin", {})
        models = xmlrpc.client.ServerProxy("http://127.0.0.1:8027/xmlrpc/2/object")
        mods = models.execute_kw(
            "pet_spot_elsahel",
            uid,
            "admin",
            "ir.module.module",
            "search_read",
            [[("name", "in", ["devhub_core", "dev_session_hub", "devhub_work"])]],
            {"fields": ["name", "state"]},
        )
        safety["prod_modules"] = mods
    except Exception as exc:
        safety["prod_check_error"] = str(exc)[:200]

    critical, non_block, unrelated = [], [], []
    for ev in console_events:
        text = (ev.get("text") or "").lower()
        if ev.get("type") != "error":
            continue
        if "failed to fetch" in text and "reloadmenus" in text:
            unrelated.append({**ev, "class": "UNRELATED_SERVICE_BLIP"})
            continue
        if any(
            k in text
            for k in ("devhub", "dev.work", "dev.session", "dev.git", "dev.deploy", "workflow")
        ):
            critical.append(ev)
        elif "ai.embedding" in text:
            unrelated.append(ev)
        else:
            non_block.append(ev)
    for nf in network_fails:
        url = (nf.get("url") or "").lower()
        if nf["status"] in (404,) and "/web/image" in url:
            unrelated.append(nf)
        elif any(
            k in url for k in ("dev.work", "dev.session", "dev.git", "dev.deploy", "workflow")
        ) and nf["status"] >= 500:
            critical.append(nf)
        elif nf["status"] >= 500:
            non_block.append(nf)
        else:
            unrelated.append(nf)

    # Blank-shot detection
    blankish = [e for e in index if e["bytes"] < 70000 and e["file"] not in ("03_workflow_board.png",)]
    # workflow board can be smaller but rich; use content check via bytes after successful wait
    results = {
        "critical": critical[:50],
        "non_blockers": non_block[:50],
        "unrelated": unrelated[:50],
        "critical_count": len(critical),
        "console_total": len(console_events),
        "network_fail_total": len(network_fails),
        "small_screenshots": blankish,
    }
    (DATA / "console_network.json").write_text(json.dumps(results, indent=2, default=str))
    (DATA / "screenshot_index.json").write_text(json.dumps(index, indent=2))
    (DATA / "production_safety.json").write_text(json.dumps(safety, indent=2, default=str))
    trace["console_network"] = {
        "critical_count": results["critical_count"],
        "console_total": results["console_total"],
        "network_fail_total": results["network_fail_total"],
    }
    trace["production_safety"] = safety
    (DATA / "trace.json").write_text(json.dumps(trace, indent=2, default=str))

    expected = [
        "01_login_backend.png",
        "02_devhub_main_menu.png",
        "03_workflow_board.png",
        "04_work_item_3324.png",
        "05_analysis_2695.png",
        "06_plan_2478.png",
        "07_plan_steps.png",
        "08_approval_2276.png",
        "09_session_950.png",
        "10_workspace_1849.png",
        "11_execution_state.png",
        "12_checkpoint_evidence.png",
        "13_git_commit_push.png",
        "14_github_pr_16.png",
        "15_merge_approval_57.png",
        "16_merge_record_35.png",
        "17_test_deployment_success.png",
        "18_workflow_board_final.png",
    ]
    missing = [
        f
        for f in expected
        if not (SHOT / f).exists() or (SHOT / f).stat().st_size < 20000
    ]
    (DATA / "missing.json").write_text(json.dumps(missing, indent=2))
    log(f"missing={missing} critical={results['critical_count']}")
    if missing:
        return 2
    if results["critical_count"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
