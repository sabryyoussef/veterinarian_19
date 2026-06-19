#!/usr/bin/env python3
"""Deploy PetSpot El Sahel website to local or remote Odoo via JSON-RPC."""
from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from odoo_rpc import OdooRPC  # noqa: E402
from page_templates import build_contact_arch, build_homepage_arch  # noqa: E402
from site_config import load_config  # noqa: E402


def load_logo_b64() -> str | None:
    """Load logo for res.company — prefers assets/logo/petspot-logo.png."""
    # TODO: Replace petspot-logo.png with final brand asset from logo brief
    for rel in ("assets/logo/petspot-logo.png", "assets/logo.png"):
        path = ROOT / rel
        if path.exists():
            return base64.b64encode(path.read_bytes()).decode()
    return None


def install_module(client: OdooRPC, name: str) -> None:
    mods = client.search_read("ir.module.module", [("name", "=", name)], ["id", "state"])
    if not mods:
        print(f"  Module {name} not found")
        return
    mod = mods[0]
    if mod["state"] == "installed":
        print(f"  {name}: already installed")
        return
    print(f"  Installing {name}...")
    client.execute("ir.module.module", "button_immediate_install", [mod["id"]])


def install_arabic(client: OdooRPC) -> None:
    langs = client.search_read(
        "res.lang",
        [("code", "in", ["ar_001", "ar_SY", "ar_EG"])],
        ["id", "code", "active"],
        limit=1,
    )
    if not langs:
        print("  Arabic: not in database — inline AR+EN copy used on homepage")
        return
    lang = langs[0]
    if lang.get("active"):
        print(f"  Arabic ({lang['code']}) already active")
        return
    print(f"  Activating Arabic ({lang['code']})...")
    wiz_id = client.create("base.language.install", {"overwrite": False, "lang_ids": [(6, 0, [lang["id"]])]})
    client.execute("base.language.install", "lang_install", [wiz_id])


def deploy_to(client: OdooRPC, c: dict, label: str, install_theme: bool = False) -> None:
    print(f"\n--- Deploying to {label} ---")
    client.authenticate()
    print("Connected")

    logo_b64 = load_logo_b64()
    company_vals = {
        "name": c["company_name"],
        "phone": c["phone"],
        "email": c["email"],
        "website": c["website_url"],
        "street": c["area_en"],
        "city": "North Coast",
        "country_id": 65,
    }
    if logo_b64:
        company_vals["logo"] = logo_b64
    client.write("res.company", [1], company_vals)
    print("Updated res.company")

    websites = client.search_read("website", [], ["id", "name"], limit=1)
    if not websites:
        print("ERROR: no website record", file=sys.stderr)
        return
    website_id = websites[0]["id"]
    client.write("website", [website_id], {"name": c["company_name"]})
    print(f"Updated website id={website_id}")

    if install_theme:
        print("Modules & languages:")
        install_module(client, "website")
        install_module(client, "theme_beauty")
        install_arabic(client)

    home_pages = client.search_read(
        "website.page",
        [("website_id", "=", website_id), ("url", "=", "/")],
        ["id", "view_id", "name"],
        limit=5,
    )
    if not home_pages:
        home_pages = client.search_read(
            "website.page",
            [("url", "=", "/")],
            ["id", "view_id", "name", "website_id"],
            limit=5,
        )
    if not home_pages:
        print("ERROR: no homepage found", file=sys.stderr)
        return

    home = home_pages[0]
    view_id = home["view_id"][0] if isinstance(home["view_id"], list) else home["view_id"]
    seo = c["seo"]
    client.write("ir.ui.view", [view_id], {"arch_db": build_homepage_arch(c)})
    page_vals = {
        "is_published": True,
        "name": "Home",
        "website_meta_title": seo["title"],
        "website_meta_description": seo["description"],
    }
    if home.get("website_id") in (False, None) or (isinstance(home.get("website_id"), list) and not home["website_id"]):
        page_vals["website_id"] = website_id
    client.write("website.page", [home["id"]], page_vals)
    print(f"Updated homepage view {view_id} (page {home['id']})")

    dupes = client.search_read(
        "website.page",
        [("url", "=", "/"), ("id", "!=", home["id"])],
        ["id", "website_id"],
    )
    for d in dupes:
        if d["id"] != home["id"]:
            client.write("website.page", [d["id"]], {"is_published": False})
            print(f"Unpublished duplicate homepage page {d['id']}")

    contact_pages = client.search_read(
        "website.page",
        [("url", "=", "/contactus")],
        ["id", "view_id"],
        limit=1,
    )
    if contact_pages:
        cp = contact_pages[0]
        cv_id = cp["view_id"][0] if isinstance(cp["view_id"], list) else cp["view_id"]
        client.write("ir.ui.view", [cv_id], {"arch_db": build_contact_arch(c)})
        client.write(
            "website.page",
            [cp["id"]],
            {
                "is_published": True,
                "website_id": website_id,
                "website_meta_title": f"Contact | {seo['title']}",
                "website_meta_description": seo["description"],
            },
        )
        print(f"Updated contact page view {cv_id}")

    print(f"Deploy complete ({label})")


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Deploy PetSpot website to Odoo")
    parser.add_argument(
        "--target",
        choices=("local", "remote", "both"),
        default="remote",
        help="Odoo instance to update (default: remote)",
    )
    args = parser.parse_args()
    c = load_config()

    if args.target in ("local", "both"):
        local_secret = os.getenv("LOCAL_ODOO_PASSWORD", "admin")
        local_client = OdooRPC(
            os.environ.get("LOCAL_ODOO_URL", "http://127.0.0.1:8027"),
            os.environ.get("LOCAL_ODOO_DB", "pet_spot_elsahel"),
            os.environ.get("LOCAL_ODOO_USERNAME", "admin"),
            local_secret,
        )
        deploy_to(local_client, c, "LOCAL", install_theme=True)

    if args.target in ("remote", "both"):
        secret = os.getenv("REMOTE_ODOO_API_KEY") or os.getenv("REMOTE_ODOO_PASSWORD")
        if not secret:
            print("Set REMOTE_ODOO_API_KEY or REMOTE_ODOO_PASSWORD in website/.env", file=sys.stderr)
            return 1
        remote_client = OdooRPC(
            os.environ["REMOTE_ODOO_URL"],
            os.environ["REMOTE_ODOO_DB"],
            os.environ["REMOTE_ODOO_USERNAME"],
            secret,
        )
        deploy_to(remote_client, c, "REMOTE", install_theme=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
