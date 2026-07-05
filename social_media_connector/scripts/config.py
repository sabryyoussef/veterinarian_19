"""Load .env and build Odoo RPC client + Facebook page map."""
from __future__ import annotations

import os
import sys
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
WEBSITE_ROOT = MODULE_ROOT.parent / "website"
sys.path.insert(0, str(WEBSITE_ROOT))

from odoo_rpc import OdooRPC  # noqa: E402


def load_env_file(path: Path | None = None) -> None:
    path = path or MODULE_ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _normalize_odoo_url(url: str) -> str:
    url = url.rstrip("/")
    if url.endswith("/odoo"):
        url = url[: -len("/odoo")]
    return url


def get_odoo_client(target: str | None = None) -> OdooRPC:
    load_env_file()
    target = target or os.getenv("CONNECTOR_TARGET", "remote")
    if target == "local":
        url = _normalize_odoo_url(os.getenv("LOCAL_ODOO_URL", "http://127.0.0.1:8027"))
        db = os.getenv("LOCAL_ODOO_DB", "pet_spot_elsahel")
        user = os.getenv("LOCAL_ODOO_USERNAME", "admin")
        secret = os.getenv("LOCAL_ODOO_PASSWORD", "admin")
    else:
        url = _normalize_odoo_url(os.getenv("ODOO_URL", ""))
        db = os.getenv("ODOO_DB", "petspot")
        user = os.getenv("ODOO_USERNAME", "")
        secret = os.getenv("ODOO_API_KEY") or os.getenv("ODOO_PASSWORD", "")
    if not url or not db or not user or not secret:
        raise RuntimeError("Missing Odoo credentials in social_media_connector/.env")
    return OdooRPC(url, db, user, secret)


def get_campaign_prefix() -> str:
    load_env_file()
    return os.getenv("CAMPAIGN_PREFIX", "[PetSpot FB]").strip()


def get_page_map(client: OdooRPC | None = None) -> dict[str, dict]:
    """Map FACEBOOK_PAGE_N keys to Odoo social.account ids from .env."""
    load_env_file()
    page_map: dict[str, dict] = {}
    for n in range(1, 21):
        key = f"FACEBOOK_PAGE_{n}"
        name = os.getenv(f"{key}_NAME", "").strip()
        odoo_id = os.getenv(f"{key}_ODOO_ACCOUNT_ID", "").strip()
        fb_id = os.getenv(f"{key}_ID", "").strip()
        url = os.getenv(f"{key}_URL", "").strip()
        if not name and not odoo_id and not fb_id:
            if n > 3:
                break
            continue
        page_map[key] = {
            "name": name,
            "odoo_account_id": int(odoo_id) if odoo_id.isdigit() else None,
            "facebook_account_id": fb_id,
            "url": url,
        }
    return page_map


def resolve_account_id(
    client: OdooRPC,
    page_key: str,
    page_map: dict[str, dict] | None = None,
) -> int:
    """Resolve page_key to social.account id (env first, then search by name)."""
    page_map = page_map or get_page_map()
    entry = page_map.get(page_key)
    if entry and entry.get("odoo_account_id"):
        return entry["odoo_account_id"]

    name = (entry or {}).get("name", "")
    domain: list = [("media_id.media_type", "=", "facebook")]
    if name:
        domain = ["|", ("name", "ilike", name), ("name", "ilike", name.split("/")[0].strip())] + domain

    accounts = client.search_read(
        "social.account",
        domain,
        ["id", "name", "facebook_account_id"],
        limit=5,
    )
    if not accounts:
        raise RuntimeError(
            f"No Facebook social.account for {page_key}. "
            "Run: python3 scripts/discover_pages.py"
        )
    if len(accounts) > 1 and not name:
        names = ", ".join(f"{a['id']}:{a['name']}" for a in accounts)
        raise RuntimeError(f"Ambiguous page_key {page_key}. Set {page_key}_ODOO_ACCOUNT_ID. Found: {names}")
    return accounts[0]["id"]
