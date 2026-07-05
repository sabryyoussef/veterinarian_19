#!/usr/bin/env python3
"""Verify LinkedIn app credentials, token scopes, and company page readiness."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

MODULE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = MODULE_ROOT.parent
WEBSITE_ROOT = PROJECT_ROOT / "website"
sys.path.insert(0, str(WEBSITE_ROOT))

from odoo_rpc import OdooRPC  # noqa: E402

REQUIRED_ORG_SCOPE = "w_organization_social"


def mask(value: str | None) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 6:
        return "****"
    return value[:4] + "****" + value[-3:]


def test_linkedin_app(client_id: str, client_secret: str, redirect_uri: str) -> tuple[bool, str]:
    try:
        resp = requests.post(
            "https://www.linkedin.com/oauth/v2/accessToken",
            data={
                "grant_type": "authorization_code",
                "code": "invalid-test-code",
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        return False, f"Network error: {exc}"

    body = resp.text[:300]
    if resp.status_code == 401 and "invalid_client" in body:
        return False, "LinkedIn rejected client_id/client_secret (HTTP 401)"
    if "authorization code not found" in body or "invalid_grant" in body:
        return True, "App credentials accepted by LinkedIn (OAuth endpoint reachable)"
    if resp.status_code == 200:
        return True, "Unexpected success on test exchange"
    return False, f"Unexpected HTTP {resp.status_code}: {body}"


def introspect_scopes(client_id: str, client_secret: str, token: str) -> tuple[str, bool]:
    resp = requests.post(
        "https://www.linkedin.com/oauth/v2/introspectToken",
        data={"client_id": client_id, "client_secret": client_secret, "token": token},
        timeout=15,
    )
    if resp.status_code != 200:
        return "", False
    scope = (resp.json().get("scope") or "").replace(" ", "")
    has_org = REQUIRED_ORG_SCOPE in scope.split(",")
    return scope, has_org


def main() -> int:
    load_dotenv(MODULE_ROOT / ".env")

    url = os.getenv("ODOO_URL", "http://127.0.0.1:8027")
    db = os.getenv("ODOO_DB", "pet_spot_elsahel")
    user = os.getenv("ODOO_USERNAME", "admin")
    secret = os.getenv("ODOO_PASSWORD") or os.getenv("ODOO_API_KEY", "admin")

    print("=== Odoo ===")
    print(f"URL: {url}")
    print(f"DB:  {db}")
    try:
        client = OdooRPC(url, db, user, secret)
        client.authenticate()
        print("Auth OK")
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1

    fields = [
        "id", "name", "client_id", "client_secret", "oauth_public_base_url",
        "oauth_scopes", "connected", "access_token",
        "linkedin_organization_id", "linkedin_organization_urn",
    ]
    accounts = client.search_read("linkedin.account", [], fields, limit=1)
    if not accounts:
        print("FAIL: no linkedin.account — run scripts/sync_credentials.py first")
        return 1

    acc = accounts[0]
    cid = acc.get("client_id") or ""
    csec = acc.get("client_secret") or ""
    print(f"Account: id={acc['id']} name={acc['name']}")
    print(f"client_id:     {mask(cid)}")
    print(f"oauth scopes:  {acc.get('oauth_scopes') or '-'}")
    print(f"org URN:       {acc.get('linkedin_organization_urn') or '(not set)'}")
    print(f"connected:     {acc.get('connected')}")

    if not cid or not csec:
        print("FAIL: client_id or client_secret missing")
        return 1

    print("\n=== LinkedIn API (app credentials) ===")
    redirect = f"{(acc.get('oauth_public_base_url') or url).rstrip('/')}/linkedin_connector/callback?db={db}"
    ok, msg = test_linkedin_app(cid, csec, redirect)
    print(msg)
    if not ok:
        return 1

    print("\n=== Token scopes (company page milestone) ===")
    token = acc.get("access_token")
    if not token:
        print("Not connected — complete OAuth: Disconnect → Connect in Odoo")
        print(f"Redirect URI: {redirect}")
        return 0

    scope_str, has_org = introspect_scopes(cid, csec, token)
    print(f"token scopes: {scope_str or '(introspect failed)'}")
    if has_org:
        print(f"OK — {REQUIRED_ORG_SCOPE} present (company page posting allowed)")
    else:
        print(f"WARN — {REQUIRED_ORG_SCOPE} missing on current token")
        print("Fix: LinkedIn Developers → Community Management API → Disconnect → Connect in Odoo")

    print("\n=== SUMMARY ===")
    if acc.get("connected") and has_org and acc.get("linkedin_organization_urn"):
        print("READY — run: ../../venv19/bin/python3 scripts/run_test_post.py")
    elif acc.get("connected"):
        print("Connected but not ready for company page posts — reconnect after org scope is granted")
    else:
        print("Connect account in Odoo first")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
