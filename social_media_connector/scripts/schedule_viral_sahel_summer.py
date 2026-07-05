#!/usr/bin/env python3
"""Publish + hourly-repost viral Sahel summer safety interactive Facebook post."""
from __future__ import annotations

import base64
import mimetypes
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import MODULE_ROOT, get_campaign_prefix, get_odoo_client, load_env_file  # noqa: E402

TZ = ZoneInfo("Africa/Cairo")
TOPIC = "Sahel Summer Safety — Interactive"
PREFIX = get_campaign_prefix()
IMAGE_PATH = MODULE_ROOT / "assets" / "images" / "petspot-opening-hero.png"
ACCOUNT_ID = 4
HOURS = 7 * 24          # hourly for 7 days (including slots after first publish)
INTERVAL_MIN = 60

FOOTER = (
    "\n\n---\n"
    "📞 Call: 01201568888\n"
    "💬 WhatsApp: 01000059085\n"
    "🌐 petspot.odoo.com\n"
    "📘 Facebook: بيت الدواء البيطري -pet spot\n"
    "📍 Beside Amwaj 1 gate, Main Road, Sidi Abdel Rahman, North Coast\n"
    "🗺️ Google Maps: PetSpot Amwaj 1 gate\n\n"
    "---\n"
    "📞 اتصل: 01201568888\n"
    "💬 واتساب: 01000059085\n"
    "🌐 petspot.odoo.com\n"
    "📘 فيسبوك: بيت الدواء البيطري -pet spot\n"
    "📍 بجوار بوابة أمواج 1، الطريق الرئيسي، سيدي عبد الرحمن، الساحل الشمالي\n"
    "🗺️ خرائط جوجل: بجوار بوابة أمواج 1"
)

BODY = """**نازل الساحل ومعاك كلبك؟ اقرأ ده قبل ما يحصل مشكلة.**

🐾 الساحل مش بس للناس… ده كمان موسم تعب للحيوانات!

قبل ما تنزل بكلبك أو قطتك الساحل، افتكر إن الحر والرطوبة والرمل والسفر ممكن يعملوا مشاكل بسرعة:

☀️ بلاش مشي وقت الظهر
🚗 بلاش تسيبه في العربية حتى "دقيقتين"
💧 خليه يشرب مياه كتير
🐶 لو بيلهث جامد / مرهق / بيرجع / مش قادر يقف — دي علامة خطر
🦟 متنساش الحماية من الحشرات والقراد والبراغيث
🛁 وبعد البحر أو الرمل، لازم تنظيف كويس للجلد والودان

في **PetSpot Vet Clinic – Sahel** إحنا جاهزين لموسم الصيف:
كشف، تطعيمات، grooming، boarding، وزيارات منزلية.

اكتب في الكومنت:
**اسم حيوانك + أول حاجة بيعملها لما يوصل الساحل؟** 😂🐶🐱

---

كلبك في الساحل مش محتاج بحر بس… محتاج مياه، ظل، حماية من الحشرات، ومتابعة لو ظهر أي تعب.
اكتبلنا اسم حيوانك في الكومنت وهنقولك أهم نصيحة صيفية له 🐾

#PetSpotSahel #VetClinic #NorthCoast #SahelPets #DogCare #CatCare #PetCareEgypt #SummerPets #VeterinaryClinic #Grooming #Boarding #PetSafety"""


def _to_utc(local_dt: datetime) -> str:
    if local_dt.tzinfo is None:
        local_dt = local_dt.replace(tzinfo=TZ)
    return local_dt.astimezone(ZoneInfo("UTC")).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


def _message(slot: int, *, live: bool = False) -> str:
    title = f"{PREFIX} {TOPIC}" if live else f"{PREFIX} {TOPIC} (repost {slot})"
    return f"{title}\n\n{BODY.strip()}{FOOTER}"


def _upload_image(client, path: Path) -> int:
    if not path.exists():
        raise FileNotFoundError(path)
    mimetype = mimetypes.guess_type(path.name)[0] or "image/png"
    raw_b64 = base64.b64encode(path.read_bytes()).decode()
    base = {"name": path.name, "type": "binary", "mimetype": mimetype, "res_model": "social.post"}
    for field in ("datas", "raw"):
        try:
            att_id = client.create("ir.attachment", {**base, field: raw_b64})
            row = client.search_read("ir.attachment", [("id", "=", att_id)], ["file_size", "checksum"], limit=1)
            if row and row[0].get("file_size") and row[0].get("checksum"):
                return att_id
        except RuntimeError:
            continue
    raise RuntimeError(f"Image upload failed for {path}")


def main() -> int:
    load_env_file(MODULE_ROOT / ".env")
    client = get_odoo_client("remote")
    client.authenticate()
    account_id = ACCOUNT_ID

    print("Uploading image...")
    att_id = _upload_image(client, IMAGE_PATH)

    now_local = datetime.now(TZ)
    print(f"\n1) Publishing NOW ({now_local.strftime('%Y-%m-%d %H:%M')} Cairo)...")
    post_id = client.create(
        "social.post",
        {
            "post_method": "now",
            "account_ids": [(6, 0, [account_id])],
            "message": _message(1, live=True),
            "image_ids": [(6, 0, [att_id])],
        },
    )
    client.execute("social.post", "action_post", [post_id])
    row = client.search_read("social.post", [("id", "=", post_id)], ["state", "published_date"], limit=1)[0]
    print(f"   → id={post_id} state={row['state']}")

    print(f"\n2) Scheduling {HOURS - 1} hourly reposts for 7 days...")
    start = now_local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    created = 0
    for i in range(1, HOURS):
        slot_local = start + timedelta(hours=i - 1)
        slot_utc = _to_utc(slot_local)
        msg = _message(i + 1)
        post_id = client.create(
            "social.post",
            {
                "post_method": "scheduled",
                "scheduled_date": slot_utc,
                "account_ids": [(6, 0, [account_id])],
                "message": msg,
                "image_ids": [(6, 0, [att_id])],
            },
        )
        client.execute("social.post", "action_schedule", [post_id])
        created += 1
        if i <= 3 or i == HOURS - 1:
            print(f"   slot {i}: id={post_id} → {slot_local.strftime('%Y-%m-%d %H:%M')} Cairo")

    print(f"\nDone. Published 1 now + scheduled {created} hourly reposts (7 days).")
    print(f"View: {client.url}/odoo/social-posts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
