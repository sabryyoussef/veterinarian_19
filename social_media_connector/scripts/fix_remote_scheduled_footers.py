#!/usr/bin/env python3
"""Fix scheduled remote social.post footers — remove trackable URLs and stale markers."""
from __future__ import annotations

import re
import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_ROOT / "scripts"))
from config import get_odoo_client, load_env_file  # noqa: E402

PREFIX = "[PetSpot FB]"
MARKER = "[PetSpot Contact]"

FOOTER = (
    "\n\n---\n"
    "📞 Call: 01201568888\n"
    "💬 WhatsApp: 01000059085\n"
    "🌐 petspot.odoo.com\n"
    "📘 Facebook: بيت الدواء البيطري -pet spot\n"
    "📍 Beside Amwaj 1 gate, Main Road, Sidi Abdel Rahman, North Coast\n"
    "🗺️ Google Maps: PetSpot Amwaj 1 gate\n\n"
    "---\n"
    "📞 اتصل: 01201568888\n"
    "💬 واتساب: 01000059085\n"
    "🌐 petspot.odoo.com\n"
    "📘 فيسبوك: بيت الدواء البيطري -pet spot\n"
    "📍 بجوار بوابة أمواج 1، الطريق الرئيسي، سيدي عبد الرحمن، الساحل الشمالي\n"
    "🗺️ خرائط جوجل: بجوار بوابة أمواج 1"
)

LOCATION_FIXES = (
    (r"📍\s*الساحل\b", "📍 بجوار بوابة أمواج 1، الطريق الرئيسي، سيدي عبد الرحمن"),
    (r"📍\s*Sky Court Mall[^.\n]*", "📍 Beside Amwaj 1 gate, Main Road, Sidi Abdel Rahman"),
    (r"📍\s*مول سكاي كورت[^.\n]*", "📍 بجوار بوابة أمواج 1، الطريق الرئيسي، سيدي عبد الرحمن"),
)


def strip_footer(message: str) -> str:
    body = message or ""
    if MARKER in body:
        body = body.split(MARKER)[0]
    # Remove old footer blocks after --- separators near the end
    body = re.sub(r"\n---\n(?:📞|💬|🌐|📘|💼|📍|🗺️).*$", "", body, flags=re.S)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body


def normalize_body(body: str) -> str:
    for pattern, repl in LOCATION_FIXES:
        body = re.sub(pattern, repl, body)
    body = re.sub(r"\n---\n\s*\n---", "\n---", body)
    body = re.sub(r"(\n---\s*){2,}", "\n---\n", body)
    return body.strip()


def main() -> int:
    load_env_file(MODULE_ROOT / ".env")
    client = get_odoo_client("remote")
    client.authenticate()

    scheduled = client.search_read(
        "social.post",
        [("message", "ilike", f"{PREFIX}%"), ("state", "=", "scheduled")],
        ["id", "message", "state"],
        order="id asc",
    )
    print(f"Found {len(scheduled)} scheduled posts to fix")

    updated = 0
    for post in scheduled:
        body = strip_footer(post["message"])
        body = normalize_body(body)
        new_message = body + FOOTER
        if new_message == post["message"]:
            continue
        client.write("social.post", [post["id"]], {"message": new_message})
        title = body.split("\n", 1)[0][:55]
        print(f"  updated #{post['id']}: {title}")
        updated += 1

    print(f"\nDone. Updated {updated} scheduled posts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
