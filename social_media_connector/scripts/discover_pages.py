#!/usr/bin/env python3
"""Discover Facebook pages on Odoo Online and print .env mapping hints."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import get_odoo_client, load_env_file, MODULE_ROOT  # noqa: E402


def main() -> int:
    load_env_file(MODULE_ROOT / ".env")
    client = get_odoo_client()
    client.authenticate()
    print(f"Connected to {client.url} db={client.db}\n")

    accounts = client.search_read(
        "social.account",
        [("media_id.media_type", "=", "facebook")],
        ["id", "name", "facebook_account_id", "facebook_access_token"],
        order="id asc",
    )
    if not accounts:
        print("No Facebook social.account found.")
        return 1

    print("# Paste into social_media_connector/.env:\n")
    for i, acc in enumerate(accounts, start=1):
        token = "set" if acc.get("facebook_access_token") else "MISSING"
        print(f"FACEBOOK_PAGE_{i}_NAME={acc['name']}")
        print(f"FACEBOOK_PAGE_{i}_ID={acc.get('facebook_account_id') or ''}")
        print(f"FACEBOOK_PAGE_{i}_URL=")
        print(f"FACEBOOK_PAGE_{i}_ACCESS_TOKEN=")
        print(f"FACEBOOK_PAGE_{i}_ODOO_ACCOUNT_ID={acc['id']}  # token: {token}")
        print()

    print(f"Found {len(accounts)} page(s). Use page_key FACEBOOK_PAGE_1 .. FACEBOOK_PAGE_{len(accounts)} in posts.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
