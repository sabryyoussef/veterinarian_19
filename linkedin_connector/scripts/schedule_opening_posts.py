#!/usr/bin/env python3
"""Schedule 10 bilingual PetSpot opening posts in Odoo (every 3 minutes)."""
from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

MODULE_ROOT = Path(__file__).resolve().parents[1]
WEBSITE_ROOT = MODULE_ROOT.parent / "website"
sys.path.insert(0, str(WEBSITE_ROOT))

from odoo_rpc import OdooRPC  # noqa: E402

DATA_FILE = MODULE_ROOT / "data" / "opening_posts.json"
IMAGE_FILE = MODULE_ROOT / "assets" / "campaign" / "petspot-opening-hero.png"
INTERVAL_MINUTES = 3
POST_COUNT = 10


def _utc_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def main() -> int:
    load_dotenv(MODULE_ROOT / ".env")

    if not DATA_FILE.exists():
        print(f"Missing {DATA_FILE}", file=sys.stderr)
        return 1
    if not IMAGE_FILE.exists():
        print(f"Missing image {IMAGE_FILE}", file=sys.stderr)
        return 1

    with DATA_FILE.open(encoding="utf-8") as fh:
        posts = json.load(fh)["posts"][:POST_COUNT]

    client = OdooRPC(
        os.getenv("ODOO_URL", "http://127.0.0.1:8027"),
        os.getenv("ODOO_DB", "pet_spot_elsahel"),
        os.getenv("ODOO_USERNAME", "admin"),
        os.getenv("ODOO_PASSWORD") or os.getenv("ODOO_API_KEY", "admin"),
    )
    client.authenticate()

    account_name = os.getenv("LINKEDIN_TEST_ACCOUNT_NAME", "PetSpot LinkedIn (Test)")
    accounts = client.search_read(
        "linkedin.account",
        [("name", "=", account_name)],
        ["id", "name", "connected"],
        limit=1,
    )
    if not accounts:
        print(f"Account '{account_name}' not found", file=sys.stderr)
        return 1
    acc = accounts[0]
    if not acc.get("connected"):
        print("LinkedIn test account not connected — Connect first", file=sys.stderr)
        return 1

    acc_id = acc["id"]
    client.write("linkedin.account", [acc_id], {"fallback_personal_post": True})

    # Remove prior opening batch (same internal_title prefix)
    prefix = "PetSpot Opening "
    existing = client.search_read(
        "linkedin.post",
        [("account_id", "=", acc_id), ("internal_title", "like", prefix + "%")],
        ["id", "state"],
    )
    for p in existing:
        if p["state"] != "posted":
            client.execute("linkedin.post", "unlink", [p["id"]])

    img_b64 = base64.b64encode(IMAGE_FILE.read_bytes()).decode()
    att_id = client.create(
        "ir.attachment",
        {
            "name": "petspot-opening-hero.png",
            "type": "binary",
            "datas": img_b64,
            "mimetype": "image/png",
            "res_model": "linkedin.post",
        },
    )

    # Speed up cron for ~3 min spacing (runs every 1 min)
    crons = client.search_read(
        "ir.cron",
        [("name", "ilike", "LinkedIn: Publish Scheduled")],
        ["id", "interval_number"],
        limit=1,
    )
    if crons:
        client.write("ir.cron", [crons[0]["id"]], {"interval_number": 1})

    start = datetime.now(timezone.utc) + timedelta(minutes=1)
    created = []
    for i, post in enumerate(posts):
        scheduled = start + timedelta(minutes=i * INTERVAL_MINUTES)
        title = f"{prefix}{i + 1:02d} — {post['topic']}"
        post_id = client.create(
            "linkedin.post",
            {
                "account_id": acc_id,
                "internal_title": title,
                "message": post["message"],
                "post_method": "scheduled",
                "scheduled_date": _utc_str(scheduled),
                "state": "scheduled",
                "visibility": "PUBLIC",
                "image_ids": [(6, 0, [att_id])],
            },
        )
        created.append((post_id, title, scheduled))

    print(f"Scheduled {len(created)} posts on account id={acc_id} ({account_name})")
    print(f"Image attachment id={att_id}")
    print(f"Cron interval set to 1 minute for publishing\n")
    for pid, title, when in created:
        print(f"  id={pid} | {when.strftime('%H:%M UTC')} | {title}")
    print(f"\nAll {len(created)} posts should publish within ~{(len(created)-1)*INTERVAL_MINUTES + 2} minutes.")
    print("View: Odoo → LinkedIn → Posts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
