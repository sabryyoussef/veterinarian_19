# -*- coding: utf-8 -*-
"""WhatsApp AI triage: fingerprint + untrusted JSON validation (schema v1+v2)."""
from __future__ import annotations

import hashlib
import json

from odoo.exceptions import ValidationError

SCHEMA_VERSION = "3"
SCHEMA_VERSION_V1 = "1"
SCHEMA_VERSION_V2 = "2"
SCHEMA_VERSION_V3 = "3"
DEFAULT_PROMPT_VERSION = "wa_project_aware_v3.0"

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
        "information",
        "unclear",
    }
)
NOISE_CLASSIFICATIONS = frozenset({"noise", "unrelated", "information", "unclear"})
RECOMMENDED_ACTIONS = frozenset(
    {"ignore", "review", "reply", "create_work", "request_context", "attach_existing"}
)
CLASSIFICATIONS_V3 = frozenset(
    {
        "bug",
        "enhancement",
        "investigation",
        "support",
        "documentation",
        "deployment",
        "configuration",
        "data_issue",
        "unknown",
    }
)
ACTIONS_V3 = frozenset(
    {
        "ignore",
        "request_information",
        "update_existing_work",
        "create_work",
        "create_multiple_work_items",
        "escalate",
        "review_only",
    }
)
NON_ACTIONABLE_V3 = frozenset({"ignore", "review_only"})
V3_TO_V2_CLASS = {
    "bug": "bug",
    "enhancement": "new_task",
    "investigation": "unclear",
    "support": "question",
    "documentation": "information",
    "deployment": "new_task",
    "configuration": "new_task",
    "data_issue": "bug",
    "unknown": "unclear",
}
V3_TO_V1_ACTION = {
    "ignore": "ignore",
    "request_information": "request_context",
    "update_existing_work": "attach_existing",
    "create_work": "create_work",
    "create_multiple_work_items": "create_work",
    "escalate": "review",
    "review_only": "review",
}
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
    "information": "information",
    "unclear": "information",
}

# Coarse / legacy evaluation labels → canonical schema-v2
COARSE_TO_V2_CLASS = {
    "bug": "bug",
    "bug_report": "bug",
    "feature": "new_task",
    "new_task": "new_task",
    "new_dev_request": "new_task",
    "follow_up": "existing_work_followup",
    "follow_up_existing": "existing_work_followup",
    "existing_work_followup": "existing_work_followup",
    "context": "context_update",
    "context_addition": "context_update",
    "context_update": "context_update",
    "info": "information",
    "information": "information",
    "noise": "noise",
    "unrelated": "noise",
    "question": "question",
    "decision": "decision",
    "unclear": "unclear",
}


def normalize_classification_v2(label, wi_decision=None, is_actionable=False):
    """Map coarse/legacy/v1/v2 labels onto CLASSIFICATIONS_V2."""
    if not label:
        return "unclear"
    key = str(label).strip().lower()
    if key == "none":
        return "noise" if wi_decision == "none" and not is_actionable else "unclear"
    mapped = COARSE_TO_V2_CLASS.get(key)
    if mapped in CLASSIFICATIONS_V2:
        return mapped
    if key in CLASSIFICATIONS_V2:
        return key
    return "unclear"


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

    decision = wr.get("decision") or "unclear"
    if decision not in WI_DECISIONS:
        raise ValidationError("Unsupported work_item decision: %s" % decision)

    actionability = data.get("actionability") or {}
    raw_classification = mu.get("classification")
    classification = normalize_classification_v2(
        raw_classification,
        wi_decision=decision,
        is_actionable=bool(actionability.get("is_actionable")),
    )
    if (
        classification == "unclear"
        and str(raw_classification or "").strip().lower()
        not in COARSE_TO_V2_CLASS
        and str(raw_classification or "").strip().lower() not in ("none", "")
    ):
        classification = raw_classification
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
        if classification == "noise":
            summary = "(no actionable content)"
        else:
            raise ValidationError("message_understanding.summary is required.")

    project_id = _opt_int(pr.get("project_id"), "project_resolution.project_id")
    work_item_id = _opt_int(wr.get("work_item_id"), "work_item_resolution.work_item_id")
    cand_projects = {int(i) for i in (project_candidate_ids or [])}
    cand_wis = {int(i) for i in (work_item_candidate_ids or [])}
    pr = dict(pr)
    wr = dict(wr)
    if project_id is not None and cand_projects and project_id not in cand_projects:
        raise ValidationError(
            "project_id %s is not in Odoo-supplied candidates." % project_id
        )
    if project_id is not None and not cand_projects:
        # Empty candidate list: strip baseline/dev_project leakage rather than accept.
        project_id = None
        pr["project_id"] = None
        pr["project_name"] = None
        pr["confidence"] = 0.0
        pr["resolution_status"] = "unresolved"
    if work_item_id is not None and cand_wis and work_item_id not in cand_wis:
        raise ValidationError(
            "work_item_id %s is not in Odoo-supplied candidates." % work_item_id
        )
    if work_item_id is not None and not cand_wis:
        work_item_id = None
        wr["work_item_id"] = None
        wr["work_item_title"] = None
        if decision == "existing":
            decision = "unclear"
            wr["decision"] = decision
    # Overconfidence guard for non-actionable labels without a resolved project.
    conf = _confidence(pr.get("confidence", 0.0))
    if (
        classification in ("noise", "information", "unclear")
        or not bool(data.get("safe_to_create_work"))
    ) and conf >= 0.8 and project_id is None:
        pr["confidence"] = 0.0
        if classification in ("noise", "information"):
            pr["project_name"] = None
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
        "schema_version": SCHEMA_VERSION_V2,
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


def _nonempty_str(value, field_name, required=True):
    text = str(value or "").strip()
    if required and not text:
        raise ValidationError("%s is required and must be non-empty." % field_name)
    return text


def _as_str_list(value, field_name, allow_empty=True, required_nonempty_items=False):
    if value is None:
        value = []
    if not isinstance(value, list):
        raise ValidationError("%s must be a list." % field_name)
    out = [str(x).strip() for x in value if str(x).strip()]
    if not allow_empty and not out:
        raise ValidationError("%s must be a non-empty list." % field_name)
    if required_nonempty_items and not out:
        raise ValidationError("%s must contain at least one non-empty item." % field_name)
    return out[:40]


def _validate_v3_item(item, index, batch_ids):
    if not isinstance(item, dict):
        raise ValidationError("items[%s] must be an object." % index)
    action = str(item.get("action") or "").strip()
    if action not in ACTIONS_V3:
        raise ValidationError(
            "items[%s].action unsupported: %s" % (index, action or "(empty)")
        )
    classification = str(item.get("classification") or "").strip()
    if classification not in CLASSIFICATIONS_V3:
        raise ValidationError(
            "items[%s].classification unsupported: %s"
            % (index, classification or "(empty)")
        )
    actionable = action not in NON_ACTIONABLE_V3
    title = str(item.get("title") or "").strip()
    description = str(item.get("description") or "").strip()
    current_behavior = str(
        item.get("current_behavior") or item.get("description") or ""
    ).strip()
    expected_behavior = str(
        item.get("expected_behavior") or item.get("outcome") or ""
    ).strip()
    acceptance = item.get("acceptance_criteria")
    test_requirements = item.get("test_requirements")
    source_ids = _as_int_list(
        item.get("source_message_ids") or [],
        "items[%s].source_message_ids" % index,
        batch_ids,
    )
    errors = []
    if actionable:
        if not title:
            errors.append("items[%s].title is required for actionable items" % index)
        if not description and not current_behavior:
            errors.append(
                "items[%s] needs description or current_behavior" % index
            )
        if not expected_behavior:
            errors.append(
                "items[%s] needs expected_behavior or outcome" % index
            )
        if not source_ids:
            errors.append(
                "items[%s].source_message_ids is required for actionable items" % index
            )
        try:
            ac_list = _as_str_list(
                acceptance,
                "items[%s].acceptance_criteria" % index,
                allow_empty=False,
                required_nonempty_items=True,
            )
        except ValidationError as err:
            errors.append(str(err))
            ac_list = []
        try:
            tr_list = _as_str_list(
                test_requirements if test_requirements is not None else [],
                "items[%s].test_requirements" % index,
                allow_empty=True,
            )
        except ValidationError as err:
            errors.append(str(err))
            tr_list = []
        try:
            conf = _confidence(item.get("confidence", 0.0))
        except ValidationError as err:
            errors.append(str(err))
            conf = 0.0
    else:
        ac_list = _as_str_list(
            acceptance if acceptance is not None else [],
            "items[%s].acceptance_criteria" % index,
            allow_empty=True,
        )
        tr_list = _as_str_list(
            test_requirements if test_requirements is not None else [],
            "items[%s].test_requirements" % index,
            allow_empty=True,
        )
        conf = (
            _confidence(item.get("confidence", 0.0))
            if item.get("confidence") is not None
            else 0.0
        )

    if errors:
        raise ValidationError("; ".join(errors))

    return {
        "title": title[:300] if title else None,
        "classification": classification,
        "action": action,
        "description": description[:8000] if description else None,
        "current_behavior": current_behavior[:4000] if current_behavior else None,
        "expected_behavior": expected_behavior[:4000] if expected_behavior else None,
        "acceptance_criteria": ac_list,
        "test_requirements": tr_list,
        "source_message_ids": source_ids,
        "confidence": conf,
        "outcome": str(item.get("outcome") or "").strip()[:4000] or None,
    }


def normalize_v3_to_legacy_fields(validated):
    """Map primary v3 item onto existing work_title / classification fields for UI."""
    items = list(validated.get("items") or validated.get("analysis_items") or [])
    primary = items[0] if items else {}
    action = primary.get("action") or "review_only"
    classification = primary.get("classification") or "unknown"
    class_v2 = V3_TO_V2_CLASS.get(classification, "unclear")
    recommended = V3_TO_V1_ACTION.get(action, "review")
    should_ignore = action == "ignore"
    contains_work = action in (
        "create_work",
        "create_multiple_work_items",
        "update_existing_work",
    )
    title = primary.get("title") or validated.get("conversation_summary")
    description_parts = []
    if primary.get("description"):
        description_parts.append(primary["description"])
    if primary.get("current_behavior"):
        description_parts.append("Current: %s" % primary["current_behavior"])
    if primary.get("expected_behavior"):
        description_parts.append("Expected: %s" % primary["expected_behavior"])
    if primary.get("acceptance_criteria"):
        description_parts.append(
            "Acceptance:\n- %s" % "\n- ".join(primary["acceptance_criteria"])
        )
    work_description = "\n\n".join(description_parts) if description_parts else None
    if action == "update_existing_work":
        decision = "existing"
    elif action in ("create_work", "create_multiple_work_items"):
        decision = "new"
    elif should_ignore:
        decision = "none"
    else:
        decision = "unclear"

    all_source = []
    for item in items:
        all_source.extend(item.get("source_message_ids") or [])
    seen = set()
    source_ids = []
    for mid in all_source:
        if mid not in seen:
            seen.add(mid)
            source_ids.append(mid)

    return {
        "schema_version": SCHEMA_VERSION_V3,
        "summary": str(validated.get("conversation_summary") or "")[:2000],
        "classification": V2_TO_V1_CLASS.get(class_v2, "issue"),
        "classification_v2": class_v2,
        "classification_v3": classification,
        "should_ignore": should_ignore,
        "ignore_reason": ("Classified as ignore" if should_ignore else None),
        "contains_work": contains_work and not should_ignore,
        "work_title": (str(title).strip()[:300] if title else None),
        "work_description": (
            str(work_description).strip()[:8000] if work_description else None
        ),
        "priority": "2",
        "project_reference": None,
        "participants": [],
        "source_message_ids": source_ids,
        "noise_message_ids": source_ids if should_ignore else [],
        "work_message_ids": source_ids if contains_work else [],
        "confidence": float(primary.get("confidence") or 0.0),
        "requires_human_review": bool(validated.get("requires_human_review", True)),
        "recommended_action": recommended,
        "missing_information": [],
        "project_resolution": {},
        "work_item_resolution": {"decision": decision},
        "analysis_detail": {
            "acceptance_criteria": primary.get("acceptance_criteria") or [],
            "test_requirements": primary.get("test_requirements") or [],
            "current_behavior": primary.get("current_behavior"),
            "expected_behavior": primary.get("expected_behavior"),
        },
        "evidence_used": [],
        "safe_to_create_work": action in ("create_work", "create_multiple_work_items"),
        "safe_to_attach_to_existing_work": action == "update_existing_work",
        "resolved_project_id": validated.get("resolved_project_id"),
        "resolved_work_item_id": validated.get("resolved_work_item_id"),
        "requires_project_confirmation": bool(
            validated.get("requires_project_confirmation", True)
        ),
        "contains_multiple_tasks": bool(
            validated.get("contains_multiple_tasks") or len(items) > 1
        ),
        "language": validated.get("language") or "mixed",
        "analysis_items": items,
        "action_v3": action,
    }


def _validate_v3(data, batch_ids, project_candidate_ids=None, work_item_candidate_ids=None):
    required = {"project", "conversation_summary", "items", "requires_human_review"}
    missing = required - set(data)
    if missing:
        raise ValidationError(
            "AI v3 response missing keys: %s" % ", ".join(sorted(missing))
        )
    items_raw = data.get("items")
    if not isinstance(items_raw, list):
        raise ValidationError("items must be a list.")
    if not items_raw:
        raise ValidationError("items must contain at least one item.")

    validated_items = [
        _validate_v3_item(item, idx, batch_ids) for idx, item in enumerate(items_raw)
    ]
    contains_multiple_tasks = len(validated_items) > 1

    project = data.get("project")
    if isinstance(project, dict):
        project_name = str(
            project.get("name") or project.get("code") or project.get("id") or ""
        ).strip()
        project_id = _opt_int(project.get("id") or project.get("project_id"), "project.id")
    else:
        project_name = str(project or "").strip()
        project_id = None
    cand_projects = {int(i) for i in (project_candidate_ids or [])}
    if project_id is not None and cand_projects and project_id not in cand_projects:
        raise ValidationError(
            "project.id %s is not in Odoo-supplied candidates." % project_id
        )

    summary = _nonempty_str(data.get("conversation_summary"), "conversation_summary")
    primary = normalize_v3_to_legacy_fields(
        {
            "schema_version": SCHEMA_VERSION_V3,
            "project": project,
            "conversation_summary": summary,
            "items": validated_items,
            "requires_human_review": bool(data.get("requires_human_review", True)),
            "contains_multiple_tasks": contains_multiple_tasks,
            "resolved_project_id": project_id,
        }
    )
    cand_wis = {int(i) for i in (work_item_candidate_ids or [])}
    wi_id = primary.get("resolved_work_item_id")
    if wi_id is not None and cand_wis and wi_id not in cand_wis:
        raise ValidationError(
            "work_item_id %s is not in Odoo-supplied candidates." % wi_id
        )

    primary["schema_version"] = SCHEMA_VERSION_V3
    primary["analysis_items"] = validated_items
    primary["contains_multiple_tasks"] = contains_multiple_tasks
    primary["requires_human_review"] = bool(data.get("requires_human_review", True))
    primary["project_name"] = project_name or None
    primary["resolved_project_id"] = project_id
    primary["validation_state"] = "valid"
    return primary


def validate_actionable_acceptance(validated):
    """Reject empty acceptance_criteria before approve_create_work (schema v3)."""
    if not isinstance(validated, dict):
        raise ValidationError("Validated analysis payload is required.")
    items = validated.get("analysis_items") or validated.get("items") or []
    schema = str(validated.get("schema_version") or "")
    if not items and schema != SCHEMA_VERSION_V3:
        # Legacy v1/v2 create path — do not block historical / fixture approvals
        return True
    if items:
        errors = []
        for idx, item in enumerate(items):
            action = item.get("action")
            if action in NON_ACTIONABLE_V3:
                continue
            ac = item.get("acceptance_criteria") or []
            if not isinstance(ac, list) or not [x for x in ac if str(x).strip()]:
                errors.append(
                    "items[%s] actionable action %s requires non-empty acceptance_criteria"
                    % (idx, action)
                )
        if errors:
            raise ValidationError("; ".join(errors))
        return True
    detail = validated.get("analysis_detail") or {}
    ac = detail.get("acceptance_criteria") or []
    if validated.get("contains_work") and validated.get("recommended_action") == "create_work":
        if not isinstance(ac, list) or not [x for x in ac if str(x).strip()]:
            raise ValidationError(
                "acceptance_criteria must be a non-empty list before creating work."
            )
    return True


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
    if version == SCHEMA_VERSION_V2:
        return _validate_v2(
            data,
            batch_ids,
            project_candidate_ids=project_candidate_ids,
            work_item_candidate_ids=work_item_candidate_ids,
        )
    if version == SCHEMA_VERSION_V3 or version == SCHEMA_VERSION:
        return _validate_v3(
            data,
            batch_ids,
            project_candidate_ids=project_candidate_ids,
            work_item_candidate_ids=work_item_candidate_ids,
        )
    raise ValidationError(
        "Unsupported schema_version %r (expected %s, %s, or %s)."
        % (version, SCHEMA_VERSION_V1, SCHEMA_VERSION_V2, SCHEMA_VERSION_V3)
    )


def safe_json_dumps(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2)
