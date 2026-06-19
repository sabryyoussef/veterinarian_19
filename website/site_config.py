"""Load PetSpot site config from business_data.json + environment overrides."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def _digits_only(phone: str) -> str:
    return "".join(ch for ch in phone if ch.isdigit())


def load_config() -> dict[str, Any]:
    data_path = ROOT / "business_data.json"
    with data_path.open(encoding="utf-8") as fh:
        data = json.load(fh)

    phone = os.getenv("CLINIC_PHONE", data["contact"]["phone_primary"])
    whatsapp = os.getenv("CLINIC_WHATSAPP", data["contact"]["whatsapp"])
    if not whatsapp:
        whatsapp = _digits_only(phone).lstrip("0")
        if whatsapp.startswith("20"):
            pass
        elif whatsapp.startswith("0"):
            whatsapp = "20" + whatsapp[1:]
        else:
            whatsapp = "20" + whatsapp

    maps_url = os.getenv("CLINIC_MAP_URL", data["contact"]["google_maps"])
    facebook = os.getenv("CLINIC_FACEBOOK", data["contact"]["facebook"])
    instagram = os.getenv("CLINIC_INSTAGRAM", data["contact"]["instagram"])
    email = os.getenv("CLINIC_EMAIL", data["contact"]["email"])

    area_en = os.getenv("CLINIC_AREA_EN", data["location"]["area_en"])
    area_ar = os.getenv("CLINIC_AREA_AR", data["location"]["area_ar"])

    return {
        "brand": data["brand"],
        "seo": data["seo"],
        "services": data["services"],
        "gallery_slots": data["gallery_slots"],
        "phone": phone,
        "phone_tel": phone.replace(" ", ""),
        "phone_marassi": os.getenv("CLINIC_PHONE_MARASSI", ""),
        "phone_alternate": data["contact"].get("phone_alternate", ""),
        "whatsapp": whatsapp,
        "whatsapp_url": f"https://wa.me/{whatsapp}",
        "email": email,
        "facebook": facebook,
        "instagram": instagram,
        "maps_url": maps_url,
        "area_en": area_en,
        "area_ar": area_ar,
        "hours_en": data["location"]["hours_en"],
        "hours_ar": data["location"]["hours_ar"],
        "address_note": data["location"]["address_note"],
        "company_name": os.getenv("CLINIC_COMPANY_NAME", data["brand"]["name_en"]),
        "website_url": os.getenv("WEBSITE_URL", "https://petspot.odoo.com"),
    }
