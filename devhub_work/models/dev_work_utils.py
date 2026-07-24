# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import re
import uuid

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


MAX_TEXT = 12000
# Byte ceiling for a whole outbox/generation JSON payload. A consolidated
# merge_analysis context legitimately carries many per-field limits that sum to
# ~33k chars (≈66 KB once Arabic UTF-8 is counted at ~2 bytes/char), so 16 KB was
# too small and produced "Outbox JSON exceeds the byte limit." 128 KiB keeps a
# sane bound while the per-string (MAX_JSON_STRING), item-count (MAX_JSON_ITEMS),
# nesting (MAX_JSON_DEPTH), and secret/forbidden-content guards still apply.
MAX_JSON = 131072
MAX_BRIEF = 16000
MAX_JSON_DEPTH = 6
MAX_JSON_ITEMS = 200
# Per-string cap inside outbox/generation JSON. Must be >= the largest
# per-field context limit built in _build_generation_context (technical_findings
# and human_analysis are bounded to 6000), otherwise a legitimate long analysis
# is rejected with "Outbox JSON value exceeds the storage limit." The whole
# payload stays bounded by MAX_JSON bytes, MAX_JSON_ITEMS, and MAX_JSON_DEPTH.
MAX_JSON_STRING = 6000

SECRET_PATTERN = re.compile(
    r"(?ix)"
    r"(?:authorization|proxy-authorization)\s*[\"']?\s*[:=]\s*[^\s,;]+|"
    r"\b(?:bearer|basic)\s+[a-z0-9._~+/=-]{8,}|"
    r"\b(?:password|passwd|pwd|secret|client_secret|access_token|refresh_token|"
    r"api[_-]?key|private[_-]?key)\b\s*[\"']?\s*[:=]\s*[^\s,;]+|"
    r"\bAKIA[0-9A-Z]{16}\b|"
    r"\bgh[opusr]_[A-Za-z0-9_]{20,}\b|"
    r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b|"
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b|"
    r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@|"
    r"-----BEGIN [A-Z0-9 ]*(?:PRIVATE KEY|OPENSSH KEY)-----"
)
FORBIDDEN_CONTENT = re.compile(
    r"(?im)"
    r"^(?:diff --git|index [0-9a-f]+\.\.[0-9a-f]+|@@ .+ @@|\+\+\+ b/|--- a/)|"
    r"^\s*(?:export\s+)?(?:PATH|HOME|AWS_[A-Z0-9_]+|DATABASE_URL|"
    r"OPENAI_API_KEY|ODOO_RC)\s*=|"
    r"[\"']?(?:raw_payload|environment_dump|full_diff|transcript|messages)"
    r"[\"']?\s*:"
)
FORBIDDEN_JSON_KEYS = {
    "authorization",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "diff",
    "env",
    "environment_variables",
    "headers",
    "password",
    "private_key",
    "raw",
    "raw_payload",
    "request",
    "response",
    "secret",
    "token",
    "transcript",
}

LIFECYCLE_SELECTION = [
    ("received", "Received"),
    ("triage", "Triage"),
    ("registered", "Registered"),
    ("analyzing", "Analyzing"),
    ("planning", "Planning"),
    ("awaiting_plan_approval", "Awaiting Plan Approval"),
    ("approved", "Approved"),
    ("implementing", "Implementing"),
    ("paused", "Paused"),
    ("blocked", "Blocked"),
    ("testing", "Testing"),
    ("ready_for_review", "Ready for Review"),
    ("completed", "Completed"),
    ("reported", "Reported"),
    ("cancelled", "Cancelled"),
]
LIFECYCLE_TRANSITIONS = {
    "received": {"triage", "cancelled"},
    "triage": {"registered", "cancelled"},
    "registered": {"analyzing", "blocked", "cancelled"},
    "analyzing": {"planning", "triage", "blocked", "cancelled"},
    "planning": {"awaiting_plan_approval", "blocked", "cancelled"},
    "awaiting_plan_approval": {"approved", "planning", "blocked", "cancelled"},
    "approved": {"implementing", "awaiting_plan_approval", "cancelled"},
    "implementing": {"paused", "blocked", "testing", "cancelled"},
    "paused": {"implementing", "blocked", "cancelled"},
    "blocked": {
        "triage",
        "analyzing",
        "planning",
        "awaiting_plan_approval",
        "approved",
        "implementing",
        "testing",
        "ready_for_review",
        "cancelled",
    },
    "testing": {"implementing", "ready_for_review", "blocked", "cancelled"},
    "ready_for_review": {"implementing", "testing", "completed", "blocked", "cancelled"},
    "completed": {"reported"},
    "reported": set(),
    "cancelled": set(),
}


def _uuid(*_args):
    return str(uuid.uuid4())


def _canonical_hash(payload):
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _clean_text(value, label, limit=MAX_TEXT):
    if value is None or value is False:
        value = ""
    if not isinstance(value, str):
        raise ValidationError("%s must be text." % label)
    value = value.strip()
    if len(value) > limit:
        raise ValidationError("%s exceeds the %s-character storage limit." % (label, limit))
    if SECRET_PATTERN.search(value):
        raise ValidationError("%s appears to contain credential material." % label)
    if FORBIDDEN_CONTENT.search(value):
        raise ValidationError(
            "%s contains a raw payload, environment dump, diff, or transcript." % label
        )
    return value


def _clean_note_text(value, label, limit=MAX_TEXT):
    """Softer guard for human-authored notes (e.g. My Analysis).

    Humans legitimately quote diff hunks, env lines, or use words like
    "messages:"/"transcript:" that trip FORBIDDEN_CONTENT. Those are neutralized
    later via ``_neutralize_forbidden``/``_context_text`` when the merge context is
    built, so we only enforce type, length, and SECRET_PATTERN here — real
    credentials are still never allowed through.
    """
    if value is None or value is False:
        value = ""
    if not isinstance(value, str):
        raise ValidationError("%s must be text." % label)
    value = value.strip()
    if len(value) > limit:
        raise ValidationError("%s exceeds the %s-character storage limit." % (label, limit))
    if SECRET_PATTERN.search(value):
        raise ValidationError("%s appears to contain credential material." % label)
    return value


def _bounded(value, limit):
    value = (value or "").strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _neutralize_forbidden(value):
    """Rewrite human-authored evidence so the outbox guard patterns do not reject it.

    Analysis notes legitimately quote diff hunks, env lines, or use plain words like
    "messages:"/"transcript:" that collide with FORBIDDEN_CONTENT. We keep the meaning
    (bracketing/relabelling) instead of blocking the whole merge. SECRET_PATTERN still
    applies afterwards, so real credentials are never let through.
    """
    if not value or not isinstance(value, str):
        return value
    text = value
    text = re.sub(r"(?i)\braw_payload\s*:", "payload-ref:", text)
    text = re.sub(r"(?i)\benvironment_dump\s*:", "env-ref:", text)
    text = re.sub(r"(?i)\bfull_diff\s*:", "diff-ref:", text)
    text = re.sub(r"(?i)\btranscript\s*:", "discussion:", text)
    text = re.sub(r"(?i)\bmessages\s*:", "source notes:", text)
    text = re.sub(
        r"(?m)^(diff --git|index [0-9a-f]+\.\.[0-9a-f]+|@@ .+ @@|\+\+\+ b/|--- a/)",
        r"[\1]",
        text,
    )
    text = re.sub(
        r"(?im)^(\s*)((?:export\s+)?"
        r"(?:PATH|HOME|AWS_[A-Z0-9_]+|DATABASE_URL|OPENAI_API_KEY|ODOO_RC)\s*=)",
        r"\1[env] \2",
        text,
    )
    return text


def _context_text(value, limit):
    """Bounded, guard-safe rendering of human/analysis free text for generation context."""
    return _bounded(_neutralize_forbidden(value), limit)


def _validate_text_values(model, values, limit=MAX_TEXT):
    for name, value in values.items():
        field = model._fields.get(name)
        if field and field.type in ("char", "text") and value:
            _clean_text(value, field.string or name, limit)


def _normalize_aliases(values, aliases):
    for alias, canonical in aliases.items():
        if alias not in values:
            continue
        if canonical in values and values[canonical] != values[alias]:
            raise ValidationError(
                "Conflicting values were supplied for %s and %s." % (alias, canonical)
            )
        values[canonical] = values.pop(alias)


def _validate_json_value(value, depth=0, counter=None):
    if counter is None:
        counter = [0]
    if depth > MAX_JSON_DEPTH:
        raise ValidationError("Outbox JSON exceeds the maximum nesting depth.")
    counter[0] += 1
    if counter[0] > MAX_JSON_ITEMS:
        raise ValidationError("Outbox JSON contains too many values.")
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        _clean_text(value, "Outbox JSON value", MAX_JSON_STRING)
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, depth + 1, counter)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in FORBIDDEN_JSON_KEYS:
                raise ValidationError("Outbox JSON contains a forbidden key: %s." % key)
            if len(str(key)) > 80:
                raise ValidationError("Outbox JSON key is too long.")
            _validate_json_value(item, depth + 1, counter)
        return
    raise ValidationError("Outbox JSON contains an unsupported value type.")


def _validated_json(payload):
    if isinstance(payload, str):
        if len(payload.encode("utf-8")) > MAX_JSON:
            raise ValidationError("Outbox JSON exceeds the byte limit.")
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Outbox payload must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValidationError("Outbox payload must be a JSON object.")
    _validate_json_value(payload)
    result = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(result.encode("utf-8")) > MAX_JSON:
        raise ValidationError("Outbox JSON exceeds the byte limit.")
    return result


def _require_approver(env):
    if not env.is_superuser() and not env.user.has_group(
        "devhub_core.group_dev_hub_approver"
    ):
        raise AccessError("A Dev Hub approver must authorize this action.")


def _require_importer(env):
    if env.is_superuser():
        return
    is_manager = env.user.has_group("devhub_core.group_dev_hub_manager")
    is_guarded_generation = env.user.has_group(
        "devhub_core.group_dev_hub_generation"
    ) and env.context.get("dev_generation_import")
    allowed = is_manager or is_guarded_generation
    if not allowed:
        raise AccessError(
            "Draft import requires the guarded generation callback or a manager."
        )



