#!/usr/bin/env python3
"""Remove duplicate/test scheduled posts on deebvet and reschedule the campaign."""
from __future__ import annotations

import json
import sys
import urllib.request
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

MODULE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_ROOT / "scripts"))
from config import get_odoo_client, load_env_file  # noqa: E402

PREFIX = "[PetSpot FB]"
TEST_TITLE = f"{PREFIX} UI module test"
TZ = ZoneInfo("Africa/Cairo")
INTERVAL = 60
START_HOUR = 13
END_HOUR = 3


def compute_schedule_slots(count: int, start_day: date) -> list[str]:
    slots: list[datetime] = []
    day = start_day
    while len(slots) < count:
        start_local = datetime.combine(day, time(START_HOUR, 0), tzinfo=TZ)
        end_local = datetime.combine(day + timedelta(days=1), time(END_HOUR, 0), tzinfo=TZ)
        current = start_local
        while current <= end_local and len(slots) < count:
            slots.append(current.astimezone(ZoneInfo("UTC")).replace(tzinfo=None))
            current += timedelta(minutes=INTERVAL)
        day += timedelta(days=1)
    return [s.strftime("%Y-%m-%d %H:%M:%S") for s in slots]


def post_title(message: str) -> str:
    return (message or "").split("\n", 1)[0].strip()


def main() -> int:
    load_env_file(MODULE_ROOT / ".env")
    client = get_odoo_client("remote")
    client.authenticate()

    posts = client.search_read(
        "social.post",
        [("message", "ilike", f"{PREFIX}%")],
        ["id", "message", "state", "scheduled_date", "image_ids", "account_ids"],
        order="id asc",
    )
    print(f"Found {len(posts)} remote posts with prefix {PREFIX!r}")

    by_title: dict[str, list[dict]] = defaultdict(list)
    for post in posts:
        by_title[post_title(post["message"])].append(post)

    keep_ids: set[int] = set()
    delete_ids: list[int] = []

    for title, group in by_title.items():
        if title == TEST_TITLE:
            delete_ids.extend(p["id"] for p in group if p["state"] == "scheduled")
            print(f"  DROP test scheduled: {len([p for p in group if p['state']=='scheduled'])} posts")
            continue

        posted = [p for p in group if p["state"] == "posted"]
        scheduled = [p for p in group if p["state"] == "scheduled"]

        for p in posted:
            keep_ids.add(p["id"])

        if not scheduled:
            continue

        # Keep the newest scheduled copy (highest id) with an image if possible.
        with_image = [p for p in scheduled if p.get("image_ids")]
        pick = max(with_image or scheduled, key=lambda p: p["id"])
        keep_ids.add(pick["id"])
        for p in scheduled:
            if p["id"] != pick["id"]:
                delete_ids.append(p["id"])

    delete_ids = sorted(set(delete_ids))
    print(f"\nKeeping {len(keep_ids)} posts, deleting {len(delete_ids)} duplicates/tests")

    if delete_ids:
        for i in range(0, len(delete_ids), 50):
            batch = delete_ids[i : i + 50]
            try:
                client.execute("social.post", "unlink", batch)
                print(f"  Unlinked {len(batch)} posts")
            except RuntimeError as exc:
                print(f"  Unlink batch failed: {exc}")
                for post_id in batch:
                    try:
                        client.execute("social.post", "action_set_draft", [post_id])
                        client.execute("social.post", "unlink", [post_id])
                        print(f"    Unlinked id={post_id}")
                    except RuntimeError as exc2:
                        print(f"    Failed id={post_id}: {exc2}")

    kept = client.search_read(
        "social.post",
        [("id", "in", sorted(keep_ids)), ("state", "=", "scheduled")],
        ["id", "message", "scheduled_date"],
        order="id asc",
    )
    print(f"\nRescheduling {len(kept)} scheduled posts (1 PM → 3 AM Cairo, every {INTERVAL} min)...")
    slots = compute_schedule_slots(len(kept), date(2026, 6, 20))

    for post, slot in zip(kept, slots):
        client.write("social.post", [post["id"]], {"scheduled_date": slot})
        local = (
            datetime.strptime(slot, "%Y-%m-%d %H:%M:%S")
            .replace(tzinfo=ZoneInfo("UTC"))
            .astimezone(TZ)
            .strftime("%Y-%m-%d %H:%M")
        )
        print(f"  id={post['id']} → {local} Cairo ({slot} UTC) — {post_title(post['message'])[:50]}")

    summary = client.search_read(
        "social.post",
        [("message", "ilike", f"{PREFIX}%")],
        ["id", "state"],
    )
    from collections import Counter

    counts = Counter(p["state"] for p in summary)
    print(f"\nDone. Remote campaign states: {dict(counts)} (total {len(summary)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
