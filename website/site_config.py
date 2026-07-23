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
    address_en = os.getenv("CLINIC_ADDRESS_EN", data["location"].get("address_en", area_en))
    address_ar = os.getenv("CLINIC_ADDRESS_AR", data["location"].get("address_ar", area_ar))

    branches = data.get("branches", [])
    phone_alternate = os.getenv(
        "CLINIC_PHONE_ALTERNATE", data["contact"].get("phone_alternate", "")
    )
    # Haram branch override (legacy env: CLINIC_PHONE_MARASSI)
    phone_haram = os.getenv("CLINIC_PHONE_HARAM", os.getenv("CLINIC_PHONE_MARASSI", phone_alternate))

    return {
        "brand": data["brand"],
        "seo": data["seo"],
        "services": data["services"],
        "gallery_slots": data["gallery_slots"],
        "gallery_extra_count": int(data.get("gallery_extra_count", 12)),
        "branches": branches,
        "phone": phone,
        "phone_tel": phone.replace(" ", ""),
        "phone_haram": phone_haram,
        "phone_marassi": phone_haram,
        "phone_alternate": phone_alternate,
        "whatsapp": whatsapp,
        "whatsapp_url": f"https://wa.me/{whatsapp}",
        "email": email,
        "facebook": facebook,
        "facebook_sister": data["contact"].get("facebook_sister", ""),
        "instagram": instagram,
        "maps_url": maps_url,
        "area_en": area_en,
        "area_ar": area_ar,
        "address_en": address_en,
        "address_ar": address_ar,
        "hours_en": data["location"]["hours_en"],
        "hours_ar": data["location"]["hours_ar"],
        "address_note": data["location"]["address_note"],
        "company_name": os.getenv("CLINIC_COMPANY_NAME", data["brand"]["name_en"]),
        "website_url": os.getenv("WEBSITE_URL", "https://petspot.odoo.com"),
    }
