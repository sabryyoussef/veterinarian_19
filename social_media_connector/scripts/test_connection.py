#!/usr/bin/env python3
"""Test Odoo Online connection and list Facebook social.account records."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import get_odoo_client, load_env_file, MODULE_ROOT  # noqa: E402


def main() -> int:
    load_env_file(MODULE_ROOT / ".env")
    client = get_odoo_client()
    client.authenticate()
    print(f"Connected uid={client.uid}")

    for mod in ("social", "social_facebook"):
        rows = client.search_read("ir.module.module", [("name", "=", mod)], ["name", "state"])
        if not rows:
            print(f"  {mod}: NOT FOUND")
        else:
            print(f"  {mod}: {rows[0]['state']}")

    accounts = client.search_read(
        "social.account",
        [("media_id.media_type", "=", "facebook")],
        ["id", "name", "facebook_account_id", "facebook_access_token", "has_account_stats"],
        order="id asc",
    )
    if not accounts:
        print("\nNo Facebook social.account records. Connect Facebook in Odoo Social Marketing.")
        return 1

    print(f"\nFacebook pages ({len(accounts)}):")
    for acc in accounts:
        token_ok = bool(acc.get("facebook_access_token"))
        print(
            f"  id={acc['id']}  name={acc['name']!r}  "
            f"fb_page_id={acc.get('facebook_account_id') or '-'}  token={'yes' if token_ok else 'NO'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
