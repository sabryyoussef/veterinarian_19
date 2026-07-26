#!/usr/bin/env python3
"""Production deploy: pet.spot location correction only (Test-validated).

Approved scope: website NAP/banner/JSON-LD/pages/articles CTAs + WhatsApp direction templates.
Does NOT: GBP, FB schedule, external listings, DNS/Cloudflare, social.post recreate/unlink.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOC = ROOT.parent / "docs" / "seo_ai_visibility" / "2026-07-24_read_only_audit"
EVIDENCE = DOC / "prod_uat_evidence"
sys.path.insert(0, str(ROOT))

from deploy import deploy_to, load_env_file  # noqa: E402
from implement_test_seo import (  # noqa: E402
    ARTICLES,
    configure_blog,
    create_draft_articles,
    ensure_service_pages,
    fix_placeholder_phones,
)
from odoo_rpc import OdooRPC  # noqa: E402
from site_config import load_config  # noqa: E402

PROD_URL = os.environ.get("PROD_ODOO_URL", "http://127.0.0.1:8027")
PROD_DB = os.environ.get("PROD_ODOO_DB", "pet_spot_elsahel")
PROD_USER = os.environ.get("PROD_ODOO_USERNAME", "admin")
PROD_PASS = os.environ.get("PROD_ODOO_PASSWORD", "admin")
PUBLIC = "https://drpaws.ai"
WEBSITE_ID = 1
NEW_MAPS = "https://www.google.com/maps?q=30.9909056,28.6842417"
OLD_MAPS = "https://maps.app.goo.gl/AaHup6NEFodZEs7S7"


def apply_env() -> None:
    os.environ["WEBSITE_URL"] = PUBLIC
    os.environ["CLINIC_PHONE"] = "+201280833332"
    os.environ["CLINIC_CALL_CENTER"] = "+201201568888"
    os.environ["CLINIC_WHATSAPP"] = "201000059085"
    os.environ["CLINIC_EMAIL"] = "vetelsahel@gmail.com"
    os.environ["CLINIC_COMPANY_NAME"] = "pet.spot"
    os.environ["CLINIC_ADDRESS_EN"] = (
        "Main Road, beside Amwaj Gate 1, Sidi Abdel Rahman, North Coast, Egypt"
    )
    os.environ["CLINIC_ADDRESS_AR"] = (
        "الطريق الرئيسي، بجوار بوابة أمواج 1، سيدي عبد الرحمن، الساحل الشمالي، مصر"
    )
    os.environ["CLINIC_AREA_EN"] = "Amwaj Gate 1 · Sidi Abdel Rahman · North Coast"
    os.environ["CLINIC_AREA_AR"] = "بوابة أمواج 1 · سيدي عبد الرحمن · الساحل الشمالي"
    os.environ["CLINIC_MAP_URL"] = NEW_MAPS
    os.environ["CLINIC_FACEBOOK"] = "https://www.facebook.com/animalcarecenterpetspots"
    os.environ["CLINIC_INSTAGRAM"] = "https://www.instagram.com/pet_spot_clinic/"
    os.environ["CLINIC_LAT"] = "30.9909056"
    os.environ["CLINIC_LNG"] = "28.6842417"


def snapshot_fb(rpc: OdooRPC) -> list[dict]:
    return rpc.search_read(
        "social.post",
        [("id", "in", [1, 2, 3])],
        ["id", "state", "scheduled_date", "live_post_ids", "image_ids"],
    )


def update_whatsapp_templates(rpc: OdooRPC) -> list[dict]:
    """Rewrite identifiable direction templates to the new Maps URL."""
    updated: list[dict] = []
    models = rpc.search_read(
        "ir.model",
        [("model", "ilike", "whatsapp")],
        ["model"],
        limit=80,
    )
    # Also mail.template / sms
    model_names = [m["model"] for m in models] + ["mail.template"]
    for model in model_names:
        try:
            fields = rpc.execute(
                model, "fields_get", [], {"attributes": ["type", "string"]}
            )
        except Exception:
            continue
        text_fields = [
            f
            for f, meta in fields.items()
            if meta.get("type") in ("html", "text", "char")
            and any(
                k in f.lower()
                for k in ("body", "content", "message", "template", "text")
            )
        ]
        if not text_fields:
            continue
        # Search by old maps or Amwaj 2 in any text field via OR domain
        domain: list = ["|"] * (len(text_fields) * 2 - 1) if len(text_fields) > 1 else []
        # Build simpler: search each field
        seen_ids: set[int] = set()
        for field in text_fields:
            for needle in [OLD_MAPS, "AaHup6NEFodZEs7S7", "Amwaj 2", "أمواج 2", "Wahat Khattab"]:
                try:
                    rows = rpc.search_read(
                        model,
                        [(field, "ilike", needle.split("/")[-1] if "http" in needle else needle)],
                        ["id", field],
                        limit=100,
                    )
                except Exception:
                    continue
                for row in rows:
                    if row["id"] in seen_ids:
                        continue
                    body = row.get(field) or ""
                    if not isinstance(body, str):
                        continue
                    if (
                        OLD_MAPS not in body
                        and "AaHup6" not in body
                        and "Amwaj 2" not in body
                        and "أمواج 2" not in body
                        and "Wahat Khattab" not in body
                        and "واحة خطاب" not in body
                    ):
                        continue
                    new = body.replace(OLD_MAPS, NEW_MAPS)
                    new = new.replace("Amwaj 2", "Amwaj Gate 1").replace(
                        "أمواج 2", "بوابة أمواج 1"
                    )
                    new = new.replace("Wahat Khattab", "Amwaj Gate 1").replace(
                        "واحة خطاب", "بوابة أمواج 1"
                    )
                    # Neutralize move language if present in templates
                    new = re.sub(
                        r"opposite (our )?previous location",
                        "beside Amwaj Gate 1",
                        new,
                        flags=re.I,
                    )
                    if new == body:
                        continue
                    try:
                        rpc.write(model, [row["id"]], {field: new})
                        seen_ids.add(row["id"])
                        updated.append(
                            {"model": model, "id": row["id"], "field": field}
                        )
                    except Exception as exc:  # noqa: BLE001
                        updated.append(
                            {
                                "model": model,
                                "id": row["id"],
                                "field": field,
                                "error": str(exc)[:200],
                            }
                        )
    return updated


def patch_published_articles_content(rpc: OdooRPC) -> list[dict]:
    """Update blog.post bodies that still mention Amwaj 2 / old maps."""
    posts = rpc.search_read(
        "blog.post",
        [],
        ["id", "name", "content", "is_published", "website_url"],
        limit=50,
    )
    out = []
    for p in posts:
        content = p.get("content") or ""
        if not isinstance(content, str):
            continue
        if not any(
            x in content
            for x in (
                "Amwaj 2",
                "أمواج 2",
                "Wahat Khattab",
                "واحة خطاب",
                "AaHup6",
                "30.9909989",
                "Pet Spot Clinic",
                "/g/11w2cv6pz0",
                "previous location",
                "موقعنا السابق",
            )
        ):
            continue
        new = content
        new = new.replace(OLD_MAPS, NEW_MAPS)
        new = new.replace("Amwaj 2", "Amwaj Gate 1").replace("أمواج 2", "بوابة أمواج 1")
        new = new.replace("beside Wahat Khattab, in front of Amwaj Gate 1", "beside Amwaj Gate 1")
        new = new.replace("Wahat Khattab", "Amwaj Gate 1").replace("واحة خطاب", "بوابة أمواج 1")
        new = new.replace("Pet Spot Clinic", "pet.spot")
        new = new.replace("https://www.google.com/search?kgmid=/g/11w2cv6pz0", "")
        new = new.replace("/g/11w2cv6pz0", "")
        new = re.sub(
            r"opposite (our )?previous (PetSpot )?location",
            "on the Main Road",
            new,
            flags=re.I,
        )
        new = new.replace("مقابل موقعنا السابق", "على الطريق الرئيسي")
        new = new.replace("مقابل موقع بيت سبوت السابق", "على الطريق الرئيسي")
        if new != content:
            rpc.write("blog.post", [p["id"]], {"content": new})
            out.append(
                {
                    "id": p["id"],
                    "name": p["name"],
                    "published": p.get("is_published"),
                    "url": p.get("website_url"),
                }
            )
    return out


def main() -> int:
    load_env_file(ROOT / ".env")
    apply_env()
    EVIDENCE.mkdir(parents=True, exist_ok=True)

    c = load_config()
    c["website_url"] = PUBLIC
    c["city_en"] = "Sidi Abdel Rahman"

    rpc = OdooRPC(PROD_URL, PROD_DB, PROD_USER, PROD_PASS, timeout=600)
    rpc.authenticate()
    print("Authenticated to Production", PROD_DB, PROD_URL)

    websites = rpc.search_read(
        "website", [], ["id", "name", "domain"], limit=10
    )
    print("Websites:", websites)
    assert any(w["id"] == WEBSITE_ID for w in websites), websites

    fb_before = snapshot_fb(rpc)
    print("FB before:", fb_before)

    print("Deploying website content (website_id=1)...")
    deploy_to(rpc, c, "PRODUCTION", install_theme=False, website_id=WEBSITE_ID)
    rpc.write(
        "res.company",
        [1],
        {
            "name": "pet.spot",
            "phone": c["phone_e164"],
            "email": c["email"],
            "website": PUBLIC,
            "street": c["address_en"],
            "city": "Sidi Abdel Rahman",
            "social_facebook": c["facebook"],
            "social_instagram": c["instagram"],
        },
    )
    rpc.write(
        "website",
        [WEBSITE_ID],
        {
            "social_facebook": c["facebook"],
            "social_instagram": c["instagram"],
        },
    )

    print("Fixing placeholder phones...")
    fix_placeholder_phones(rpc, c)

    print("Service pages...")
    pages = ensure_service_pages(rpc, c, WEBSITE_ID)

    print("Updating blog tags/articles CTAs (no social recreate)...")
    blog_meta = configure_blog(rpc, c)
    articles = create_draft_articles(rpc, c, blog_meta)
    patched_posts = patch_published_articles_content(rpc)

    print("Updating WhatsApp / mail direction templates...")
    wa_updated = update_whatsapp_templates(rpc)

    fb_after = snapshot_fb(rpc)
    # Guard: do not change FB schedule states
    by_id = {p["id"]: p for p in fb_after}
    assert by_id[1]["state"] == "draft" and not by_id[1].get("scheduled_date")
    assert by_id[2]["state"] == "scheduled" and by_id[2].get("scheduled_date")
    assert by_id[3]["state"] == "draft" and not by_id[3].get("scheduled_date")
    print("FB after (guard OK):", fb_after)

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": "petspot_location_prod_deploy",
        "target": {
            "url": PROD_URL,
            "db": PROD_DB,
            "public": PUBLIC,
            "website_id": WEBSITE_ID,
        },
        "canonical": {
            "name": "pet.spot",
            "lat": 30.9909056,
            "lng": 28.6842417,
            "maps": NEW_MAPS,
            "address_en": c["address_en"],
        },
        "pages": pages,
        "blog": blog_meta,
        "articles": articles,
        "blog_posts_patched": patched_posts,
        "whatsapp_templates_updated": wa_updated,
        "facebook_posts": {"before": fb_before, "after": fb_after},
        "untouched": [
            "GBP profiles",
            "Facebook scheduling (post #2 left scheduled; #1/#3 draft)",
            "External listings",
            "DNS / Cloudflare",
            "Ownership dispute public disclosure",
        ],
        "signage_gbp_blocker": (
            "Permanent sign reads PET SPOT; profile name pet.spot — "
            "no verification submit until Sabry chooses A) add visible dot PET.SPOT "
            "or B) rename profile to match sign. Do not edit disputed legacy listing."
        ),
    }
    path = EVIDENCE / "petspot_location_prod_deploy.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n")
    print("Wrote", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
