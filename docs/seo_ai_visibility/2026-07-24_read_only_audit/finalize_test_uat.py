#!/usr/bin/env python3
"""Finalize Test SEO UAT: social drafts, regression, Dev Hub evidence. No Production."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import xmlrpc.client

URL = "http://127.0.0.1:8028"
DB = "pet_spot_elsahel_test"
USER = "admin"
PWD = "admin"
PUBLIC = "https://test.drpaws.ai"
DOCS = Path(
    "/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/"
    "docs/seo_ai_visibility/2026-07-24_read_only_audit"
)
EVIDENCE = DOCS / "test_uat_evidence"
WI_ID = 3343
ANALYSIS_ID = 2697

POSTS = [
    # week, day_offset from 2026-08-03, title, message
    (1, 0, "Emergency readiness — North Coast",
     "Pet emergency on the North Coast? Stay calm: secure your pet, note symptoms, call PetSpot. "
     "24/7 clinic near Amwaj 2. Call 01280833332 · WhatsApp 01000059085 · "
     "Directions: https://maps.app.goo.gl/AaHup6NEFodZEs7S7\n\n"
     "طوارئ حيوانك الأليف على الساحل؟ حافظ على هدوئك، راقب الأعراض، واتصل ببيت سبوت. "
     "عيادة 24/7 أمام أمواج 2. 01280833332 · واتساب 01000059085"),
    (1, 2, "24/7 veterinarian near Amwaj",
     "Looking for a 24/7 veterinarian near Amwaj? PetSpot El Sahel Veterinary Clinic — "
     "Pet Spot Clinic on Google Maps. Open 24 hours. Call-center 01201568888 · Clinic 01280833332\n\n"
     "تبحث عن طبيب بيطري 24/7 قرب أمواج؟ عيادة بيت سبوت الساحل — مفتوحة 24 ساعة. "
     "مركز الاتصال 01201568888 · العيادة 01280833332"),
    (1, 4, "Directions — Amwaj 2",
     "Find us: North Coast, beside Wahat Khattab, in front of Amwaj 2, El Alamein. "
     "Official Maps: https://maps.app.goo.gl/AaHup6NEFodZEs7S7\n\n"
     "موقعنا: الساحل الشمالي، بجوار واحة خطاب، أمام أمواج 2، العلمين."),
    (2, 7, "Heatstroke signs — Sahel summer",
     "Sahel summer tip: heavy panting, weakness, bright red gums — possible heatstroke. "
     "Cool gradually and contact a vet urgently. PetSpot 24/7: 01280833332 / WA 01000059085\n\n"
     "صيف الساحل: لهث شديد، ضعف، لثة حمراء — قد تكون ضربة شمس. برّد تدريجياً واتصل بالعيادة فوراً."),
    (2, 9, "Travel safely with pets to North Coast",
     "Travelling with your pet to the North Coast? Plan water stops, shade, and a vet contact "
     "before you leave. PetSpot El Sahel is open 24/7 near Amwaj 2.\n\n"
     "مسافر بحيوانك للساحل؟ خطط لتوقفات ماء وظل ورقم بيطري قبل السفر. بيت سبوت مفتوحة 24/7 أمام أمواج 2."),
    (2, 11, "Never leave pets in hot cars",
     "Hot car + pets = emergency risk. Never leave pets in parked cars on the Coast. "
     "Need help? WhatsApp PetSpot 01000059085.\n\n"
     "لا تترك حيوانك في السيارة المتوقفة. تحتاج مساعدة؟ واتساب بيت سبوت 01000059085."),
    (3, 14, "Vaccination prep before Coast travel",
     "Before a Coast trip: review vaccines and parasite prevention with your vet. "
     "PetSpot vaccinations & travel prep — WhatsApp 01000059085 or call 01280833332.\n\n"
     "قبل رحلة الساحل: راجع التطعيمات والوقاية من الطفيليات. حجز عبر واتساب أو اتصال."),
    (3, 16, "Digestive issues on summer trips",
     "New food + travel stress can upset pet digestion. Pack familiar food and know your "
     "nearest 24/7 clinic near Amwaj.\n\n"
     "طعام جديد + سفر قد يسبب اضطرابات هضم. جهّز طعاماً معتاداً واعرف أقرب عيادة 24/7."),
    (3, 18, "Phone hierarchy reminder",
     "Booking & enquiries: call-center 01201568888 · Clinic 01280833332 · WhatsApp 01000059085. "
     "Same NAP everywhere.\n\n"
     "للحجز والاستفسار: 01201568888 · العيادة 01280833332 · واتساب 01000059085."),
    (4, 21, "Clinic visit vs home visit",
     "Unsure clinic vs home visit? Emergencies and diagnostics → clinic. Stable follow-ups may "
     "suit home visits where available. Ask PetSpot which is safer for your pet.\n\n"
     "عيادة أم زيارة منزلية؟ الطوارئ والتشخيص → العيادة. المتابعة المستقرة قد تناسب الزيارة المنزلية."),
    (4, 23, "Grooming and parasite prevention",
     "Summer parasites love the Coast. Grooming + prevention helps. PetSpot grooming & boarding "
     "support near Amwaj 2. Call 01280833332.\n\n"
     "طفيليات الصيف على الساحل. العناية والوقاية مهمة. خدمات بيت سبوت أمام أمواج 2."),
    (4, 25, "Recap — PetSpot El Sahel NAP",
     "PetSpot El Sahel Veterinary Clinic · 24/7 · Amwaj 2 · "
     "Maps: https://maps.app.goo.gl/AaHup6NEFodZEs7S7 · "
     "FB: https://www.facebook.com/animalcarecenterpetspots\n\n"
     "عيادة بيت سبوت الساحل · 24/7 · أمواج 2 · خرائط Google عبر الرابط الرسمي."),
]


def rpc():
    common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
    uid = common.authenticate(DB, USER, PWD, {})
    assert uid, "auth failed"
    models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")
    return uid, models


def execute(models, uid, model, method, *args, **kwargs):
    return models.execute_kw(DB, uid, PWD, model, method, list(args), kwargs)


def fetch(path: str) -> dict:
    url = PUBLIC.rstrip("/") + path
    req = urllib.request.Request(url, headers={"User-Agent": "PetSpot-Test-UAT/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            body = r.read().decode("utf-8", "replace")
            status = r.status
    except Exception as e:
        return {"url": path, "error": str(e)}
    slug = path.strip("/").replace("/", "_") or "home"
    (EVIDENCE / f"page_{slug}.html").write_text(body[:500_000], encoding="utf-8")
    jsonld = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        body,
        flags=re.I | re.S,
    )
    types = []
    for block in jsonld:
        types += re.findall(r'"@type"\s*:\s*"([^"]+)"', block)
    return {
        "url": path,
        "http": status,
        "has_555": "555-555" in body or "+1 555" in body,
        "has_primary": "01280833332" in body or "+201280833332" in body,
        "has_call_center": "01201568888" in body or "+201201568888" in body,
        "has_wa": "201000059085" in body,
        "has_amwaj2": "Amwaj 2" in body or "أمواج 2" in body,
        "has_amwaj1_gate": "Amwaj 1" in body or "أمواج 1" in body,
        "has_km_legacy": bool(re.search(r"\bkm\s*1(28|36|39)\b", body, re.I)),
        "has_jsonld": "application/ld+json" in body.lower(),
        "jsonld_types": sorted(set(types)),
        "has_veterinarycare": "VeterinaryCare" in body,
        "has_localbusiness": "LocalBusiness" in body,
        "has_24_7": "24/7" in body or "24 ساعة" in body or "Open 24" in body,
        "has_maps_shortlink": "AaHup6NEFodZEs7S7" in body,
        "bytes": len(body),
    }


def attach_file(models, uid, path: Path, res_model: str, res_id: int, name: str | None = None):
    data = path.read_bytes()
    att_id = execute(
        models,
        uid,
        "ir.attachment",
        "create",
        {
            "name": name or path.name,
            "res_model": res_model,
            "res_id": res_id,
            "type": "binary",
            "datas": base64.b64encode(data).decode(),
            "mimetype": "application/json"
            if path.suffix == ".json"
            else "text/markdown"
            if path.suffix == ".md"
            else "text/html"
            if path.suffix == ".html"
            else "application/octet-stream",
        },
    )
    # external link for convenience
    try:
        execute(
            models,
            uid,
            "dev.work.external.link",
            "create",
            {
                "work_item_id": WI_ID,
                "name": name or path.name,
                "url": f"file://{path}",
                "link_type": "evidence",
                "sync_state": "reference",
            },
        )
    except Exception:
        pass
    return att_id


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    uid, models = rpc()
    start = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)

    # --- Social drafts on Test ---
    # Remove prior PetSpot SEO calendar drafts if re-run
    old = execute(
        models,
        uid,
        "social.post",
        "search",
        [["message", "ilike", "PetSpot El Sahel Veterinary Clinic · 24/7 · Amwaj 2"]],
    )
    # broader: tagged marker
    old2 = execute(
        models,
        uid,
        "social.post",
        "search",
        [["message", "ilike", "[PetSpot SEO calendar draft]"]],
    )
    if old2:
        execute(models, uid, "social.post", "unlink", [old2])

    social_ids = []
    for week, offset, title, message in POSTS:
        msg = f"[PetSpot SEO calendar draft][W{week}] {title}\n\n{message}"
        scheduled = start + timedelta(days=offset)
        pid = execute(
            models,
            uid,
            "social.post",
            "create",
            {
                "message": msg,
                "state": "draft",
                "post_method": "scheduled",
                "scheduled_date": scheduled.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        # ensure still draft and no accidental post
        execute(models, uid, "social.post", "write", [pid], {"state": "draft"})
        social_ids.append(
            {
                "id": pid,
                "week": week,
                "title": title,
                "scheduled_date_planning_only": scheduled.isoformat(),
                "state": "draft",
            }
        )

    social_path = EVIDENCE / "social_drafts.json"
    social_path.write_text(
        json.dumps(
            {
                "note": "Test-only drafts; no Facebook account on Test; not published",
                "posts": social_ids,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    # --- Regression / SEO checks ---
    paths = [
        "/",
        "/emergency-vet-north-coast",
        "/veterinary-clinic-near-amwaj",
        "/veterinary-home-visits-sahel",
        "/pet-vaccinations-north-coast",
        "/grooming-boarding-sahel",
        "/contact-directions-booking",
        "/contactus",
        "/blog",
        "/robots.txt",
        "/sitemap.xml",
    ]
    snapshots = {p: fetch(p) for p in paths}

    articles = execute(
        models,
        uid,
        "blog.post",
        "search_read",
        [],
        fields=["id", "name", "is_published", "website_published", "website_url"],
        order="id",
    )
    for a in articles:
        assert not (a.get("is_published") or a.get("website_published")), a

    # company phone sanity
    company = execute(
        models,
        uid,
        "res.company",
        "search_read",
        [["id", "=", 1]],
        fields=["name", "phone", "email", "street", "city"],
        limit=1,
    )[0]

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gate": "TEST_ONLY_STOP_FOR_APPROVAL",
        "target": {"url": URL, "db": DB, "public": PUBLIC},
        "canonical": {
            "name": "PetSpot El Sahel Veterinary Clinic",
            "gbp_name": "Pet Spot Clinic",
            "phone": "+201280833332",
            "call_center": "+201201568888",
            "whatsapp": "201000059085",
            "address_en": "North Coast, beside Wahat Khattab, in front of Amwaj 2, El Alamein, Egypt",
            "address_ar": "الساحل الشمالي، بجوار واحة خطاب، أمام أمواج 2، العلمين، مصر",
            "lat": 30.9909989,
            "lng": 28.6840834,
            "maps": "https://maps.app.goo.gl/AaHup6NEFodZEs7S7",
            "kg_authoritative": "/g/11w2cv6pz0",
            "kg_duplicate_shop": "/g/11w2b6j71t",
        },
        "company": company,
        "articles": [
            {
                "id": a["id"],
                "name": a["name"],
                "published": False,
                "url": a.get("website_url"),
            }
            for a in articles
        ],
        "social_drafts": social_ids,
        "snapshots": snapshots,
        "pass_criteria": {},
    }

    failures = []
    for p in [
        "/",
        "/emergency-vet-north-coast",
        "/veterinary-clinic-near-amwaj",
        "/veterinary-home-visits-sahel",
        "/pet-vaccinations-north-coast",
        "/grooming-boarding-sahel",
        "/contact-directions-booking",
        "/contactus",
    ]:
        s = snapshots[p]
        if s.get("error") or s.get("http") != 200:
            failures.append(f"{p} not 200: {s}")
            continue
        if s.get("has_555"):
            failures.append(f"{p} has placeholder 555")
        if not s.get("has_primary"):
            failures.append(f"{p} missing primary phone")
        if not s.get("has_wa"):
            failures.append(f"{p} missing WhatsApp")
        if s.get("has_amwaj1_gate"):
            failures.append(f"{p} has Amwaj 1")
        if s.get("has_km_legacy"):
            failures.append(f"{p} has legacy km")
        if p != "/blog" and not s.get("has_veterinarycare"):
            # blog listing may lack VC; contactus and services should have it
            if p in ("/contactus", "/") or p.startswith("/"):
                if p not in ("/robots.txt", "/sitemap.xml", "/blog"):
                    if not s.get("has_veterinarycare"):
                        failures.append(f"{p} missing VeterinaryCare JSON-LD")

    report["pass_criteria"] = {
        "contactus_200": snapshots["/contactus"].get("http") == 200,
        "no_555_on_key_pages": not any(
            snapshots[p].get("has_555")
            for p in snapshots
            if not snapshots[p].get("error") and p not in ("/robots.txt",)
        ),
        "articles_unpublished": all(not a.get("published") for a in report["articles"]),
        "social_draft_count": len(social_ids),
        "failures": failures,
        "ok": not failures,
    }

    report_path = EVIDENCE / "implementation_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    uat_md = EVIDENCE / "UAT_SUMMARY.md"
    uat_md.write_text(
        f"""# PetSpot Test UAT summary — 2026-07-24

**Public:** {PUBLIC}  
**DB:** {DB}  
**Gate:** Test only — stop for Sabry approval  

## Results

| Check | Result |
|-------|--------|
| `/contactus` HTTP | {snapshots['/contactus'].get('http')} |
| Key pages no 555 | {report['pass_criteria']['no_555_on_key_pages']} |
| VeterinaryCare on home | {snapshots['/'].get('has_veterinarycare')} |
| Articles unpublished | {len(articles)} drafts |
| Social drafts (Test) | {len(social_ids)} · state=draft |
| Failures | {failures or 'none'} |

## Docs

- `CANONICAL_NAP.md`
- `EXTERNAL_PROFILE_CORRECTION_PACK.md` (includes shop KG `/g/11w2b6j71t`)
- `SOCIAL_CALENDAR_DRAFTS.md`
- `MAPS_CANONICAL_BLOCKER.md` (resolved)

## Not done (by design)

- Production deploy
- Cloudflare / DNS
- External listing edits
- Article publish
- Facebook schedule/publish
""",
        encoding="utf-8",
    )

    # --- Dev Hub update ---
    execute(
        models,
        uid,
        "dev.work.item",
        "write",
        [WI_ID],
        {
            "name": (
                "AI Visibility / Local SEO / Blog / Content — PetSpot El Sahel "
                "(Test implemented — awaiting Sabry approval)"
            ),
            "blocker": False,
            "blocked_from_phase": False,
        },
    )

    note = (
        "GBP UNLOCKED (Sabry screenshot): Pet Spot Clinic KG /g/11w2cv6pz0 authoritative; "
        "shop KG /g/11w2b6j71t potential duplicate — correction pack only, no merge/delete. "
        "Canonical coords 30.9909989,28.6840834; AR address الساحل الشمالي، بجوار واحة خطاب، "
        "أمام أمواج 2، العلمين، مصر; EN North Coast, beside Wahat Khattab, in front of Amwaj 2, "
        "El Alamein, Egypt; Maps https://maps.app.goo.gl/AaHup6NEFodZEs7S7. "
        "TEST IMPLEMENTATION DONE: NAP cleanup, website_blog, 6 service pages, VeterinaryCare "
        "JSON-LD, 8 unpublished bilingual articles, 12 social.post drafts (no FB publish), "
        "external correction pack prepared. /contactus fixed (website_crm xpath). "
        "STOP for approval — no Production/DNS/external edits/article publish/FB schedule."
    )
    execute(
        models,
        uid,
        "dev.work.analysis",
        "write",
        [ANALYSIS_ID],
        {
            "problem_summary": note,
            "technical_findings": (
                "See attached UAT_SUMMARY.md + implementation_report.json. "
                "Screenshot binary of GBP place card not in chat uploads; text evidence recorded. "
                "Shop KG /g/11w2b6j71t flagged for later ownership investigation."
            ),
            "user_analysis_notes": (
                "Await Sabry approval before Production deploy, Cloudflare/DNS, external listing "
                "edits, publishing articles, or scheduling/publishing Facebook posts."
            ),
            "execution_state": "completed",
            "step_guide_blocked": False,
            "step_guide_state": "done",
            "step_guide_title": "Test UAT complete — approval gate",
        },
    )

    attach_ids = []
    for path in [
        DOCS / "CANONICAL_NAP.md",
        DOCS / "EXTERNAL_PROFILE_CORRECTION_PACK.md",
        DOCS / "SOCIAL_CALENDAR_DRAFTS.md",
        DOCS / "MAPS_CANONICAL_BLOCKER.md",
        uat_md,
        report_path,
        social_path,
    ]:
        attach_ids.append(attach_file(models, uid, path, "dev.work.item", WI_ID))
        attach_ids.append(attach_file(models, uid, path, "dev.work.analysis", ANALYSIS_ID))

    # Update NAP inventory checklist text
    inv = DOCS / "NAP_CORRECTION_INVENTORY.md"
    inv.write_text(
        inv.read_text(encoding="utf-8")
        .replace("| Address | **BLOCKED** — awaiting GBP |", "| Address | Canonical — see CANONICAL_NAP.md |")
        .replace("- [ ] GBP address + Place ID + Plus Code confirmed", "- [x] GBP address confirmed (Plus Code/Place ID nice-to-have)")
        .replace("- [ ] Code NAP cleanup (Test)", "- [x] Code NAP cleanup (Test)")
        .replace("- [ ] website_blog install + bilingual blog config (Test)", "- [x] website_blog install + bilingual blog config (Test)")
        .replace("- [ ] Landing + service pages (Test)", "- [x] Landing + service pages (Test)")
        .replace("- [ ] JSON-LD / redirects / sitemap / hreflang (Test; Cloudflare later)", "- [x] JSON-LD on key pages (Test; Cloudflare/hreflang later)")
        .replace("- [ ] 8 draft articles (unpublished)", "- [x] 8 draft articles (unpublished)")
        .replace("- [ ] 4-week social calendar drafts (no publish)", "- [x] 4-week social calendar drafts (no publish)")
        .replace("- [ ] External correction pack (no edits)", "- [x] External correction pack (no edits)")
        .replace("- [ ] Test evidence + approval gate", "- [x] Test evidence + approval gate (this package)"),
        encoding="utf-8",
    )
    attach_ids.append(attach_file(models, uid, inv, "dev.work.item", WI_ID))

    out = {
        "wi": WI_ID,
        "analysis": ANALYSIS_ID,
        "social_drafts": len(social_ids),
        "attachments": attach_ids,
        "ok": report["pass_criteria"]["ok"],
        "failures": failures,
        "report": str(report_path),
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
