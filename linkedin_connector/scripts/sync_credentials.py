#!/usr/bin/env python3
"""Sync primary + test LinkedIn accounts from .env into Odoo linkedin.account."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

MODULE_ROOT = Path(__file__).resolve().parents[1]
WEBSITE_ROOT = MODULE_ROOT.parent / "website"
sys.path.insert(0, str(WEBSITE_ROOT))

from odoo_rpc import OdooRPC  # noqa: E402


def _env(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def _account_config(label: str, keys: dict) -> dict | None:
    client_id = _env(keys["client_id"])
    client_secret = _env(keys["client_secret"])
    if not client_id or not client_secret:
        return None
    return {
        "label": label,
        "name": _env(keys["name"], label),
        "client_id": client_id,
        "client_secret": client_secret,
        "scopes": _env(keys["scopes"], "openid profile w_member_social"),
        "org_id": _env(keys["org_id"]),
        "email": _env(keys.get("email", "")),
    }


def _upsert(client: OdooRPC, cfg: dict, public_base: str) -> int:
    existing = client.search_read("linkedin.account", [("name", "=", cfg["name"])], ["id"], limit=1)
    vals = {
        "name": cfg["name"],
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "oauth_scopes": cfg["scopes"],
    }
    if public_base:
        vals["oauth_public_base_url"] = public_base.rstrip("/")
    if cfg["org_id"]:
        vals["linkedin_organization_id"] = cfg["org_id"]

    if existing:
        acc_id = existing[0]["id"]
        client.write("linkedin.account", [acc_id], vals)
        print(f"Updated id={acc_id} — {cfg['name']}")
    else:
        acc_id = client.create("linkedin.account", vals)
        print(f"Created id={acc_id} — {cfg['name']}")

    if cfg.get("email"):
        print(f"  Sign in as: {cfg['email']}")
    if cfg.get("org_id"):
        print(f"  Company page: urn:li:organization:{cfg['org_id']}")
    return acc_id


def main() -> int:
    load_dotenv(MODULE_ROOT / ".env")

    client = OdooRPC(
        _env("ODOO_URL", "http://127.0.0.1:8027"),
        _env("ODOO_DB", "pet_spot_elsahel"),
        _env("ODOO_USERNAME", "admin"),
        _env("ODOO_PASSWORD") or _env("ODOO_API_KEY", "admin"),
    )
    client.authenticate()
    print(f"Connected to {_env('ODOO_URL')} (db={_env('ODOO_DB')})\n")

    public_base = _env("LINKEDIN_PUBLIC_BASE_URL")
    configs = [
        _account_config("Primary", {
            "client_id": "LINKEDIN_CLIENT_ID",
            "client_secret": "LINKEDIN_CLIENT_SECRET",
            "name": "LINKEDIN_ACCOUNT_NAME",
            "scopes": "LINKEDIN_OAUTH_SCOPES",
            "org_id": "LINKEDIN_ORGANIZATION_ID",
            "email": "LINKEDIN_EMAIL",
        }),
        _account_config("Test", {
            "client_id": "LINKEDIN_TEST_CLIENT_ID",
            "client_secret": "LINKEDIN_TEST_CLIENT_SECRET",
            "name": "LINKEDIN_TEST_ACCOUNT_NAME",
            "scopes": "LINKEDIN_TEST_OAUTH_SCOPES",
            "org_id": "LINKEDIN_TEST_ORGANIZATION_ID",
            "email": "LINKEDIN_TEST_EMAIL",
        }),
    ]

    for cfg in configs:
        if not cfg:
            continue
        print(f"=== {cfg['label']} ===")
        _upsert(client, cfg, public_base)
        print()

    db = _env("ODOO_DB", "pet_spot_elsahel")
    if public_base:
        print(f"Redirect URI:\n  {public_base.rstrip('/')}/linkedin_connector/callback?db={db}")
    print("\nConnect test account: Odoo → LinkedIn → Accounts → PetSpot LinkedIn (Test) → Connect")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
