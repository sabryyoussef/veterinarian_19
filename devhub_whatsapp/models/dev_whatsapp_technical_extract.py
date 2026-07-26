# -*- coding: utf-8 -*-
"""Pure technical evidence extraction from WhatsApp message texts (AR+EN)."""
from __future__ import annotations

import re

from odoo import api, models

# Markers that indicate unavailable / encrypted content
_MISSING_MARKERS = (
    "content unavailable",
    "encrypted",
    "unsupported",
    "waiting for this message",
    "رسالة مشفرة",
    "محتوى غير متاح",
    "غير مدعوم",
)

_URL_RE = re.compile(
    r"https?://[^\s<>\"')\]]+|www\.[^\s<>\"')\]]+",
    re.IGNORECASE,
)
_RPC_ERROR_RE = re.compile(r"\bRPC_ERROR\b", re.IGNORECASE)
_PERMISSION_ERROR_RE = re.compile(r"\bPermissionError\b")
_TRACEBACK_RE = re.compile(
    r"Traceback \(most recent call last\):.*?(?=\n\S|\Z)",
    re.DOTALL | re.IGNORECASE,
)
_PATH_RE = re.compile(
    r"(?:"
    r"index\.html|html4css1\.css|"
    r"[A-Za-z0-9_./\-]+\.(?:py|xml|js|css|scss|html|csv)"
    r")",
    re.IGNORECASE,
)
# Odoo-style technical module tokens (snake_case, often with underscores)
_MODULE_RE = re.compile(
    r"\b(?:"
    r"edafaa_student_profile|batch_intake|"
    r"[a-z][a-z0-9]*(?:_[a-z0-9]+){1,6}"
    r")\b"
)
_MODEL_RE = re.compile(r"\b[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+\b")
_METHOD_RE = re.compile(r"\b(?:def\s+)?([a-z_][a-z0-9_]{2,})\s*\(")
_XML_ID_RE = re.compile(
    r"\b([a-z][a-z0-9_]*)\.(?:view_|action_|menu_|model_|ir_|res_)[a-z0-9_.]+\b",
    re.IGNORECASE,
)
_WORK_REF_RE = re.compile(
    r"(?:"
    r"(?:OP|WI|WP|DH)[\s_\-]*#?\s*\d+"
    r"|#\d{2,6}"
    r"|work[\s_-]?item\s*#?\s*\d+"
    r"|مهمة\s*#?\s*\d+"
    r"|تذكرة\s*#?\s*\d+"
    r")",
    re.IGNORECASE,
)

# Noise modules / models that match the broad patterns too often
_MODULE_STOPWORDS = frozenset(
    {
        "message_timestamp",
        "inbox_state",
        "group_jid",
        "sender_jid",
        "media_kind",
        "schema_version",
        "prompt_version",
        "analysis_mode",
        "work_item",
        "dev_project",
        "project_id",
        "user_id",
        "create_date",
        "write_date",
        "display_name",
        "res_users",
        "ir_ui",
        "most_recent",
        "call_last",
        "action_confirm",
        "view_batch_form",
    }
)
_MODEL_STOPWORDS = frozenset(
    {
        "www.google.com",
        "www.odoo.com",
        "example.com",
    }
)
_FILE_EXT_RE = re.compile(r"\.(?:py|xml|js|css|scss|html|csv|png|jpg|jpeg|gif)$", re.I)


def _empty_evidence():
    return {
        "detected_errors": [],
        "tracebacks": [],
        "detected_paths": [],
        "detected_modules": [],
        "detected_models": [],
        "detected_methods": [],
        "detected_xml_ids": [],
        "detected_urls": [],
        "detected_work_references": [],
        "missing_content": False,
    }


def _uniq(items, limit=40):
    seen = set()
    out = []
    for item in items:
        key = str(item).strip()
        if not key or key.lower() in seen:
            continue
        seen.add(key.lower())
        out.append(key)
        if len(out) >= limit:
            break
    return out


def _looks_missing(text):
    lower = (text or "").strip().lower()
    if not lower:
        return True
    return any(marker in lower for marker in _MISSING_MARKERS)


def extract_technical_evidence(texts):
    """Extract technical signals from a list of message body strings.

    Returns a dict with keys:
    detected_errors, tracebacks, detected_paths, detected_modules,
    detected_models, detected_methods, detected_xml_ids, detected_urls,
    detected_work_references, missing_content.
    """
    evidence = _empty_evidence()
    if not texts:
        evidence["missing_content"] = True
        return evidence

    joined_parts = []
    any_real = False
    missing_any = False
    for raw in texts:
        text = raw if isinstance(raw, str) else (str(raw) if raw else "")
        if _looks_missing(text):
            missing_any = True
            continue
        any_real = True
        joined_parts.append(text)

    if not any_real:
        evidence["missing_content"] = True
        return evidence
    if missing_any:
        evidence["missing_content"] = True

    blob = "\n".join(joined_parts)

    errors = []
    if _RPC_ERROR_RE.search(blob):
        errors.append("RPC_ERROR")
    if _PERMISSION_ERROR_RE.search(blob):
        errors.append("PermissionError")
    # Generic Error / Exception tokens when accompanied by traceback-ish context
    for match in re.finditer(
        r"\b([A-Z][A-Za-z]*(?:Error|Exception))\b", blob
    ):
        errors.append(match.group(1))
    evidence["detected_errors"] = _uniq(errors)

    tracebacks = [m.group(0)[:4000] for m in _TRACEBACK_RE.finditer(blob)]
    evidence["tracebacks"] = _uniq(tracebacks, limit=10)

    evidence["detected_paths"] = _uniq(_PATH_RE.findall(blob))

    modules = []
    for match in _MODULE_RE.finditer(blob):
        token = match.group(0)
        if token.lower() in _MODULE_STOPWORDS:
            continue
        if token.startswith(("action_", "view_", "get_", "set_", "_")):
            continue
        # Prefer tokens that look like Odoo modules (underscore + length)
        if "_" not in token and token not in (
            "edafaa_student_profile",
            "batch_intake",
        ):
            continue
        modules.append(token)
    # Always surface well-known tokens if present
    for known in ("edafaa_student_profile", "batch_intake"):
        if re.search(r"\b%s\b" % re.escape(known), blob) and known not in modules:
            modules.append(known)
    evidence["detected_modules"] = _uniq(modules)

    models = []
    for match in _MODEL_RE.finditer(blob):
        token = match.group(0)
        if token.lower() in _MODEL_STOPWORDS:
            continue
        if token.lower().startswith("www."):
            continue
        if "/" in token or _FILE_EXT_RE.search(token):
            continue
        # Skip host-like two-part domains without odoo-ish left side
        parts = token.split(".")
        if len(parts) == 2 and parts[1] in ("com", "org", "net", "io", "html", "css", "py"):
            continue
        # XML ids are tracked separately
        if any(parts[-1].startswith(p) for p in ("view_", "action_", "menu_", "model_")):
            continue
        models.append(token)
    evidence["detected_models"] = _uniq(models)

    methods = []
    for match in _METHOD_RE.finditer(blob):
        name = match.group(1)
        if name in ("if", "for", "while", "print", "len", "str", "int"):
            continue
        methods.append(name)
    evidence["detected_methods"] = _uniq(methods)

    evidence["detected_xml_ids"] = _uniq(
        [m.group(0) for m in _XML_ID_RE.finditer(blob)]
    )
    evidence["detected_urls"] = _uniq(_URL_RE.findall(blob))
    evidence["detected_work_references"] = _uniq(
        [m.group(0).strip() for m in _WORK_REF_RE.finditer(blob)]
    )
    return evidence


def extract_from_messages(messages):
    """Extract technical evidence from a whatsapp.message recordset."""
    texts = []
    for msg in messages:
        body = getattr(msg, "body", None) or ""
        texts.append(body)
    return extract_technical_evidence(texts)


class DevWhatsappTechnicalExtract(models.AbstractModel):
    """Thin model helper wrapping pure extract functions."""

    _name = "dev.whatsapp.technical.extract"
    _description = "WhatsApp Technical Evidence Extractor"

    @api.model
    def extract_technical_evidence(self, texts):
        return extract_technical_evidence(texts)

    @api.model
    def extract_from_messages(self, messages):
        return extract_from_messages(messages)
