#!/usr/bin/env python3
"""Controlled Production deploy for PetSpot SEO (Test-validated baseline).

Targets: http://127.0.0.1:8027 / pet_spot_elsahel / https://drpaws.ai
Does NOT: edit GBP/external listings, DNS/Cloudflare, publish all articles,
schedule Facebook posts, create Facebook accounts, or touch shop KG /g/11w2b6j71t.
"""
from __future__ import annotations

import json
import os
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
    install_blog,
)
from odoo_rpc import OdooRPC  # noqa: E402
from page_templates import SERVICE_PAGES  # noqa: E402
from site_config import load_config  # noqa: E402

PROD_URL = os.environ.get("PROD_ODOO_URL", "http://127.0.0.1:8027")
PROD_DB = os.environ.get("PROD_ODOO_DB", "pet_spot_elsahel")
PROD_USER = os.environ.get("PROD_ODOO_USERNAME", "admin")
PROD_PASS = os.environ.get("PROD_ODOO_PASSWORD", "admin")
PUBLIC = "https://drpaws.ai"
WEBSITE_ID = 1  # PetSpot El Sahel only — not sabry resume site
FB_ACCOUNT_ID = 16

# First three FB posts (Week 1) — drafts only; schedule after Sabry approval
SOCIAL_POSTS = [
    {
        "week": 1,
        "key": "emergency",
        "proposed_schedule": "2026-08-03 10:00:00",  # Africa/Cairo planning
        "title": "Emergency readiness — North Coast",
        "article_slug_hint": "pet-emergency-north-coast",
        "message": (
            "Pet emergency on the North Coast? Stay calm: secure your pet, note symptoms, call PetSpot. "
            "24/7 clinic near Amwaj 2.\n"
            "Call 01280833332 · WhatsApp 01000059085\n"
            "Directions: https://maps.app.goo.gl/AaHup6NEFodZEs7S7\n"
            "{utm_url}\n\n"
            "طوارئ حيوانك الأليف على الساحل؟ حافظ على هدوئك، راقب الأعراض، واتصل ببيت سبوت. "
            "عيادة 24/7 أمام أمواج 2. 01280833332 · واتساب 01000059085"
        ),
    },
    {
        "week": 1,
        "key": "heatstroke",
        "proposed_schedule": "2026-08-05 10:00:00",
        "title": "Heatstroke signs — Sahel summer",
        "article_slug_hint": "heatstroke-dogs-cats-sahel-summer",
        "message": (
            "Sahel summer tip: heavy panting, weakness, bright red gums — possible heatstroke. "
            "Cool gradually and contact a vet urgently.\n"
            "PetSpot 24/7: 01280833332 / WA 01000059085\n"
            "{utm_url}\n\n"
            "صيف الساحل: لهث شديد، ضعف، لثة حمراء — قد تكون ضربة شمس. "
            "برّد تدريجياً واتصل بالعيادة فوراً."
        ),
    },
    {
        "week": 1,
        "key": "directions",
        "proposed_schedule": "2026-08-07 10:00:00",
        "title": "Directions — Amwaj 2",
        "article_slug_hint": "pet-emergency-north-coast",
        "message": (
            "Find us: North Coast, beside Wahat Khattab, in front of Amwaj 2, El Alamein.\n"
            "Official Maps: https://maps.app.goo.gl/AaHup6NEFodZEs7S7\n"
            "Clinic 01280833332 · WhatsApp 01000059085\n"
            "{utm_url}\n\n"
            "موقعنا: الساحل الشمالي، الطريق الرئيسي بجوار بوابة أمواج 1، مقابل موقع بيت سبوت السابق، العلمين."
        ),
    },
]

# Remaining nine calendar drafts (connected to #16, unpublished schedule)
SOCIAL_REMAINING = [
    (2, "2026-08-10 10:00:00", "Travel safely with pets to North Coast",
     "Travelling with your pet to the North Coast? Plan water stops, shade, and a vet contact before you leave. "
     "PetSpot El Sahel is open 24/7 near Amwaj 2. Call 01280833332 · WA 01000059085\n\n"
     "مسافر بحيوانك للساحل؟ خطط لتوقفات ماء وظل ورقم بيطري. بيت سبوت 24/7 أمام أمواج 2."),
    (2, "2026-08-12 10:00:00", "Never leave pets in hot cars",
     "Hot car + pets = emergency risk. Never leave pets in parked cars on the Coast. "
     "WhatsApp PetSpot 01000059085\n\nلا تترك حيوانك في السيارة المتوقفة. واتساب 01000059085"),
    (2, "2026-08-14 10:00:00", "Water + shade reminder",
     "Shade and water first on Sahel afternoons. Need a 24/7 vet near Amwaj 2? PetSpot El Sahel — 01280833332.\n\n"
     "ظل وماء أولاً في ظهيرة الساحل. عيادة 24/7 أمام أمواج 2."),
    (3, "2026-08-17 10:00:00", "Vaccination prep before Coast travel",
     "Before a Coast trip: review vaccines and parasite prevention with your vet. "
     "Book via WhatsApp 01000059085 or call 01280833332.\n\nقبل رحلة الساحل: راجع التطعيمات. واتساب أو اتصال."),
    (3, "2026-08-19 10:00:00", "Digestive issues on summer trips",
     "New food + travel stress can upset pet digestion. Pack familiar food; know your nearest 24/7 clinic near Amwaj.\n\n"
     "طعام جديد + سفر قد يسبب اضطراب هضم. اعرف أقرب عيادة 24/7."),
    (3, "2026-08-21 10:00:00", "Phone hierarchy reminder",
     "Booking: call-center 01201568888 · Clinic 01280833332 · WhatsApp 01000059085. Same NAP everywhere.\n\n"
     "للحجز: 01201568888 · العيادة 01280833332 · واتساب 01000059085"),
    (4, "2026-08-24 10:00:00", "Clinic visit vs home visit",
     "Emergencies and diagnostics → clinic. Stable follow-ups may suit home visits. Ask PetSpot which is safer.\n\n"
     "الطوارئ → العيادة. المتابعة المستقرة قد تناسب الزيارة المنزلية."),
    (4, "2026-08-26 10:00:00", "Grooming and parasite prevention",
     "Summer parasites love the Coast. Grooming + prevention helps. Near Amwaj 2 — call 01280833332.\n\n"
     "طفيليات الصيف. العناية مهمة. أمام أمواج 2."),
    (4, "2026-08-28 10:00:00", "Recap — PetSpot El Sahel NAP",
     "PetSpot El Sahel Veterinary Clinic · 24/7 · Amwaj 2 · "
     "Maps https://maps.app.goo.gl/AaHup6NEFodZEs7S7 · "
     "FB https://www.facebook.com/animalcarecenterpetspots\n\n"
     "عيادة بيت سبوت الساحل · 24/7 · أمواج 2"),
]


def apply_canonical_env() -> None:
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
    os.environ["CLINIC_MAP_URL"] = "https://www.google.com/maps?q=30.9909056,28.6842417"
    os.environ["CLINIC_FACEBOOK"] = "https://www.facebook.com/animalcarecenterpetspots"
    os.environ["CLINIC_INSTAGRAM"] = "https://www.instagram.com/pet_spot_clinic/"
    os.environ["CLINIC_LAT"] = "30.9909056"
    os.environ["CLINIC_LNG"] = "28.6842417"


def utm_url(base: str, campaign: str, content: str) -> str:
    sep = "&" if "?" in base else "?"
    return (
        f"{base}{sep}utm_source=facebook&utm_medium=social"
        f"&utm_campaign={campaign}&utm_content={content}"
    )


def ensure_fb_account(rpc: OdooRPC) -> dict:
    rows = rpc.search_read(
        "social.account",
        [("id", "=", FB_ACCOUNT_ID)],
        ["id", "name", "social_account_handle", "media_type", "is_media_disconnected", "active"],
        limit=1,
    )
    if not rows:
        raise RuntimeError("Production social.account #16 missing — abort")
    acc = rows[0]
    if acc.get("social_account_handle") != "animalcarecenterpetspots":
        raise RuntimeError(f"Account #16 handle mismatch: {acc}")
    if acc.get("media_type") != "facebook":
        raise RuntimeError(f"Account #16 is not facebook: {acc}")
    if acc.get("is_media_disconnected"):
        raise RuntimeError("Account #16 disconnected — abort")
    # Guard: do not create any facebook account
    fb_count = rpc.search_read(
        "social.account",
        [("media_type", "=", "facebook")],
        ["id", "social_account_handle"],
    )
    if len(fb_count) != 1 or fb_count[0]["id"] != FB_ACCOUNT_ID:
        raise RuntimeError(f"Unexpected facebook accounts: {fb_count}")
    return acc


def create_social_drafts(rpc: OdooRPC, article_urls: dict[str, str]) -> list[dict]:
    """Create/update drafts linked to account #16. Never schedule (state=draft, no scheduled_date)."""
    out = []
    # Remove prior SEO calendar drafts for idempotency
    old = rpc.search_read(
        "social.post",
        [("message", "ilike", "[PetSpot SEO calendar draft]")],
        ["id"],
        limit=200,
    )
    if old:
        rpc.execute("social.post", "unlink", [[o["id"] for o in old]])
        print(f"  Removed {len(old)} prior SEO social drafts")

    def _create(title: str, message: str, week: int, proposed: str, key: str) -> dict:
        msg = f"[PetSpot SEO calendar draft][W{week}] {title}\n\n{message}"
        pid = rpc.create(
            "social.post",
            {
                "message": msg,
                "facebook_message": msg,
                "state": "draft",
                "post_method": "now",  # draft only; not scheduled
                "account_ids": [(6, 0, [FB_ACCOUNT_ID])],
            },
        )
        # Force draft again (defaults may expand accounts)
        rpc.write(
            "social.post",
            [pid],
            {
                "state": "draft",
                "scheduled_date": False,
                "account_ids": [(6, 0, [FB_ACCOUNT_ID])],
            },
        )
        row = rpc.search_read(
            "social.post",
            [("id", "=", pid)],
            ["id", "state", "scheduled_date", "account_ids"],
            limit=1,
        )[0]
        assert row["state"] == "draft", row
        assert not row.get("scheduled_date"), row
        return {
            "id": pid,
            "week": week,
            "key": key,
            "title": title,
            "proposed_schedule_cairo": proposed,
            "state": "draft",
            "scheduled": False,
            "account_ids": row.get("account_ids"),
        }

    for spec in SOCIAL_POSTS:
        slug = spec["article_slug_hint"]
        base = article_urls.get(slug) or f"{PUBLIC}/blog"
        tracked = utm_url(base, "petspot_seo_w1", spec["key"])
        message = spec["message"].format(utm_url=tracked)
        out.append(
            _create(spec["title"], message, spec["week"], spec["proposed_schedule"], spec["key"])
        )
        print(f"  Priority draft {out[-1]['id']}: {spec['title']}")

    for week, proposed, title, message in SOCIAL_REMAINING:
        out.append(_create(title, message, week, proposed, f"w{week}"))
        print(f"  Remaining draft {out[-1]['id']}: {title}")
    return out


def main() -> int:
    load_env_file(ROOT / ".env")
    apply_canonical_env()
    EVIDENCE.mkdir(parents=True, exist_ok=True)

    c = load_config()
    c["website_url"] = PUBLIC
    c["website_domain"] = PUBLIC
    c["city_en"] = "El Alamein"

    rpc = OdooRPC(PROD_URL, PROD_DB, PROD_USER, PROD_PASS, timeout=600)
    rpc.authenticate()
    print("Authenticated to Production")

    acc = ensure_fb_account(rpc)
    print("Social #16 OK:", {k: acc[k] for k in acc if "token" not in k})

    # Phase 2 core website NAP deploy (website 1 only)
    deploy_to(rpc, c, "PRODUCTION", install_theme=False, website_id=WEBSITE_ID)
    rpc.write(
        "res.company",
        [1],
        {
            "name": c["company_name"],
            "phone": c["phone_e164"],
            "email": c["email"],
            "website": PUBLIC,
            "street": c["address_en"],
            "city": "El Alamein",
            "social_facebook": c["facebook"],
            "social_instagram": c["instagram"],
        },
    )

    print("Fixing placeholder phones...")
    fix_placeholder_phones(rpc, c)

    print("Service pages...")
    pages = ensure_service_pages(rpc, c, WEBSITE_ID)

    print("Installing website_blog...")
    install_blog(rpc)
    time.sleep(1)
    rpc.authenticate()
    blog_meta = configure_blog(rpc, c)
    articles = create_draft_articles(rpc, c, blog_meta)

    # Map slug → public URL for UTM (drafts may still have website_url)
    article_urls = {}
    for art, row in zip(ARTICLES, articles):
        url = row.get("url") or f"{PUBLIC}/blog"
        if url.startswith("/"):
            url = PUBLIC.rstrip("/") + url
        article_urls[art["slug"]] = url

    print("Social drafts on account #16 (NOT scheduled)...")
    social = create_social_drafts(rpc, article_urls)

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": "2_deploy",
        "target": {"url": PROD_URL, "db": PROD_DB, "public": PUBLIC, "website_id": WEBSITE_ID},
        "social_account": acc,
        "pages": pages,
        "blog": blog_meta,
        "articles": articles,
        "social_drafts": social,
        "notes": [
            "Articles remain unpublished",
            "Social posts state=draft; scheduled_date empty pending Sabry approval of first 3",
            "No GBP/external/DNS/Cloudflare changes",
            "Shop KG /g/11w2b6j71t not used",
        ],
    }
    path = EVIDENCE / "deploy_report.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Wrote", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
