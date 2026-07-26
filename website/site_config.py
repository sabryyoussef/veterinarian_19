"""Load PetSpot site config from business_data.json + environment overrides."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def _digits_only(phone: str) -> str:
    return "".join(ch for ch in phone if ch.isdigit())


def _wa_digits(raw: str) -> str:
    digits = _digits_only(raw)
    if digits.startswith("20"):
        return digits
    if digits.startswith("0"):
        return "20" + digits[1:]
    return "20" + digits


def load_config() -> dict[str, Any]:
    data_path = ROOT / "business_data.json"
    with data_path.open(encoding="utf-8") as fh:
        data = json.load(fh)

    contact = data["contact"]
    geo = data["geo"]
    hours = data["hours"]

    phone = os.getenv("CLINIC_PHONE", contact["phone_primary"])
    call_center = os.getenv(
        "CLINIC_CALL_CENTER", contact.get("phone_call_center", "")
    )
    whatsapp = os.getenv("CLINIC_WHATSAPP", contact["whatsapp"])
    whatsapp = _wa_digits(whatsapp)

    maps_url = os.getenv("CLINIC_MAP_URL", contact["google_maps"])
    facebook = os.getenv("CLINIC_FACEBOOK", contact["facebook"])
    instagram = os.getenv("CLINIC_INSTAGRAM", contact["instagram"])
    email = os.getenv("CLINIC_EMAIL", contact["email"])

    address_en = os.getenv("CLINIC_ADDRESS_EN", geo["address_en"])
    address_ar = os.getenv("CLINIC_ADDRESS_AR", geo["address_ar"])
    area_en = os.getenv("CLINIC_AREA_EN", geo["area_en"])
    area_ar = os.getenv("CLINIC_AREA_AR", geo["area_ar"])

    lat = float(os.getenv("CLINIC_LAT", str(geo["latitude"])))
    lng = float(os.getenv("CLINIC_LNG", str(geo["longitude"])))

    company_name = os.getenv(
        "CLINIC_COMPANY_NAME", data["brand"].get("name_en") or data["brand"].get("gbp_name", "pet.spot")
    )

    return {
        "brand": data["brand"],
        "seo": data["seo"],
        "services": data["services"],
        "gallery_slots": data["gallery_slots"],
        "gallery_extra_count": int(data.get("gallery_extra_count", 12)),
        "phone": contact.get("phone_primary_display")
        or phone.replace("+20", "0 ").replace("+", ""),
        "phone_tel": phone.replace(" ", ""),
        "phone_e164": phone.replace(" ", ""),
        "call_center": contact.get("phone_call_center_display")
        or call_center.replace("+20", "0 ").replace("+", ""),
        "call_center_tel": call_center.replace(" ", "") if call_center else "",
        "call_center_e164": call_center.replace(" ", "") if call_center else "",
        "whatsapp": whatsapp,
        "whatsapp_url": f"https://wa.me/{whatsapp}",
        "email": email,
        "facebook": facebook.rstrip("/"),
        "instagram": instagram.rstrip("/") + "/",
        "maps_url": maps_url,
        # Legacy Google listing IDs are internal-only — never promote via config defaults.
        "kg_id": "",
        "kg_duplicate_shop": "",
        "location_policy": contact.get("location_policy") or {},
        "area_en": area_en,
        "area_ar": area_ar,
        "address_en": address_en,
        "address_ar": address_ar,
        "city_en": geo.get("city_en", "El Alamein"),
        "hours_en": hours["hours_en"],
        "hours_ar": hours["hours_ar"],
        "emergency_en": hours["emergency_en"],
        "emergency_ar": hours["emergency_ar"],
        "opening_hours_spec": hours.get("opening_hours_spec", ["Mo-Su 00:00-23:59"]),
        "latitude": lat,
        "longitude": lng,
        "company_name": company_name,
        "website_url": os.getenv("WEBSITE_URL", "https://drpaws.ai"),
        "contact": contact,
        "geo": geo,
        "hours": hours,
    }
