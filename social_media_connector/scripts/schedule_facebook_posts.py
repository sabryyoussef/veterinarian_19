#!/usr/bin/env python3
"""Push local Facebook posts to Odoo Online as scheduled social.post records."""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (  # noqa: E402
    MODULE_ROOT,
    get_campaign_prefix,
    get_odoo_client,
    get_page_map,
    load_env_file,
    resolve_account_id,
)

DATA_FILE = MODULE_ROOT / "data" / "posts.json"
IMAGE_CACHE: dict[str, int] = {}


def _marker(index: int, topic: str) -> str:
    prefix = get_campaign_prefix()
    return f"{prefix} {index:02d} — {topic}"


def _full_message(index: int, topic: str, body: str) -> str:
    return f"{_marker(index, topic)}\n\n{body.strip()}"


def _to_utc_str(local_dt: datetime, tz_name: str) -> str:
    tz = ZoneInfo(tz_name)
    if local_dt.tzinfo is None:
        local_dt = local_dt.replace(tzinfo=tz)
    utc_dt = local_dt.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    return utc_dt.strftime("%Y-%m-%d %H:%M:%S")


def _upload_image(client, image_path: Path) -> int:
    key = str(image_path.resolve())
    if key in IMAGE_CACHE:
        return IMAGE_CACHE[key]
    if not image_path.exists():
        raise FileNotFoundError(image_path)
    mimetype = mimetypes.guess_type(image_path.name)[0] or "image/png"
    att_id = client.create(
        "ir.attachment",
        {
            "name": image_path.name,
            "type": "binary",
            "datas": base64.b64encode(image_path.read_bytes()).decode(),
            "mimetype": mimetype,
            "res_model": "social.post",
        },
    )
    IMAGE_CACHE[key] = att_id
    return att_id


def _cleanup_existing(client, prefix: str) -> int:
    existing = client.search_read(
        "social.post",
        [("message", "like", f"{prefix}%"), ("state", "in", ["draft", "scheduled"])],
        ["id", "state", "message"],
    )
    removed = 0
    for post in existing:
        client.execute("social.post", "unlink", [post["id"]])
        removed += 1
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Schedule Facebook posts on Odoo Online")
    parser.add_argument("--limit", type=int, default=0, help="Max posts to schedule (0 = all)")
    parser.add_argument("--test", action="store_true", help="Schedule 1 post ~5 minutes from now")
    parser.add_argument("--data", type=Path, default=DATA_FILE, help="Path to posts.json")
    parser.add_argument("--dry-run", action="store_true", help="Validate only, no RPC writes")
    args = parser.parse_args()

    load_env_file(MODULE_ROOT / ".env")
    if not args.data.exists():
        print(f"Missing {args.data}", file=sys.stderr)
        return 1

    with args.data.open(encoding="utf-8") as fh:
        data = json.load(fh)

    posts = data.get("posts", [])
    defaults = data.get("defaults", {})
    tz_name = defaults.get("timezone", "Africa/Cairo")
    interval = int(defaults.get("interval_minutes", 60))
    default_image = defaults.get("image", "assets/images/petspot-opening-hero.png")
    campaign_prefix = get_campaign_prefix()

    if args.test:
        posts = posts[:1]
        interval = 5
    elif args.limit > 0:
        posts = posts[: args.limit]

    client = get_odoo_client()
    client.authenticate()
    page_map = get_page_map()

    if not args.dry_run:
        removed = _cleanup_existing(client, campaign_prefix)
        if removed:
            print(f"Removed {removed} prior scheduled/draft post(s) with prefix {campaign_prefix!r}")

    start_local = datetime.now(ZoneInfo(tz_name)) + timedelta(minutes=5)
    created = []

    for i, post in enumerate(posts, start=1):
        topic = post["topic"]
        page_key = post.get("page_key") or defaults.get("page_key", "FACEBOOK_PAGE_1")
        body = post["message"]
        image_rel = post.get("image") or default_image
        image_path = MODULE_ROOT / image_rel

        if post.get("scheduled_at"):
            scheduled_local = datetime.strptime(post["scheduled_at"], "%Y-%m-%d %H:%M:%S")
            scheduled_local = scheduled_local.replace(tzinfo=ZoneInfo(tz_name))
        else:
            scheduled_local = start_local + timedelta(minutes=(i - 1) * interval)

        scheduled_utc = _to_utc_str(scheduled_local, tz_name)
        message = _full_message(i, topic, body)
        account_id = resolve_account_id(client, page_key, page_map)

        print(f"\n[{i}/{len(posts)}] {topic}")
        print(f"  page_key={page_key} → social.account id={account_id}")
        print(f"  scheduled {scheduled_local.strftime('%Y-%m-%d %H:%M')} {tz_name} → UTC {scheduled_utc}")
        print(f"  image={image_rel}")

        if args.dry_run:
            created.append((None, topic, scheduled_utc))
            continue

        att_id = _upload_image(client, image_path)
        post_id = client.create(
            "social.post",
            {
                "post_method": "scheduled",
                "scheduled_date": scheduled_utc,
                "account_ids": [(6, 0, [account_id])],
                "message": message,
                "image_ids": [(6, 0, [att_id])],
            },
        )
        client.execute("social.post", "action_schedule", [post_id])
        rows = client.search_read(
            "social.post",
            [("id", "=", post_id)],
            ["id", "state", "scheduled_date"],
            limit=1,
        )
        state = rows[0]["state"] if rows else "?"
        print(f"  → social.post id={post_id} state={state}")
        created.append((post_id, topic, scheduled_utc))

    print(f"\nDone. Scheduled {len(created)} post(s) on {client.url}")
    if args.test:
        print("Test mode: first post in ~5 minutes. Check Odoo Social Marketing → Posts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
