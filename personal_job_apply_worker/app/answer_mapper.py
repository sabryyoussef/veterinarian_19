# -*- coding: utf-8 -*-
"""Map form-field schemas to verified candidate facts (never invent)."""

from __future__ import annotations

import re
from typing import Any, Optional

from app.models import ApplicantFixture

# Verified personal facts for account id=2 (must stay truthful).
VERIFIED_FACTS: dict[str, Any] = {
    "legal_name": "Sabry Youssef",
    "email": "vendorah2@gmail.com",
    "phone": "",  # filled from applicant/profile when present
    "location": "Egypt",
    "years_odoo": "8+",
    "years_experience": "8+",
    "skills_python": "Yes",
    "skills_postgresql": "Yes",
    "skills_odoo": "Yes",
    "salary_expectation": "USD 1000/month",
    "notice_period": "1 month",
    "onsite_available": "Yes",
    "relocation": "Yes",
    "eu_work_authorization": "No",
    "belgium_work_authorization": "No",
    "visa_sponsorship_required": "Yes",
    "professional_intro": (
        "Senior Odoo developer with 8+ years of experience in Python, PostgreSQL, "
        "custom modules, integrations, and production-safe delivery."
    ),
}

# Question-variant patterns → verified fact keys
_VARIANT_MAP: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"full\s*name|legal\s*name|your\s*name|^name$", re.I), "legal_name"),
    (re.compile(r"e-?mail", re.I), "email"),
    (re.compile(r"phone|mobile|tel|whatsapp", re.I), "phone"),
    (re.compile(r"relocat", re.I), "relocation"),
    (re.compile(r"\bcity\b|\bcountry\b|\blocation\b|based\s*in|current\s*location", re.I), "location"),
    (re.compile(r"years?\s*(of\s*)?(odoo|erp)", re.I), "years_odoo"),
    (re.compile(r"years?\s*(of\s*)?experience|experience\s*level", re.I), "years_experience"),
    (re.compile(r"\bpython\b", re.I), "skills_python"),
    (re.compile(r"postgres|postgresql|psql", re.I), "skills_postgresql"),
    (re.compile(r"\bodoo\b", re.I), "skills_odoo"),
    (re.compile(r"salary|compensation|expected\s*pay|ctc|remuneration", re.I), "salary_expectation"),
    (re.compile(r"notice\s*period|availability\s*to\s*start|when\s*can\s*you\s*start", re.I), "notice_period"),
    (re.compile(r"on-?site|onsite|office\s*based|willing\s*to\s*work\s*from", re.I), "onsite_available"),
    (re.compile(r"eu\s*(work|authoriz)|european\s*union|schengen|belgium\s*(work|authoriz)", re.I), "eu_work_authorization"),
    (re.compile(r"work\s*authoriz|right\s*to\s*work|legally\s*authori[sz]ed", re.I), "eu_work_authorization"),
    (re.compile(r"visa|sponsor|work\s*permit", re.I), "visa_sponsorship_required"),
    (re.compile(r"about\s*yourself|introduction|cover\s*letter|why\s*(do\s*you\s*)?want", re.I), "professional_intro"),
]


def map_schema_to_answers(
    schema: list[dict[str, Any]],
    *,
    applicant: Optional[ApplicantFixture] = None,
    extra_facts: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, Any], list[str]]:
    """Return (answers_by_field_key, missing_required_labels).

    Unknown mandatory questions are listed in missing — never guessed.
    """
    facts = dict(VERIFIED_FACTS)
    if applicant:
        if applicant.full_name:
            facts["legal_name"] = applicant.full_name
        if applicant.email:
            facts["email"] = applicant.email
        if applicant.phone:
            facts["phone"] = applicant.phone
        if applicant.cover_letter:
            facts["professional_intro"] = applicant.cover_letter
    if extra_facts:
        facts.update({k: v for k, v in extra_facts.items() if v not in (None, "")})

    answers: dict[str, Any] = {}
    missing: list[str] = []

    for field in schema:
        label = str(field.get("label") or "")
        name = str(field.get("name") or "")
        field_id = str(field.get("field_id") or "")
        ftype = str(field.get("field_type") or "text")
        required = bool(field.get("required"))
        blob = f"{label} {name}".strip()

        if ftype == "file":
            answers[field_id or name or label] = "__CV__"
            continue
        if ftype == "password":
            if required:
                missing.append(label or name or "password")
            continue

        fact_key = None
        for pat, key in _VARIANT_MAP:
            if pat.search(blob):
                fact_key = key
                break

        # Type heuristics when label is weak
        if not fact_key:
            if ftype == "email":
                fact_key = "email"
            elif ftype == "tel":
                fact_key = "phone"

        value = facts.get(fact_key) if fact_key else None
        if value in (None, ""):
            if required:
                missing.append(label or name or field_id or "unknown_field")
            continue

        key = field_id or name or label
        answers[key] = value
        if name and name != key:
            answers[name] = value
        if label and label != key:
            answers[label] = value

    return answers, missing
