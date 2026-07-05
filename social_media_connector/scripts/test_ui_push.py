#!/usr/bin/env python3
"""Integration test: local Odoo UI module → push to remote deebvet."""
from __future__ import annotations

import base64
import json
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_ROOT / "scripts"))
from config import load_env_file  # noqa: E402

# 1x1 red PNG
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def rpc(url, db, uid, password, model, method, *args, **kwargs):
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "service": "object",
            "method": "execute_kw",
            "args": [db, uid, password, model, method, list(args), kwargs],
        },
        "id": 1,
    }
    req = urllib.request.Request(
        f"{url}/jsonrpc",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    if data.get("error"):
        raise RuntimeError(data["error"])
    return data.get("result")


def auth(url, db, user, secret):
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "service": "common",
            "method": "authenticate",
            "args": [db, user, secret, {}],
        },
        "id": 1,
    }
    req = urllib.request.Request(
        f"{url}/jsonrpc",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    uid = data.get("result")
    if not uid:
        raise RuntimeError("Local auth failed")
    return uid


def set_param(url, db, uid, pwd, key, value):
    rows = rpc(
        url, db, uid, pwd, "ir.config_parameter", "search_read",
        [("key", "=", key)], fields=["id"], limit=1,
    )
    if rows:
        rpc(url, db, uid, pwd, "ir.config_parameter", "write", [rows[0]["id"]], {"value": value})
    else:
        rpc(url, db, uid, pwd, "ir.config_parameter", "create", {"key": key, "value": value})


def main() -> int:
    load_env_file(MODULE_ROOT / ".env")
    import os

    local_url = os.environ.get("LOCAL_ODOO_URL", "http://127.0.0.1:8027").rstrip("/")
    local_db = os.environ.get("LOCAL_ODOO_DB", "pet_spot_elsahel")
    local_user = os.environ.get("LOCAL_ODOO_USERNAME", "admin")
    local_pwd = os.environ.get("LOCAL_ODOO_PASSWORD", "admin")

    uid = auth(local_url, local_db, local_user, local_pwd)
    print(f"Local auth OK uid={uid}")

    for key, env_key in (
        ("social_media_connector.remote_url", "ODOO_URL"),
        ("social_media_connector.remote_db", "ODOO_DB"),
        ("social_media_connector.remote_username", "ODOO_USERNAME"),
        ("social_media_connector.remote_api_key", "ODOO_API_KEY"),
        ("social_media_connector.campaign_prefix", "CAMPAIGN_PREFIX"),
    ):
        set_param(local_url, local_db, uid, local_pwd, key, os.environ.get(env_key, ""))
    print("Config parameters set from .env")

    page_count = rpc(local_url, local_db, uid, local_pwd, "social.media.page", "sync_from_remote")
    print(f"Synced {page_count} Facebook page(s)")

    pages = rpc(
        local_url,
        local_db,
        uid,
        local_pwd,
        "social.media.page",
        "search_read",
        [("remote_account_id", "=", 4)],
        fields=["id", "name", "has_token", "is_disconnected"],
        limit=1,
    )
    if not pages:
        print("ERROR: Main page (بيت الدواء البيطري -pet spot) not found. Fetch pages first.", file=sys.stderr)
        return 1
    page_id = pages[0]["id"]
    print(f"Using page: {pages[0]['name']} (id={page_id}, has_token={pages[0]['has_token']})")

    att_id = rpc(
        local_url,
        local_db,
        uid,
        local_pwd,
        "ir.attachment",
        "create",
        {
            "name": "test-ui-push.png",
            "type": "binary",
            "datas": base64.b64encode(TINY_PNG).decode(),
            "mimetype": "image/png",
            "res_model": "social.media.post",
        },
    )

    scheduled = (datetime.utcnow() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    post_id = rpc(
        local_url,
        local_db,
        uid,
        local_pwd,
        "social.media.post",
        "create",
        {
            "title": "UI module test",
            "page_id": page_id,
            "message": "Test push from local Social Media Connector UI module.",
            "post_method": "scheduled",
            "scheduled_date": scheduled,
            "image_ids": [(6, 0, [att_id])],
            "state": "draft",
        },
    )
    print(f"Created local post id={post_id}, scheduled UTC {scheduled}")

    rpc(local_url, local_db, uid, local_pwd, "social.media.post", "action_mark_ready", [post_id])
    rpc(local_url, local_db, uid, local_pwd, "social.media.post", "action_push_to_remote", [post_id])

    rows = rpc(
        local_url,
        local_db,
        uid,
        local_pwd,
        "social.media.post",
        "read",
        [post_id],
        fields=["state", "remote_post_id", "remote_state", "failure_reason"],
    )
    rec = rows[0]
    print(f"Push result: state={rec['state']} remote_post_id={rec['remote_post_id']} remote_state={rec.get('remote_state')}")
    if rec.get("failure_reason"):
        print(f"Failure: {rec['failure_reason']}", file=sys.stderr)
        return 1
    if rec["state"] != "pushed" or not rec["remote_post_id"]:
        print("ERROR: push did not succeed", file=sys.stderr)
        return 1
    print("SUCCESS: post pushed to remote Odoo Online")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
