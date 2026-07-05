#!/usr/bin/env python3
"""Reschedule campaign drafts (1 PM–3 AM window), mark ready, push to Odoo Online."""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_ROOT / "scripts"))
from config import load_env_file  # noqa: E402


def rpc(url, db, uid, pwd, model, method, *args, **kwargs):
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "service": "object",
            "method": "execute_kw",
            "args": [db, uid, pwd, model, method, list(args), kwargs],
        },
        "id": 1,
    }
    req = urllib.request.Request(
        f"{url}/jsonrpc",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
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
        uid = json.loads(resp.read().decode()).get("result")
    if not uid:
        raise RuntimeError("Local auth failed")
    return uid


def main() -> int:
    load_env_file(MODULE_ROOT / ".env")
    import os

    url = os.environ.get("LOCAL_ODOO_URL", "http://127.0.0.1:8027").rstrip("/")
    db = os.environ.get("LOCAL_ODOO_DB", "pet_spot_elsahel")
    user = os.environ.get("LOCAL_ODOO_USERNAME", "admin")
    pwd = os.environ.get("LOCAL_ODOO_PASSWORD", "admin")
    uid = auth(url, db, user, pwd)

    print("1) Prepare campaign reposts (schedule 1 PM → 3 AM daily, Cairo)...")
    rpc(url, db, uid, pwd, "social.media.post", "prepare_campaign_reposts")

    draft_ids = rpc(
        url,
        db,
        uid,
        pwd,
        "social.media.post",
        "search",
        [("state", "=", "draft"), ("message", "ilike", "[PetSpot Contact]")],
    )
    print(f"   Campaign drafts: {len(draft_ids)}")

    rows = rpc(
        url,
        db,
        uid,
        pwd,
        "social.media.post",
        "search_read",
        [("id", "in", draft_ids)],
        fields=["title", "scheduled_date"],
        order="scheduled_date asc",
    )
    for row in rows[:3]:
        print(f"   - {row['title']} @ {row['scheduled_date']} UTC")
    if len(rows) > 3:
        print(f"   ... and {len(rows) - 3} more")

    print("2) Mark ready...")
    rpc(url, db, uid, pwd, "social.media.post", "action_mark_ready", draft_ids)

    print("3) Push to remote Odoo Online...")
    for post_id in draft_ids:
        try:
            rpc(url, db, uid, pwd, "social.media.post", "action_push_to_remote", [post_id])
            rec = rpc(
                url,
                db,
                uid,
                pwd,
                "social.media.post",
                "read",
                [post_id],
                fields=["title", "state", "remote_post_id", "failure_reason"],
            )[0]
            status = rec["state"]
            remote_id = rec.get("remote_post_id")
            if status == "pushed" and remote_id:
                print(f"   OK  {rec['title']} → remote id {remote_id}")
            else:
                print(f"   FAIL {rec['title']}: {rec.get('failure_reason') or status}")
        except Exception as exc:
            print(f"   ERROR post {post_id}: {exc}")

    pushed = rpc(
        url,
        db,
        uid,
        pwd,
        "social.media.post",
        "search_count",
        [("id", "in", draft_ids), ("state", "=", "pushed")],
    )
    print(f"Done: {pushed}/{len(draft_ids)} pushed to remote.")
    return 0 if pushed == len(draft_ids) else 1


if __name__ == "__main__":
    raise SystemExit(main())
