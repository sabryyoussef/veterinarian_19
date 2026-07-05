#!/usr/bin/env python3
"""Deploy PetSpot El Sahel website to local or remote Odoo via JSON-RPC."""
from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOGO_DIR = ROOT / "assets" / "logo"
LOGO_SVG = LOGO_DIR / "logo.svg"
LOGO_PNG = LOGO_DIR / "petspot-logo.png"
sys.path.insert(0, str(ROOT))


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


from gallery_build import prepare_gallery  # noqa: E402
from odoo_rpc import OdooRPC  # noqa: E402
from page_templates import build_contact_arch, build_footer_inherit_arch, build_homepage_arch  # noqa: E402
from site_config import load_config  # noqa: E402


def sync_logo_png() -> Path | None:
    """Export logo.svg → petspot-logo.png for Odoo (PNG renders reliably in company logo)."""
    if not LOGO_SVG.is_file():
        return LOGO_PNG if LOGO_PNG.is_file() else None
    if LOGO_PNG.is_file() and LOGO_PNG.stat().st_mtime >= LOGO_SVG.stat().st_mtime:
        return LOGO_PNG
    import subprocess

    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "rsvg-convert",
            "-w",
            "800",
            str(LOGO_SVG),
            "-o",
            str(LOGO_PNG),
        ],
        check=True,
        capture_output=True,
    )
    return LOGO_PNG


def load_logo_b64() -> str | None:
    """Load unified clinic logo for res.company (PNG export of logo.svg)."""
    path = sync_logo_png()
    if path and path.is_file():
        return base64.b64encode(path.read_bytes()).decode()
    return None


def _attachment_has_data(client: OdooRPC, att_id: int) -> bool:
    row = client.search_read(
        "ir.attachment",
        [("id", "=", att_id)],
        ["file_size", "checksum"],
        limit=1,
    )
    return bool(row and row[0].get("file_size") and row[0].get("checksum"))


def _store_attachment_bytes(
    client: OdooRPC,
    *,
    name: str,
    mimetype: str,
    raw_b64: str,
    att_id: int | None,
) -> int:
    """Store image bytes; Odoo Online needs `raw`, local Odoo needs `datas`."""
    base_vals = {"mimetype": mimetype, "type": "binary"}
    attempts: list[tuple[str, dict]] = [
        ("datas", {**base_vals, "datas": raw_b64}),
        ("raw", {**base_vals, "raw": raw_b64}),
    ]
    last_error: Exception | None = None
    for _label, payload in attempts:
        try:
            if att_id:
                client.write("ir.attachment", [att_id], payload)
                candidate = att_id
            else:
                candidate = client.create(
                    "ir.attachment",
                    {"name": name, "public": True, **payload},
                )
            if _attachment_has_data(client, candidate):
                return candidate
        except RuntimeError as exc:
            last_error = exc
    if att_id and last_error:
        raise last_error
    raise RuntimeError(f"Attachment upload failed for {name}")


def ensure_public_image(client: OdooRPC, name: str, path: Path) -> str:
    """Upload or refresh a public attachment; return Odoo image URL."""
    if not path.exists():
        raise FileNotFoundError(path)
    mimetype = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }.get(path.suffix.lower(), "application/octet-stream")
    raw_b64 = base64.b64encode(path.read_bytes()).decode()
    existing = client.search_read(
        "ir.attachment",
        [("name", "=", name), ("public", "=", True)],
        ["id"],
        limit=1,
    )
    att_id = existing[0]["id"] if existing else None
    att_id = _store_attachment_bytes(
        client,
        name=name,
        mimetype=mimetype,
        raw_b64=raw_b64,
        att_id=att_id,
    )
    return f"/web/image/ir.attachment/{att_id}/datas"


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


def deploy_footer(client: OdooRPC, c: dict, website_id: int) -> None:
    layouts = client.search_read("ir.ui.view", [("key", "=", "website.layout")], ["id"], limit=1)
    if not layouts:
        print("  Footer: website.layout view not found")
        return
    layout_id = layouts[0]["id"]
    arch = build_footer_inherit_arch(c)
    existing = client.search_read(
        "ir.ui.view",
        [("name", "=", "PetSpot Footer"), ("website_id", "=", website_id)],
        ["id"],
        limit=1,
    )
    vals = {
        "name": "PetSpot Footer",
        "type": "qweb",
        "mode": "extension",
        "inherit_id": layout_id,
        "arch_db": arch,
        "priority": 99,
        "website_id": website_id,
        "active": True,
    }
    if existing:
        client.write("ir.ui.view", [existing[0]["id"]], vals)
        print(f"Updated footer view {existing[0]['id']}")
    else:
        footer_id = client.create("ir.ui.view", vals)
        print(f"Created footer view {footer_id}")


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
        "street": c["address_en"],
        "city": "Sidi Abdel Rahman",
        "country_id": 65,
        "social_facebook": c["facebook"],
        "social_instagram": c["instagram"],
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
    website_vals = {"name": c["company_name"]}
    if logo_b64:
        website_vals["logo"] = logo_b64
    client.write("website", [website_id], website_vals)
    print(f"Updated website id={website_id}" + (" (navbar logo set)" if logo_b64 else ""))

    hero_path = ROOT / "assets" / "clinic-hero.png"
    if hero_path.exists():
        c["hero_image_url"] = ensure_public_image(client, "petspot-clinic-hero", hero_path)
        print(f"Uploaded clinic hero image → {c['hero_image_url']}")
    c["logo_url"] = "/web/image/res.company/1/logo"

    c["gallery_urls"] = {}
    c["gallery_items"] = []
    gallery_dir = ROOT / "assets" / "gallery"
    selection = prepare_gallery(
        gallery_dir,
        extra_count=c.get("gallery_extra_count", 12),
    )
    if selection:
        print(
            f"Gallery selection: {selection['slot_count']} featured + "
            f"{selection['extra_count']} extra from Facebook"
        )

    for slot in c["gallery_slots"]:
        image_path = gallery_dir / slot["file"]
        if image_path.is_file():
            att_name = f"petspot-gallery-{slot['id']}"
            url = ensure_public_image(client, att_name, image_path)
            c["gallery_urls"][slot["id"]] = url
            c["gallery_items"].append({"url": url, "alt": slot["alt"]})
            print(f"Uploaded gallery {slot['file']} → {url}")

    if selection:
        for extra in selection["extras"]:
            image_path = gallery_dir / extra["file"]
            if not image_path.is_file():
                continue
            att_name = f"petspot-gallery-fb-{extra['id']}"
            url = ensure_public_image(client, att_name, image_path)
            c["gallery_items"].append({"url": url, "alt": extra["alt"]})
            print(f"Uploaded gallery {extra['file']} → {url}")

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

    deploy_footer(client, c, website_id)

    print(f"Deploy complete ({label})")


def main() -> int:
    load_env_file(ROOT / ".env")
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
