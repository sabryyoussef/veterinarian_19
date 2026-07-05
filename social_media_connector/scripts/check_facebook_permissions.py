#!/usr/bin/env python3
"""Diagnose Facebook page token permissions on Odoo Online social.account."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import get_odoo_client, load_env_file, MODULE_ROOT  # noqa: E402

GRAPH = "https://graph.facebook.com/v17.0"
REQUIRED = {
    "pages_manage_posts",
    "pages_read_engagement",
    "pages_manage_metadata",
    "pages_read_user_content",
    "pages_manage_engagement",
    "pages_manage_ads",
    "pages_show_list",
    "pages_messaging",
}


def graph_get(path: str, token: str, params: dict | None = None) -> dict:
    q = dict(params or {})
    q["access_token"] = token
    url = f"{GRAPH}/{path}?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"error": {"message": body, "code": exc.code}}


def main() -> int:
    load_env_file(MODULE_ROOT / ".env")
    client = get_odoo_client()
    client.authenticate()
    print(f"Remote: {client.url} db={client.db}\n")

    accounts = client.search_read(
        "social.account",
        [("media_id.media_type", "=", "facebook"), ("id", "=", 4)],
        ["id", "name", "facebook_account_id", "facebook_access_token"],
        limit=1,
    )
    if not accounts:
        accounts = client.search_read(
            "social.account",
            [("media_id.media_type", "=", "facebook")],
            ["id", "name", "facebook_account_id", "facebook_access_token"],
            order="id asc",
            limit=1,
        )
    if not accounts:
        print("No Facebook social.account found.", file=sys.stderr)
        return 1

    acc = accounts[0]
    token = acc.get("facebook_access_token") or ""
    page_id = acc.get("facebook_account_id") or ""
    print(f"Account: {acc['name']} (odoo id={acc['id']}, page_id={page_id})")
    if not token:
        print("ERROR: facebook_access_token is MISSING — reconnect Facebook in Odoo Online.")
        return 1

    debug = graph_get("debug_token", token, {"input_token": token})
    data = debug.get("data") or {}
    print(f"\nToken type: {data.get('type', '?')}")
    print(f"App id: {data.get('app_id', '?')}")
    print(f"Valid: {data.get('is_valid', '?')}")
    expires = data.get("expires_at", 0)
    print(f"Expires at: {expires or 'never (long-lived page token)'}")

    scopes = set(data.get("scopes") or [])
    if scopes:
        print(f"\nGranted scopes ({len(scopes)}):")
        for s in sorted(scopes):
            mark = "OK" if s in REQUIRED or s.startswith("pages_") else "  "
            print(f"  [{mark}] {s}")
    else:
        print("\nCould not read scopes from debug_token.")

    missing = sorted(REQUIRED - scopes)
    if missing:
        print(f"\nMISSING recommended scopes: {', '.join(missing)}")

    # Live permission check: read page + test photo upload capability
    page_info = graph_get(page_id, token, {"fields": "id,name,access_token"})
    if page_info.get("error"):
        err = page_info["error"]
        print(f"\nPage API error: {err.get('message')} (code {err.get('code')})")
    else:
        print(f"\nPage reachable: {page_info.get('name')} (id={page_info.get('id')})")

    # Minimal photo upload test (1x1 PNG) — same endpoint Odoo uses
    tiny_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    boundary = "----OdooFbDiag"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="caption"\r\n\r\n'
        f"permission test\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="access_token"\r\n\r\n'
        f"{token}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="published"\r\n\r\n'
        f"false\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="source"; filename="test.png"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode() + tiny_png + f"\r\n--{boundary}--\r\n".encode()

    upload_url = f"{GRAPH}/{page_id}/photos"
    req = urllib.request.Request(
        upload_url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
        print(f"\nPhoto upload test: OK (unpublished draft id={result.get('id')})")
        if result.get("id"):
            graph_get(result["id"], token, {})  # noqa: keep draft unpublished
    except urllib.error.HTTPError as exc:
        result = json.loads(exc.read().decode())
        err = result.get("error", {})
        print(f"\nPhoto upload test: FAILED")
        print(f"  {err.get('message')}")
        if "permission" in (err.get("message") or "").lower():
            print("\nFIX: Reconnect Facebook in Odoo Online (see FACEBOOK_SETUP.md).")
            return 2

    if missing:
        print("\nFIX: Reconnect Facebook in Odoo Online to refresh page token scopes.")
        return 2
    print("\nToken looks healthy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
