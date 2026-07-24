# -*- coding: utf-8 -*-
"""WhatsApp AI triage: fingerprint + untrusted JSON validation (schema v1+v2)."""
from __future__ import annotations

import hashlib
import json

from odoo.exceptions import ValidationError

SCHEMA_VERSION = "2"
SCHEMA_VERSION_V1 = "1"
DEFAULT_PROMPT_VERSION = "wa_project_aware_v2"

CLASSIFICATIONS_V1 = frozenset(
    {
        "new_dev_request",
        "bug_report",
        "question",
        "decision",
        "issue",
        "information",
        "noise",
        "unrelated",
        "follow_up_existing",
        "context_addition",
    }
)
CLASSIFICATIONS_V2 = frozenset(
    {
        "new_task",
        "existing_work_followup",
        "bug",
        "question",
        "context_update",
        "decision",
        "noise",
        "unclear",
    }
)
NOISE_CLASSIFICATIONS = frozenset({"noise", "unrelated", "information", "unclear"})
RECOMMENDED_ACTIONS = frozenset(
    {"ignore", "review", "reply", "create_work", "request_context", "attach_existing"}
)
PRIORITIES = frozenset({"0", "1", "2", "3"})
WI_DECISIONS = frozenset({"new", "existing", "none", "unclear"})
LANGUAGES = frozenset({"ar", "en", "mixed"})
_LANGUAGE_ALIASES = {
    "english": "en",
    "en-us": "en",
    "en_gb": "en",
    "arabic": "ar",
    "ar-eg": "ar",
    "eg": "ar",
    "mix": "mixed",
    "bilingual": "mixed",
}

V2_TO_V1_CLASS = {
    "new_task": "new_dev_request",
    "existing_work_followup": "follow_up_existing",
    "bug": "bug_report",
    "question": "question",
    "context_update": "context_addition",
    "decision": "decision",
    "noise": "noise",
    "unclear": "information",
}


def batch_fingerprint(group_jid, message_ids, prompt_version, schema_version, analysis_mode):
    payload = {
        "group_jid": (group_jid or "").strip(),
        "message_ids": sorted(int(i) for i in message_ids),
        "prompt_version": (prompt_version or DEFAULT_PROMPT_VERSION).strip(),
        "schema_version": (schema_version or SCHEMA_VERSION).strip(),
        "analysis_mode": (analysis_mode or "group_triage").strip(),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _as_int_list(value, field_name, batch_ids):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError("%s must be a list of integers." % field_name)
    out = []
    for item in value:
        try:
            mid = int(item)
        except (TypeError, ValueError) as err:
            raise ValidationError("%s contains a non-integer id." % field_name) from err
        if mid not in batch_ids:
            raise ValidationError(
                "%s id %s is not in the leased batch (untrusted AI id rejected)."
                % (field_name, mid)
            )
        out.append(mid)
    return out


def _opt_int(value, field_name):
    if value is None or value is False or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as err:
        raise ValidationError("%s must be an integer or null." % field_name) from err


def _confidence(value):
    if isinstance(value, str):
        cleaned = value.strip().lower()
        aliases = {
            "low": 0.35,
            "medium": 0.6,
            "med": 0.6,
            "high": 0.85,
            "very high": 0.95,
            "very_high": 0.95,
        }
        if cleaned in aliases:
            value = aliases[cleaned]
    try:
        confidence = float(value)
    except (TypeError, ValueError) as err:
        raise ValidationError("confidence must be a number.") from err
    if confidence < 0.0 or confidence > 1.0:
        raise ValidationError("confidence must be between 0 and 1.")
    return confidence


def _validate_v1(data, batch_ids):
    missing = {
        "schema_version",
        "summary",
        "classification",
        "should_ignore",
        "ignore_reason",
        "contains_work",
        "work_title",
        "work_description",
        "priority",
        "project_reference",
        "participants",
        "source_message_ids",
        "noise_message_ids",
        "work_message_ids",
        "confidence",
        "requires_human_review",
        "recommended_action",
        "missing_information",
    } - set(data)
    if missing:
        raise ValidationError("AI response missing keys: %s" % ", ".join(sorted(missing)))
    classification = data.get("classification")
    if classification not in CLASSIFICATIONS_V1:
        raise ValidationError("Unsupported classification: %s" % classification)
    recommended_action = data.get("recommended_action")
    if recommended_action not in RECOMMENDED_ACTIONS:
        raise ValidationError("Unsupported recommended_action: %s" % recommended_action)
    priority = str(data.get("priority"))
    if priority not in PRIORITIES:
        raise ValidationError("Unsupported priority: %s" % data.get("priority"))
    confidence = _confidence(data.get("confidence"))
    should_ignore = bool(data.get("should_ignore"))
    contains_work = bool(data.get("contains_work"))
    ignore_reason = data.get("ignore_reason")
    if should_ignore and not (ignore_reason and str(ignore_reason).strip()):
        raise ValidationError("should_ignore=true requires ignore_reason.")
    work_title = data.get("work_title")
    work_description = data.get("work_description")
    if contains_work:
        if not (work_title and str(work_title).strip()):
            raise ValidationError("contains_work=true requires work_title.")
        if not (work_description and str(work_description).strip()):
            raise ValidationError("contains_work=true requires work_description.")
    summary = str(data.get("summary") or "").strip()
    if not summary:
        raise ValidationError("summary is required.")
    return {
        "schema_version": SCHEMA_VERSION_V1,
        "summary": summary[:2000],
        "classification": classification,
        "should_ignore": should_ignore,
        "ignore_reason": (str(ignore_reason).strip() if ignore_reason else None),
        "contains_work": contains_work,
        "work_title": (str(work_title).strip()[:300] if work_title else None),
        "work_description": (
            str(work_description).strip()[:8000] if work_description else None
        ),
        "priority": priority,
        "project_reference": (
            str(data.get("project_reference")).strip()[:200]
            if data.get("project_reference")
            else None
        ),
        "participants": [str(p)[:120] for p in (data.get("participants") or [])][:50],
        "source_message_ids": _as_int_list(
            data.get("source_message_ids"), "source_message_ids", batch_ids
        ),
        "noise_message_ids": _as_int_list(
            data.get("noise_message_ids"), "noise_message_ids", batch_ids
        ),
        "work_message_ids": _as_int_list(
            data.get("work_message_ids"), "work_message_ids", batch_ids
        ),
        "confidence": confidence,
        "requires_human_review": bool(data.get("requires_human_review", True)),
        "recommended_action": recommended_action,
        "missing_information": [
            str(x)[:500] for x in (data.get("missing_information") or [])
        ][:30],
        "project_resolution": {},
        "work_item_resolution": {},
        "analysis_detail": {},
        "evidence_used": [],
        "safe_to_create_work": contains_work and not should_ignore,
        "safe_to_attach_to_existing_work": False,
        "resolved_project_id": None,
        "resolved_work_item_id": None,
        "requires_project_confirmation": False,
        "contains_multiple_tasks": False,
        "language": "mixed",
    }


def _validate_v2(data, batch_ids, project_candidate_ids=None, work_item_candidate_ids=None):
    mu = data.get("message_understanding") or {}
    pr = data.get("project_resolution") or {}
    wr = data.get("work_item_resolution") or {}
    analysis = data.get("analysis") or {}
    if not isinstance(mu, dict) or not isinstance(pr, dict) or not isinstance(wr, dict):
        raise ValidationError("v2 sections must be objects.")

    classification = mu.get("classification")
    if classification not in CLASSIFICATIONS_V2:
        raise ValidationError("Unsupported v2 classification: %s" % classification)
    language = mu.get("language") or "mixed"
    if isinstance(language, str):
        language = language.strip()
        language = _LANGUAGE_ALIASES.get(language.lower(), language.lower())
    if language not in LANGUAGES:
        raise ValidationError("Unsupported language: %s" % language)
    summary = str(mu.get("summary") or "").strip()
    if not summary:
        raise ValidationError("message_understanding.summary is required.")

    decision = wr.get("decision") or "unclear"
    if decision not in WI_DECISIONS:
        raise ValidationError("Unsupported work_item decision: %s" % decision)

    project_id = _opt_int(pr.get("project_id"), "project_resolution.project_id")
    work_item_id = _opt_int(wr.get("work_item_id"), "work_item_resolution.work_item_id")
    cand_projects = {int(i) for i in (project_candidate_ids or [])}
    cand_wis = {int(i) for i in (work_item_candidate_ids or [])}
    if project_id is not None and cand_projects and project_id not in cand_projects:
        raise ValidationError(
            "project_id %s is not in Odoo-supplied candidates." % project_id
        )
    if work_item_id is not None and cand_wis and work_item_id not in cand_wis:
        raise ValidationError(
            "work_item_id %s is not in Odoo-supplied candidates." % work_item_id
        )
    if decision == "existing" and not work_item_id:
        raise ValidationError("decision=existing requires work_item_id from candidates.")
    if decision == "existing" and work_item_id and cand_wis and work_item_id not in cand_wis:
        raise ValidationError("existing work_item_id not in candidates.")

    confidence = _confidence(data.get("confidence", pr.get("confidence", 0.0)))
    legacy_bridge = data.get("legacy_v1_bridge") or {}
    batch_msg_ids = sorted(batch_ids)
    source_ids = _as_int_list(
        legacy_bridge.get("source_message_ids") or batch_msg_ids,
        "source_message_ids",
        batch_ids,
    )
    noise_ids = _as_int_list(
        legacy_bridge.get("noise_message_ids") or [], "noise_message_ids", batch_ids
    )
    work_msg_ids = _as_int_list(
        legacy_bridge.get("work_message_ids")
        or (batch_msg_ids if decision in ("new", "existing") else []),
        "work_message_ids",
        batch_ids,
    )

    should_ignore = classification == "noise" or bool(legacy_bridge.get("should_ignore"))
    contains_work = decision in ("new", "existing") or bool(legacy_bridge.get("contains_work"))
    work_title = legacy_bridge.get("work_title") or analysis.get("business_request") or summary
    work_description = legacy_bridge.get("work_description") or json.dumps(
        {
            "business_request": analysis.get("business_request"),
            "recommended_approach": analysis.get("recommended_approach"),
            "questions": analysis.get("questions_before_implementation"),
        },
        ensure_ascii=False,
    )
    if contains_work and decision == "new" and not str(work_title or "").strip():
        raise ValidationError("New work requires a title/summary.")

    if should_ignore:
        recommended_action = "ignore"
    elif decision == "existing":
        recommended_action = "attach_existing"
    elif decision == "new":
        recommended_action = "create_work"
    elif classification == "question":
        recommended_action = "reply"
    else:
        recommended_action = "request_context"

    priority = str(legacy_bridge.get("priority") or "2")
    if priority not in PRIORITIES:
        priority = "2"

    evidence_used = data.get("evidence_used") or []
    if not isinstance(evidence_used, list):
        raise ValidationError("evidence_used must be a list.")

    return {
        "schema_version": SCHEMA_VERSION,
        "summary": summary[:2000],
        "classification": V2_TO_V1_CLASS.get(classification, "issue"),
        "classification_v2": classification,
        "should_ignore": should_ignore,
        "ignore_reason": (
            "Classified as noise/unclear" if should_ignore else None
        ),
        "contains_work": contains_work and not should_ignore,
        "work_title": (str(work_title).strip()[:300] if work_title else None),
        "work_description": (str(work_description).strip()[:8000] if work_description else None),
        "priority": priority,
        "project_reference": pr.get("project_name"),
        "participants": [],
        "source_message_ids": source_ids,
        "noise_message_ids": noise_ids,
        "work_message_ids": work_msg_ids,
        "confidence": confidence,
        "requires_human_review": True,
        "recommended_action": recommended_action,
        "missing_information": [
            str(x)[:500] for x in (mu.get("missing_information") or [])
        ][:30],
        "project_resolution": pr,
        "work_item_resolution": wr,
        "analysis_detail": analysis,
        "evidence_used": evidence_used[:40],
        "safe_to_create_work": bool(data.get("safe_to_create_work")) and decision == "new",
        "safe_to_attach_to_existing_work": bool(data.get("safe_to_attach_to_existing_work"))
        and decision == "existing"
        and bool(work_item_id),
        "resolved_project_id": project_id,
        "resolved_work_item_id": work_item_id,
        "requires_project_confirmation": bool(pr.get("requires_confirmation")),
        "contains_multiple_tasks": bool(mu.get("contains_multiple_tasks")),
        "language": language,
        "technical_terms": [str(t)[:80] for t in (mu.get("technical_terms") or [])][:40],
    }


def validate_ai_response(
    raw_text,
    batch_message_ids,
    project_candidate_ids=None,
    work_item_candidate_ids=None,
):
    """Parse and validate Dify/n8n JSON. Unknown keys are dropped."""
    if not raw_text or not str(raw_text).strip():
        raise ValidationError("AI response is empty.")
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as err:
        raise ValidationError("AI response is not valid JSON.") from err
    if not isinstance(data, dict):
        raise ValidationError("AI response must be a JSON object.")

    batch_ids = {int(i) for i in batch_message_ids}
    version = str(data.get("schema_version") or "")
    if version == SCHEMA_VERSION_V1:
        return _validate_v1(data, batch_ids)
    if version == SCHEMA_VERSION:
        return _validate_v2(
            data,
            batch_ids,
            project_candidate_ids=project_candidate_ids,
            work_item_candidate_ids=work_item_candidate_ids,
        )
    raise ValidationError(
        "Unsupported schema_version %r (expected %s or %s)."
        % (version, SCHEMA_VERSION, SCHEMA_VERSION_V1)
    )


def safe_json_dumps(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2)
