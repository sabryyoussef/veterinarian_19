# -*- coding: utf-8 -*-
"""Dev Needed media canary: enqueue exact message IDs (Test only).

Env:
  CANARY_MODE=select|enqueue|status|safety
  CANARY_MESSAGE_IDS=6184,6167,783,750,853
  CANARY_RUN_REF=wa-media-dn-canary-20260725
"""
import json
import os

from odoo import fields

from odoo.addons.devhub_whatsapp.models.dev_whatsapp_historical_guard import (
    CTX_NON_MUTATING,
)

START_AT = "2026-07-18 09:22:14"
END_AT = "2026-07-25 09:22:14"
SOURCE_ID = 9

mode = (os.environ.get("CANARY_MODE") or "select").strip()
run_ref = (os.environ.get("CANARY_RUN_REF") or "wa-media-dn-canary-20260725").strip()
raw_ids = [
    int(item)
    for item in (os.environ.get("CANARY_MESSAGE_IDS") or "").split(",")
    if item.strip()
]

manager = env["res.users"].search([("login", "=", "admin")], limit=1)
if not manager.has_group("devhub_core.group_dev_hub_manager"):
    manager = env["res.users"].search([], order="id").filtered(
        lambda user: user.has_group("devhub_core.group_dev_hub_manager")
    )[:1]
if not manager:
    raise RuntimeError("No Dev Hub manager is available.")

Backfill = env["dev.whatsapp.media.backfill"].with_user(manager)
Message = env["whatsapp.message"].sudo()
Media = env["dev.whatsapp.media"].sudo().with_context(**{CTX_NON_MUTATING: True})
Job = env["dev.whatsapp.media.job"].sudo().with_context(**{CTX_NON_MUTATING: True})
Source = env["dev.whatsapp.source"].sudo().browse(SOURCE_ID)


def _safety_for(ids):
    rows = []
    for mid in sorted(ids):
        msg = Message.browse(mid)
        works = ",".join(str(i) for i in sorted(msg.work_item_ids.ids))
        rows.append("%s:%s:%s" % (mid, msg.inbox_state or "", works))
    import hashlib

    return {
        "message_ids": sorted(ids),
        "rows": rows,
        "safety_hash": hashlib.md5("|".join(rows).encode()).hexdigest(),
        "work_item_count": env["dev.work.item"].sudo().search_count([]),
        "source": {
            "id": Source.id,
            "mapping": Source.project_mapping_state,
            "ai_triage": Source.ai_triage_enabled,
            "lane": Source.historical_review_lane,
            "require_human_confirm": Source.require_human_confirm,
        },
    }


def _select_rows(ids):
    dry = Backfill.dry_run(START_AT, END_AT, source_ids=[SOURCE_ID])
    by_id = {item["message_id"]: item for item in dry["selected"]}
    out = []
    for mid in ids:
        item = by_id.get(mid)
        msg = Message.browse(mid)
        if not item:
            out.append(
                {
                    "message_id": mid,
                    "eligible": False,
                    "reason": "not_in_dry_run_selected",
                    "media_kind": msg.media_kind,
                    "timestamp": fields.Datetime.to_string(msg.message_timestamp),
                    "inbox_state": msg.inbox_state,
                    "sender_jid": msg.sender_jid,
                    "body": (msg.body or "")[:80],
                }
            )
            continue
        out.append(
            {
                "message_id": mid,
                "eligible": True,
                "media_type": item["media_type"],
                "timestamp": item["message_timestamp"],
                "inbox_state": msg.inbox_state,
                "sender_jid": msg.sender_jid,
                "body": (msg.body or "")[:80],
                "existing_media_id": item.get("existing_media_id"),
            }
        )
    return out


if mode == "safety":
    print("CANARY_RESULT=" + json.dumps(_safety_for(raw_ids), ensure_ascii=False))
elif mode == "select":
    print(
        "CANARY_RESULT="
        + json.dumps(
            {"selected": _select_rows(raw_ids), "safety": _safety_for(raw_ids)},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
elif mode == "enqueue":
    if not raw_ids:
        raise RuntimeError("CANARY_MESSAGE_IDS required")
    selected = _select_rows(raw_ids)
    bad = [row for row in selected if not row.get("eligible")]
    if bad:
        raise RuntimeError("Ineligible messages: %s" % bad)
    enqueued = []
    for mid in raw_ids:
        message = Message.browse(mid)
        inbox_before = message.inbox_state
        work_before = tuple(message.work_item_ids.ids)
        media = Media._ensure_for_message(message, is_historical_review=True)
        job = Job._enqueue_download(media)
        message.invalidate_recordset(["inbox_state", "work_item_ids"])
        if message.inbox_state != inbox_before or tuple(message.work_item_ids.ids) != work_before:
            raise RuntimeError("Safety violation on message %s" % mid)
        enqueued.append(
            {
                "message_id": mid,
                "media_id": media.id,
                "job_id": job.id if job else None,
                "media_type": media.media_type,
                "run_ref": run_ref,
            }
        )
    env.cr.commit()
    print(
        "CANARY_RESULT="
        + json.dumps(
            {"enqueued": enqueued, "safety": _safety_for(raw_ids)},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
elif mode == "status":
    MediaS = env["dev.whatsapp.media"].sudo()
    rows = []
    for mid in raw_ids:
        media = MediaS.search([("whatsapp_message_id", "=", mid)], limit=1)
        jobs = env["dev.whatsapp.media.job"].sudo().search([("media_id", "=", media.id)])
        rows.append(
            {
                "message_id": mid,
                "media_id": media.id or None,
                "media_type": media.media_type or None,
                "retrieval_state": media.retrieval_state or None,
                "enrichment_state": media.enrichment_state or None,
                "attachment_id": media.attachment_id.id or None,
                "file_size": media.attachment_id.file_size if media.attachment_id else None,
                "ocr_len": len(media.image_extracted_text or ""),
                "ocr_lang": media.image_ocr_language or None,
                "ocr_conf": media.image_ocr_confidence,
                "visible_error": (media.image_visible_error or "")[:120] or None,
                "tx_len": len(media.audio_transcript or ""),
                "audio_lang": media.audio_language or None,
                "provider": media.enrichment_provider or None,
                "model": media.enrichment_model or None,
                "manual_review": media.needs_manual_review,
                "jobs": [
                    {
                        "id": j.id,
                        "kind": j.kind,
                        "state": j.state,
                        "attempt": j.attempt_count,
                        "error": j.last_error_code or None,
                        "duration_ms": j.duration_ms,
                    }
                    for j in jobs
                ],
            }
        )
    print(
        "CANARY_RESULT="
        + json.dumps(
            {"status": rows, "safety": _safety_for(raw_ids)},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
else:
    raise RuntimeError("Unknown CANARY_MODE")
