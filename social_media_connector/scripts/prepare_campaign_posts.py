#!/usr/bin/env python3
"""Prepare unique fetched posts with images for campaign repost (draft + contact footer)."""
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
    with urllib.request.urlopen(req, timeout=180) as resp:
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
    rpc(url, db, uid, pwd, "social.media.post", "prepare_campaign_reposts")
    rows = rpc(
        url,
        db,
        uid,
        pwd,
        "social.media.post",
        "search_read",
        [("state", "=", "draft"), ("message", "ilike", "[PetSpot Contact]")],
        fields=["title", "scheduled_date", "image_ids", "page_id"],
        order="scheduled_date asc",
    )
    print(f"Campaign draft posts: {len(rows)}")
    for r in rows[:5]:
        print(f"  - {r['title']} @ {r.get('scheduled_date')} (image={'yes' if r.get('image_ids') else 'no'})")
    if len(rows) > 5:
        print(f"  ... and {len(rows) - 5} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
