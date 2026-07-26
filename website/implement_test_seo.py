#!/usr/bin/env python3
"""Test-only PetSpot SEO / blog / pages implementation.

Targets: http://127.0.0.1:8028 / pet_spot_elsahel_test / public https://test.drpaws.ai
Does NOT touch Production :8027, Cloudflare, external listings, or publish social posts.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOC = ROOT.parent / "docs" / "seo_ai_visibility" / "2026-07-24_read_only_audit"
EVIDENCE = DOC / "test_uat_evidence"
sys.path.insert(0, str(ROOT))

from deploy import deploy_footer, deploy_to, load_env_file, load_logo_b64  # noqa: E402
from odoo_rpc import OdooRPC  # noqa: E402
from page_templates import SERVICE_PAGES, build_service_page_arch  # noqa: E402
from site_config import load_config  # noqa: E402

TEST_URL = os.environ.get("TEST_ODOO_URL", "http://127.0.0.1:8028")
TEST_DB = os.environ.get("TEST_ODOO_DB", "pet_spot_elsahel_test")
TEST_USER = os.environ.get("TEST_ODOO_USERNAME", "admin")
TEST_PASS = os.environ.get("TEST_ODOO_PASSWORD", "admin")
PUBLIC_TEST = "https://test.drpaws.ai"


ARTICLES = [
    {
        "slug": "pet-emergency-north-coast",
        "name": "What to do during a pet emergency in North Coast",
        "name_ar": "ماذا تفعل عند طوارئ حيوانك الأليف في الساحل الشمالي",
        "subtitle": "Practical first steps — call the clinic; this is not a remote diagnosis.",
        "tags": ["Emergency Care", "North Coast Pet Care"],
        "body": """
<p><strong>EN:</strong> If your pet collapses, struggles to breathe, seizes, bleeds heavily, or may have eaten something toxic, contact PetSpot El Sahel immediately: clinic <a href="tel:+201280833332">01280833332</a>, WhatsApp <a href="https://wa.me/201000059085">01000059085</a>. Keep your pet calm, avoid forcing food or water, and note symptoms and timing. Online articles cannot examine your animal.</p>
<p dir="rtl"><strong>عربي:</strong> إذا انهار أليفك أو صعب عليه التنفس أو تشنّج أو نزف بشدة أو ابتلع مادة ضارة، تواصل فورًا مع بيت سبوت الساحل: عيادة 01280833332 · واتساب 01000059085. هدّئ أليفك ولا تجبره على الأكل أو الشرب وسجّل الأعراض والوقت. المقالات لا تغني عن الفحص.</p>
<p><em>Medical disclaimer:</em> Content is educational for pet owners. It does not diagnose or prescribe. Seek urgent in-person care when warning signs appear.</p>
""",
    },
    {
        "slug": "heatstroke-dogs-cats-sahel-summer",
        "name": "Heatstroke signs in dogs and cats during Sahel summer",
        "name_ar": "علامات ضربة الحر لدى الكلاب والقطط في صيف الساحل",
        "subtitle": "Shade, water, and early clinic contact in North Coast heat.",
        "tags": ["Travel and Summer Safety", "Dogs", "Cats"],
        "body": """
<p><strong>EN:</strong> Hot cars, midday walks and limited shade raise heat risk. Watch for excessive panting, drooling, weakness, bright gums or vomiting. Move to shade, offer cool (not ice-cold) water if the pet can drink, and contact the clinic. Do not invent home treatments from social media.</p>
<p dir="rtl"><strong>عربي:</strong> السيارات الحارة والمشي وقت الظهيرة وقلة الظل ترفع خطر ضربات الحر. راقبوا اللهاث الشديد والضعف واللعاب وقيء. انقلوا أليفك للظل وقدّموا ماءً فاترًا إن أمكن، وتواصلوا مع العيادة. لا تعتمدوا وصفات غير موثوقة.</p>
<p><em>Medical disclaimer:</em> Educational only — not a diagnosis.</p>
""",
    },
    {
        "slug": "travel-safely-pet-north-coast",
        "name": "How to travel safely with your pet to North Coast",
        "name_ar": "كيف تسافر بأمان مع أليفك إلى الساحل الشمالي",
        "subtitle": "Car breaks, hydration, and clinic location near Amwaj Gate 1.",
        "tags": ["Travel and Summer Safety", "North Coast Pet Care"],
        "body": """
<p><strong>EN:</strong> Plan rest stops, secure crates, never leave pets in parked cars, and pack meds/records. Save pet.spot directions: Main Road beside Amwaj Gate 1, Sidi Abdel Rahman. Book vaccines or checkups before peak travel weeks when possible.</p>
<p dir="rtl"><strong>عربي:</strong> خططوا محطات راحة وثبّتوا صندوق النقل ولا تتركوا الحيوان في سيارة متوقفة واحملوا الأدوية والسجلات. احفظوا موقع pet.spot: الطريق الرئيسي بجوار بوابة أمواج 1، سيدي عبد الرحمن. احجزوا التطعيمات أو الكشف قبل ذروة السفر إن أمكن.</p>
<p><em>Medical disclaimer:</em> Educational travel tips only.</p>
""",
    },
    {
        "slug": "24-7-veterinarian-near-amwaj",
        "name": "Finding a 24/7 veterinarian near Amwaj",
        "name_ar": "كيف تجد طبيبًا بيطريًا على مدار الساعة قرب أمواج",
        "subtitle": "pet.spot is open 24/7 beside Amwaj Gate 1 on the Main Road, Sidi Abdel Rahman.",
        "tags": ["Emergency Care", "North Coast Pet Care"],
        "body": """
<p><strong>EN:</strong> pet.spot operates 24/7 near Amwaj Gate 1 on the Main Road. Primary phone 01280833332 · call center 01201568888 · WhatsApp 01000059085. Use the official Maps directions button — avoid outdated kilometre listings from directories.</p>
<p dir="rtl"><strong>عربي:</strong> pet.spot يعمل 24/7 قرب بوابة أمواج 1 على الطريق الرئيسي. هاتف العيادة 01280833332 · مركز الاتصال 01201568888 · واتساب 01000059085. استخدموا اتجاهات خرائط جوجل الرسمية وتجنبوا أرقام الكيلومترات القديمة في الأدلة.</p>
<p><em>Medical disclaimer:</em> Confirm care needs by phone for urgent cases.</p>
""",
    },
    {
        "slug": "vaccination-before-travelling",
        "name": "Pet vaccination preparation before travelling",
        "name_ar": "التجهيز لتطعيم أليفك قبل السفر",
        "subtitle": "Bring records; ask the clinic — no remote vaccine prescriptions here.",
        "tags": ["Vaccinations", "Travel and Summer Safety"],
        "body": """
<p><strong>EN:</strong> Share your pet's age, species and last vaccine dates with the clinic. Core schedules vary; we will not list unverified products online. Book ahead of busy summer weekends near Amwaj.</p>
<p dir="rtl"><strong>عربي:</strong> أخبروا العيادة بعمر أليفك ونوعه وآخر تطعيم. الجداول تختلف ولن نعرض منتجات غير موثقة هنا. احجزوا قبل عطل الصيف المزدحمة قرب أمواج.</p>
<p><em>Medical disclaimer:</em> Vaccination plans require clinical assessment.</p>
""",
    },
    {
        "slug": "digestive-problems-summer-trips",
        "name": "Common digestive problems during summer trips",
        "name_ar": "اضطرابات الهضم الشائعة أثناء رحلات الصيف",
        "subtitle": "Diet changes, heat and when to call the vet.",
        "tags": ["Travel and Summer Safety", "Dogs", "Cats"],
        "body": """
<p><strong>EN:</strong> Sudden food changes, scavenging and heat stress can upset digestion. Mild soft stool may settle with rest and usual diet; persistent vomiting, blood, lethargy or refusal to drink needs clinic contact. Do not give human painkillers.</p>
<p dir="rtl"><strong>عربي:</strong> تغيير الطعام فجأة والالتقاط من الأرض والحر قد تسبب اضطرابًا هضميًا. الليونة الخفيفة قد تتحسن بالراحة والغذاء المعتاد؛ القيء المستمر أو الدم أو الخمول أو رفض الشرب يستدعي التواصل مع العيادة. لا تعطوا مسكنات بشرية.</p>
<p><em>Medical disclaimer:</em> Not a diagnosis — contact the clinic when worried.</p>
""",
    },
    {
        "slug": "clinic-visit-vs-home-visit",
        "name": "When a pet needs a clinic visit versus a home visit",
        "name_ar": "متى تحتاج زيارة العيادة ومتى تناسب الزيارة المنزلية",
        "subtitle": "Stable cases vs emergencies on the North Coast.",
        "tags": ["North Coast Pet Care", "Emergency Care"],
        "body": """
<p><strong>EN:</strong> Home visits can suit stable wellness checks when travel is hard. Critical breathing issues, trauma and severe dehydration usually need the clinic. Message WhatsApp with a short description so staff can advise.</p>
<p dir="rtl"><strong>عربي:</strong> الزيارة المنزلية قد تناسب الفحوصات المستقرة عندما يصعب النقل. مشاكل التنفس الحرجة والإصابات والجفاف الشديد غالبًا تحتاج العيادة. راسلوا واتساب بوصف مختصر ليساعدكم الفريق.</p>
<p><em>Medical disclaimer:</em> Staff advise based on what you report; examination decides care.</p>
""",
    },
    {
        "slug": "grooming-parasite-prevention-summer",
        "name": "Pet grooming and parasite prevention during summer",
        "name_ar": "الجروومينج والوقاية من الطفيليات في الصيف",
        "subtitle": "Coat care and ask the clinic about prevention — no unverified products listed.",
        "tags": ["Travel and Summer Safety", "Dogs", "Cats"],
        "body": """
<p><strong>EN:</strong> Regular grooming helps comfort in heat. Parasite prevention should match your pet's weight and risk — ask PetSpot which products suit your animal. Combine grooming/boarding bookings via WhatsApp when useful.</p>
<p dir="rtl"><strong>عربي:</strong> الجرومينج المنتظم يريح أليفك في الحر. الوقاية من الطفيليات يجب أن تناسب الوزن والمخاطر — اسألوا بيت سبوت عن المنتج المناسب. يمكن الجمع بين الجرومينج والبوردينج عبر واتساب.</p>
<p><em>Medical disclaimer:</em> Product choice requires clinic guidance.</p>
""",
    },
]


def client() -> OdooRPC:
    return OdooRPC(TEST_URL, TEST_DB, TEST_USER, TEST_PASS, timeout=300)


def fix_placeholder_phones(rpc: OdooRPC, c: dict) -> None:
    """Replace Odoo demo tel:+1 555-555-5556 in website views."""
    views = rpc.search_read(
        "ir.ui.view",
        [("arch_db", "ilike", "555-555")],
        ["id", "name", "key", "arch_db"],
        limit=50,
    )
    phone = c["phone"]
    tel = c["phone_tel"]
    for v in views:
        arch = v.get("arch_db") or ""
        if "555-555" not in arch:
            continue
        new = arch.replace("+1 555-555-5556", tel.replace("tel:", "") if tel.startswith("tel:") else tel)
        new = new.replace("tel:+1 555-555-5556", f"tel:{tel}")
        new = new.replace("+1 555-555-5556", phone)
        new = new.replace("555-555-5556", phone)
        if new != arch:
            rpc.write("ir.ui.view", [v["id"]], {"arch_db": new})
            print(f"  Fixed 555 placeholder in view {v['id']} {v.get('key')}")


def ensure_service_pages(rpc: OdooRPC, c: dict, website_id: int) -> list[dict]:
    created = []
    for page in SERVICE_PAGES:
        arch = build_service_page_arch(c, page)
        existing = rpc.search_read(
            "website.page",
            [("url", "=", page["url"]), ("website_id", "=", website_id)],
            ["id", "view_id"],
            limit=1,
        )
        if existing:
            view_id = existing[0]["view_id"][0] if isinstance(existing[0]["view_id"], list) else existing[0]["view_id"]
            rpc.write("ir.ui.view", [view_id], {"arch_db": arch})
            rpc.write(
                "website.page",
                [existing[0]["id"]],
                {
                    "is_published": True,
                    "website_indexed": True,
                    "name": page["name"],
                    "website_meta_title": page["title"],
                    "website_meta_description": page["meta"],
                },
            )
            print(f"  Updated page {page['url']}")
            created.append({"url": page["url"], "id": existing[0]["id"], "action": "updated"})
        else:
            view_id = rpc.create(
                "ir.ui.view",
                {
                    "name": page["name"],
                    "type": "qweb",
                    "key": f"website.petspot{page['url'].replace('/', '_').replace('-', '_')}",
                    "arch_db": arch,
                    "website_id": website_id,
                },
            )
            page_id = rpc.create(
                "website.page",
                {
                    "name": page["name"],
                    "url": page["url"],
                    "view_id": view_id,
                    "website_id": website_id,
                    "is_published": True,
                    "website_indexed": True,
                    "website_meta_title": page["title"],
                    "website_meta_description": page["meta"],
                },
            )
            print(f"  Created page {page['url']} id={page_id}")
            created.append({"url": page["url"], "id": page_id, "action": "created"})
    return created


def install_blog(rpc: OdooRPC) -> None:
    mods = rpc.search_read("ir.module.module", [("name", "=", "website_blog")], ["id", "state"])
    if not mods:
        raise RuntimeError("website_blog module not found in addons")
    if mods[0]["state"] != "installed":
        print("Installing website_blog (may take a while)...")
        rpc.execute("ir.module.module", "button_immediate_install", [mods[0]["id"]])
        # reconnect after install may reset — re-auth
        time.sleep(2)
        rpc.authenticate()
        print("  website_blog installed")
    else:
        print("  website_blog already installed")


def configure_blog(rpc: OdooRPC, c: dict) -> dict:
    blogs = rpc.search_read("blog.blog", [("name", "ilike", "PetSpot")], ["id", "name"], limit=5)
    blog_vals = {
        "name": "PetSpot Pet Care Guide",
        "subtitle": "دليل PetSpot لرعاية الحيوانات",
    }
    if blogs:
        blog_id = blogs[0]["id"]
        rpc.write("blog.blog", [blog_id], blog_vals)
    else:
        blog_id = rpc.create("blog.blog", blog_vals)
    print(f"  Blog id={blog_id}")

    tag_names = [
        ("Emergency Care", "طوارئ"),
        ("North Coast Pet Care", "رعاية الحيوانات في الساحل"),
        ("Dogs", "كلاب"),
        ("Cats", "قطط"),
        ("Vaccinations", "تطعيمات"),
        ("Travel and Summer Safety", "السفر والسلامة في الصيف"),
    ]
    tag_ids = {}
    for en, ar in tag_names:
        existing = rpc.search_read(
            "blog.tag",
            ["|", ("name", "=", en), ("name", "ilike", en)],
            ["id", "name"],
            limit=1,
        )
        if existing:
            tag_ids[en] = existing[0]["id"]
        else:
            tag_ids[en] = rpc.create("blog.tag", {"name": f"{en} / {ar}"})
        print(f"  Tag {en} -> {tag_ids[en]}")
    return {"blog_id": blog_id, "tags": tag_ids}


def create_draft_articles(rpc: OdooRPC, c: dict, blog_meta: dict) -> list[dict]:
    out = []
    blog_id = blog_meta["blog_id"]
    tags = blog_meta["tags"]
    for art in ARTICLES:
        existing = rpc.search_read(
            "blog.post",
            [("blog_id", "=", blog_id), ("name", "=", art["name"])],
            ["id", "website_url", "is_published"],
            limit=1,
        )
        tag_link = [(6, 0, [tags[t] for t in art["tags"] if t in tags])]
        content = (
            f"<h2 dir=\"rtl\">{art['name_ar']}</h2>"
            f"<p class=\"lead\">{art['subtitle']}</p>"
            f"{art['body']}"
            f"<p><a href=\"{c['whatsapp_url']}\">WhatsApp 01000059085</a> · "
            f"<a href=\"tel:{c['phone_tel']}\">Clinic {c['phone']}</a> · "
            f"<a href=\"{c['maps_url']}\">Directions</a></p>"
        )
        vals = {
            "name": art["name"],
            "blog_id": blog_id,
            "content": content,
            "teaser_manual": True,
            "teaser": art["subtitle"],
            "tag_ids": tag_link,
            "is_published": False,
            "website_meta_title": f"{art['name']} | PetSpot El Sahel",
            "website_meta_description": art["subtitle"][:160],
        }
        # website_slug if field exists
        fields = rpc.execute("blog.post", "fields_get", [], attributes=["type"])
        if "website_slug" in fields:
            vals["website_slug"] = art["slug"]
        if existing:
            rpc.write("blog.post", [existing[0]["id"]], vals)
            pid = existing[0]["id"]
            action = "updated_draft"
        else:
            pid = rpc.create("blog.post", vals)
            action = "created_draft"
        row = rpc.search_read("blog.post", [("id", "=", pid)], ["website_url", "is_published"], limit=1)
        out.append({"id": pid, "name": art["name"], "action": action, "published": row[0]["is_published"] if row else False, "url": row[0].get("website_url") if row else None})
        print(f"  Article draft {pid}: {art['name']}")
    return out


def snapshot_public(paths: list[str]) -> dict:
    import urllib.request

    results = {}
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    for path in paths:
        url = PUBLIC_TEST.rstrip("/") + path
        req = urllib.request.Request(url, headers={"User-Agent": "PetSpotTestUAT/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8", "replace")
                code = resp.status
        except Exception as exc:  # noqa: BLE001
            results[path] = {"error": str(exc)}
            continue
        checks = {
            "http": code,
            "has_555": "555-555-5556" in html,
            "has_primary": "01280833332" in html or "012 80833332" in html or "201280833332" in html,
            "has_wa": "201000059085" in html or "wa.me/201000059085" in html,
            "has_amwaj2": "Amwaj 2" in html or "أمواج 2" in html,
            "has_amwaj_gate_1": "Amwaj Gate 1" in html or "بوابة أمواج 1" in html,
            "has_new_coords": "30.9909056" in html and "28.6842417" in html,
            "has_old_maps_shortlink": "AaHup6NEFodZEs7S7" in html,
            "has_move_language": any(x in html for x in ("We have moved", "انتقلنا", "previous location", "موقعنا السابق", "Pet Spot Clinic", "/g/11w2cv6pz0")),
            "has_petspot_brand": "pet.spot" in html or "Pet.spot" in html,
            "has_jsonld": "application/ld+json" in html,
            "has_24_7": "24" in html and ("7" in html or "ساعة" in html),
        }
        fname = "page" + path.replace("/", "_").rstrip("_") + ".html"
        if path == "/":
            fname = "page_home.html"
        (EVIDENCE / fname).write_text(html[:200000], encoding="utf-8")
        results[path] = checks
    return results


def main() -> int:
    load_env_file(ROOT / ".env")
    # Force public URL for schema on Test pages (still Test host for browsing)
    os.environ["WEBSITE_URL"] = PUBLIC_TEST
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

    c = load_config()
    c["website_url"] = PUBLIC_TEST
    rpc = client()
    rpc.authenticate()
    print("Authenticated to Test")

    # Align company city with El Alamein
    deploy_to(rpc, c, "TEST", install_theme=False)
    # Patch city after deploy_to (deploy sets Sidi Abdel Rahman)
    rpc.write(
        "res.company",
        [1],
        {
            "name": c["company_name"],
            "phone": c["phone_e164"],
            "email": c["email"],
            "website": PUBLIC_TEST,
            "street": c["address_en"],
            "city": "Sidi Abdel Rahman",
            "social_facebook": c["facebook"],
            "social_instagram": c["instagram"],
        },
    )
    websites = rpc.search_read("website", [], ["id"], limit=1)
    website_id = websites[0]["id"]
    rpc.write(
        "website",
        [website_id],
        {
            "name": c["company_name"],
            "domain": "https://test.drpaws.ai",
            "social_facebook": c["facebook"],
            "social_instagram": c["instagram"],
        },
    )

    print("Fixing placeholder phones...")
    fix_placeholder_phones(rpc, c)

    print("Service pages...")
    pages = ensure_service_pages(rpc, c, website_id)

    print("Blog...")
    install_blog(rpc)
    blog_meta = configure_blog(rpc, c)
    articles = create_draft_articles(rpc, c, blog_meta)

    print("Public snapshots...")
    paths = ["/"] + [p["url"] for p in SERVICE_PAGES] + ["/contactus", "/blog", "/robots.txt", "/sitemap.xml"]
    snaps = snapshot_public(paths)

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "target": {"url": TEST_URL, "db": TEST_DB, "public": PUBLIC_TEST},
        "canonical": {
            "name": c["company_name"],
            "phone": c["phone_e164"],
            "call_center": c["call_center_e164"],
            "whatsapp": c["whatsapp"],
            "address_en": c["address_en"],
            "address_ar": c["address_ar"],
            "lat": c["latitude"],
            "lng": c["longitude"],
            "maps": c["maps_url"],
            "kg": c.get("kg_id"),
        },
        "pages": pages,
        "blog": blog_meta,
        "articles": articles,
        "snapshots": snaps,
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "implementation_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("Wrote", EVIDENCE / "implementation_report.json")
    # Fail summary
    bad = []
    home = snaps.get("/") or {}
    if home.get("has_555"):
        bad.append("homepage still has 555 placeholder")
    if home.get("has_amwaj2") or home.get("has_old_maps_shortlink") or home.get("has_move_language"):
        bad.append("customer page has Amwaj 2 / old Maps / move language / disputed listing")
    if not home.get("has_petspot_brand"):
        bad.append("homepage missing pet.spot brand")
    if not home.get("has_amwaj_gate_1"):
        bad.append("homepage missing Amwaj Gate 1 landmark")
    if not home.get("has_new_coords"):
        bad.append("homepage JSON-LD / content missing new coordinates")
    if not home.get("has_jsonld"):
        bad.append("homepage missing JSON-LD")
    if not home.get("has_wa"):
        bad.append("homepage missing WhatsApp 01000059085")
    print("UAT flags:", bad or ["OK"])
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
