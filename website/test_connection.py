#!/usr/bin/env python3
"""Test local and remote Odoo connections + website read access."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from odoo_rpc import OdooRPC  # noqa: E402


def mask(s: str | None) -> str:
    if not s or len(s) < 8:
        return s or "-"
    return s[:4] + "****" + s[-3:]


def test(label: str, url: str, db: str, user: str, secret: str) -> bool:
    print(f"\n=== {label} ===")
    print(f"URL: {url}")
    print(f"DB:  {db}")
    try:
        client = OdooRPC(url, db, user, secret)
        version = client._call("common", "version", [])
        print(f"Server: {version.get('server_version')} ({version.get('server_serie')})")
        uid = client.authenticate()
        print(f"Auth OK: uid={uid}")
        sites = client.search_read("website", [], ["id", "name", "domain"], limit=5)
        pages = client.execute("website.page", "search_count", [])
        print(f"Website sites: {len(sites)} | pages total: {pages}")
        for s in sites:
            print(f"  - id={s['id']} name={s['name']} domain={s.get('domain') or '-'}")
        return True
    except Exception as exc:
        print(f"FAIL: {exc}")
        return False


def main() -> int:
    load_dotenv(ROOT / ".env")
    ok = True
    if os.getenv("LOCAL_ODOO_URL"):
        ok &= test(
            "LOCAL",
            os.environ["LOCAL_ODOO_URL"],
            os.environ["LOCAL_ODOO_DB"],
            os.environ["LOCAL_ODOO_USERNAME"],
            os.environ["LOCAL_ODOO_PASSWORD"],
        )
    remote_secret = os.getenv("REMOTE_ODOO_API_KEY") or os.getenv("REMOTE_ODOO_PASSWORD")
    if os.getenv("REMOTE_ODOO_URL") and remote_secret:
        ok &= test(
            "REMOTE",
            os.environ["REMOTE_ODOO_URL"],
            os.environ["REMOTE_ODOO_DB"],
            os.environ["REMOTE_ODOO_USERNAME"],
            remote_secret,
        )
    print("\n=== SUMMARY ===", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
