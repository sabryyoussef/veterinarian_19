#!/usr/bin/env python3
"""Run LinkedIn test post via Odoo linkedin.account.action_test_post."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

MODULE_ROOT = Path(__file__).resolve().parents[1]
WEBSITE_ROOT = MODULE_ROOT.parent / "website"
sys.path.insert(0, str(WEBSITE_ROOT))

from odoo_rpc import OdooRPC  # noqa: E402


def main() -> int:
    load_dotenv(MODULE_ROOT / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--account",
        choices=("primary", "test"),
        default="test",
        help="Which linkedin.account to use (default: test)",
    )
    args = parser.parse_args()

    account_name = (
        os.getenv("LINKEDIN_TEST_ACCOUNT_NAME", "PetSpot LinkedIn (Test)")
        if args.account == "test"
        else os.getenv("LINKEDIN_ACCOUNT_NAME", "PetSpot LinkedIn")
    )

    client = OdooRPC(
        os.getenv("ODOO_URL", "http://127.0.0.1:8027"),
        os.getenv("ODOO_DB", "pet_spot_elsahel"),
        os.getenv("ODOO_USERNAME", "admin"),
        os.getenv("ODOO_PASSWORD") or os.getenv("ODOO_API_KEY", "admin"),
    )
    client.authenticate()
    print(f"Connected to Odoo (db={os.getenv('ODOO_DB')})")

    accounts = client.search_read(
        "linkedin.account",
        [("name", "=", account_name)],
        ["id", "name", "access_token", "linkedin_member_urn", "connected", "linkedin_organization_id"],
        limit=1,
    )
    if not accounts:
        accounts = client.search_read(
            "linkedin.account",
            [],
            ["id", "name", "access_token", "linkedin_member_urn", "connected", "linkedin_organization_id"],
            limit=5,
        )
        print(f"Account '{account_name}' not found. Available:", [a["name"] for a in accounts])
        return 1

    acc = accounts[0]
    acc_id = acc["id"]
    print(f"Account: {acc['name']} (id={acc_id}) org={acc.get('linkedin_organization_id') or 'not set'}")

    if args.account == "test":
        print(f"Sign in as: {os.getenv('LINKEDIN_TEST_EMAIL', 'vetdrughouse@gmail.com')}")

    if not acc.get("access_token") or not acc.get("linkedin_member_urn"):
        print("\nNot connected. Open this URL, sign in, approve, then re-run:")
        action = client.execute("linkedin.account", "action_connect", [acc_id])
        if isinstance(action, dict) and action.get("url"):
            print(action["url"])
        return 2

    print("Sending test post to company page...")
    try:
        client.execute("linkedin.account", "action_test_post", [acc_id])
        print("SUCCESS — test post published")
        return 0
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
