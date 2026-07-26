"""JSON-LD builders for PetSpot El Sahel (VeterinaryCare + FAQ + Article)."""
from __future__ import annotations

import json
from typing import Any


def veterinary_care_ld(c: dict[str, Any], page_url: str | None = None) -> dict[str, Any]:
    url = page_url or c["website_url"].rstrip("/") + "/"
    logo = c.get("logo_url") or f"{c['website_url'].rstrip('/')}/web/image/res.company/1/logo"
    # Public sameAs: Facebook + Instagram only. Never include disputed legacy Google listing KG.
    same_as = [c["facebook"]]
    if c.get("instagram"):
        same_as.append(c["instagram"].rstrip("/"))

    contacts = [
        {
            "@type": "ContactPoint",
            "telephone": c["phone_e164"],
            "contactType": "customer service",
            "areaServed": "EG",
            "availableLanguage": ["en", "ar"],
        },
        {
            "@type": "ContactPoint",
            "telephone": f"+{c['whatsapp']}" if not str(c["whatsapp"]).startswith("+") else c["whatsapp"],
            "contactType": "customer support",
            "contactOption": "TollFree",
            "areaServed": "EG",
            "availableLanguage": ["en", "ar"],
        },
    ]
    if c.get("call_center_e164"):
        contacts.insert(
            1,
            {
                "@type": "ContactPoint",
                "telephone": c["call_center_e164"],
                "contactType": "customer service",
                "name": "Call center",
                "areaServed": "EG",
                "availableLanguage": ["en", "ar"],
            },
        )

    return {
        "@context": "https://schema.org",
        "@type": ["VeterinaryCare", "LocalBusiness"],
        "@id": f"{c['website_url'].rstrip('/')}/#veterinarycare",
        "name": c["company_name"],
        "alternateName": [
            n for n in [
                c["brand"].get("marketing_name_en", ""),
                c["brand"].get("marketing_name_ar", ""),
                c["brand"].get("name_ar", ""),
            ]
            if n and n != c["company_name"]
        ],
        "url": url,
        "logo": logo,
        "image": logo,
        "telephone": c["phone_e164"],
        "email": c.get("email") or None,
        "address": {
            "@type": "PostalAddress",
            "streetAddress": c["address_en"],
            "addressLocality": c.get("city_en", "El Alamein"),
            "addressRegion": "Matrouh",
            "addressCountry": "EG",
        },
        "geo": {
            "@type": "GeoCoordinates",
            "latitude": c["latitude"],
            "longitude": c["longitude"],
        },
        "hasMap": c["maps_url"],
        "openingHoursSpecification": [
            {
                "@type": "OpeningHoursSpecification",
                "dayOfWeek": [
                    "Monday",
                    "Tuesday",
                    "Wednesday",
                    "Thursday",
                    "Friday",
                    "Saturday",
                    "Sunday",
                ],
                "opens": "00:00",
                "closes": "23:59",
            }
        ],
        "contactPoint": contacts,
        "sameAs": [s for s in same_as if s],
        "areaServed": [
            {"@type": "Place", "name": "Amwaj"},
            {"@type": "Place", "name": "Sidi Abdel Rahman"},
            {"@type": "Place", "name": "El Alamein"},
            {"@type": "Place", "name": "North Coast Egypt"},
        ],
        "availableService": [
            {"@type": "MedicalProcedure", "name": "Veterinary consultation"},
            {"@type": "MedicalProcedure", "name": "Emergency veterinary care"},
            {"@type": "MedicalProcedure", "name": "Pet vaccination"},
            {"@type": "Service", "name": "Pet grooming"},
            {"@type": "Service", "name": "Pet boarding"},
            {"@type": "Service", "name": "Veterinary home visit"},
        ],
    }


def organization_ld(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "@id": f"{c['website_url'].rstrip('/')}/#organization",
        "name": c["company_name"],
        "url": c["website_url"],
        "logo": c.get("logo_url")
        or f"{c['website_url'].rstrip('/')}/web/image/res.company/1/logo",
        "sameAs": [c["facebook"], c.get("instagram", "").rstrip("/")],
    }


def faq_ld(faqs: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
            for q, a in faqs
        ],
    }


def article_ld(
    *,
    headline: str,
    description: str,
    url: str,
    date_published: str,
    image: str | None,
    c: dict[str, Any],
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": headline,
        "description": description,
        "url": url,
        "datePublished": date_published,
        "dateModified": date_published,
        "inLanguage": ["en", "ar"],
        "author": {"@type": "Organization", "name": c["company_name"]},
        "publisher": {
            "@type": "Organization",
            "name": c["company_name"],
            "logo": {
                "@type": "ImageObject",
                "url": c.get("logo_url")
                or f"{c['website_url'].rstrip('/')}/web/image/res.company/1/logo",
            },
        },
        "mainEntityOfPage": url,
    }
    if image:
        data["image"] = image
    return data


def script_tag(*objs: dict[str, Any]) -> str:
    chunks = []
    for obj in objs:
        cleaned = json.loads(json.dumps(obj, ensure_ascii=False, default=str))
        # Drop null emails
        if cleaned.get("email") is None:
            cleaned.pop("email", None)
        payload = json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))
        chunks.append(
            f'<script type="application/ld+json">{payload}</script>'
        )
    return "\n".join(chunks)
