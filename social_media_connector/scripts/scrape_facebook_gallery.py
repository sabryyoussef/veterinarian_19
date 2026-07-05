#!/usr/bin/env python3
"""Download Facebook page photos into website/assets/gallery/facebook/."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_ROOT / "scripts"))
sys.path.insert(0, str(MODULE_ROOT / "models"))
from config import get_odoo_client, load_env_file  # noqa: E402
from facebook_gallery_scraper import scrape_facebook_gallery  # noqa: E402


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
    with urllib.request.urlopen(req, timeout=600) as resp:
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


def _resolve_page_facebook_id(local_url, local_db, uid, pwd) -> tuple[int, str]:
    remote_account_id = int(
        os.environ.get("DEFAULT_REMOTE_ACCOUNT_ID", "4") or 4
    )
    pages = rpc(
        local_url,
        local_db,
        uid,
        pwd,
        "social.media.page",
        "search_read",
        [("remote_account_id", "=", remote_account_id)],
        fields=["name", "facebook_page_id"],
        limit=1,
    )
    if pages and pages[0].get("facebook_page_id"):
        return remote_account_id, pages[0]["facebook_page_id"]

    fb_page_id = os.environ.get("FACEBOOK_PAGE_1_ID", "").strip()
    if fb_page_id:
        return remote_account_id, fb_page_id

    raise RuntimeError(
        "Facebook page not linked locally. Run Fetch Facebook Pages in Odoo "
        "or set FACEBOOK_PAGE_1_ID in .env."
    )


def scrape_direct(max_photos: int, fill_slots: bool) -> dict:
    load_env_file(MODULE_ROOT / ".env")
    remote_client = get_odoo_client("remote")

    local_url = os.environ.get("LOCAL_ODOO_URL", "http://127.0.0.1:8027").rstrip("/")
    local_db = os.environ.get("LOCAL_ODOO_DB", "pet_spot_elsahel")
    local_user = os.environ.get("LOCAL_ODOO_USERNAME", "admin")
    local_pwd = os.environ.get("LOCAL_ODOO_PASSWORD", "admin")
    uid = auth(local_url, local_db, local_user, local_pwd)
    remote_account_id, page_facebook_id = _resolve_page_facebook_id(
        local_url, local_db, uid, local_pwd
    )

    return scrape_facebook_gallery(
        remote_client,
        page_facebook_id=page_facebook_id,
        remote_account_id=remote_account_id,
        module_root=MODULE_ROOT,
        max_photos=max_photos,
        fill_slots=fill_slots,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max", type=int, default=200, help="Max photos to download")
    parser.add_argument(
        "--no-fill-slots",
        action="store_true",
        help="Do not copy best matches into the 4 homepage gallery slots",
    )
    parser.add_argument(
        "--via-odoo",
        action="store_true",
        help="Call scrape_facebook_gallery_to_website on local Odoo (needs module reload)",
    )
    args = parser.parse_args()
    fill_slots = not args.no_fill_slots

    print(
        f"Scraping Facebook gallery (max={args.max}, fill_slots={fill_slots})..."
    )

    if args.via_odoo:
        load_env_file(MODULE_ROOT / ".env")
        url = os.environ.get("LOCAL_ODOO_URL", "http://127.0.0.1:8027").rstrip("/")
        db = os.environ.get("LOCAL_ODOO_DB", "pet_spot_elsahel")
        user = os.environ.get("LOCAL_ODOO_USERNAME", "admin")
        pwd = os.environ.get("LOCAL_ODOO_PASSWORD", "admin")
        uid = auth(url, db, user, pwd)
        result = rpc(
            url,
            db,
            uid,
            pwd,
            "social.media.post",
            "scrape_facebook_gallery_to_website",
            max_photos=args.max,
            fill_slots=fill_slots,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        result = scrape_direct(args.max, fill_slots)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    manifest = MODULE_ROOT.parent / "website" / "assets" / "gallery" / "facebook" / "manifest.json"
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        print(f"\nDownloaded: {data.get('count', 0)} photo(s)")
        print(f"Manifest: {manifest}")
        if result.get("slots_filled"):
            print(f"Homepage slots: {', '.join(result['slots_filled'].keys())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
