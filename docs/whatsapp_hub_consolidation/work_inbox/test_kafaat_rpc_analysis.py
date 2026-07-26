#!/usr/bin/env python3
"""Ingest Ahmed Kafaat RPC thread into Hub and enqueue historical evaluation.

Run:
  /home/sabry/odoo_base/base_odoo_19/venv19/bin/python3 \\
    /home/sabry/odoo_base/base_odoo_19/odoo19/odoo19/odoo-bin shell \\
    -c /home/sabry/odoo_base/base_odoo_19/config/projects/pet_spot_elsahel_test.conf \\
    -d pet_spot_elsahel_test --http-port=18028 --gevent-port=18072 \\
    < test_kafaat_rpc_analysis.py
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

env  # noqa: F821

GROUP_JID = "120363422104853335@g.us"
GROUP_NAME = "Dev Needed"
SOURCE_ID = 9
SAMPLE_ID = "kafaat-rpc-20260725"
EVOLUTION_BASE = "http://127.0.0.1:8080"
INSTANCE = "sabry min"
# Ahmed's RPC + notes window (UTC approx matching Jul 25 14:47–18:30 Cairo+3 → 11:47–15:30 UTC)
# Evolution timestamps are unix seconds.


def _load_evo_key():
    for path in (
        Path("/home/sabry/infra/chatwoot-evolution-bridge/.env"),
        Path("/home/sabry/infra/evolution-api/.env"),
    ):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("AUTHENTICATION_API_KEY=") or line.startswith(
                "EVOLUTION_API_KEY="
            ):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("Evolution API key not found")


def _ts_to_odoo(ts):
    if ts is None:
        return False
    if isinstance(ts, dict):
        # baileys Long
        low = ts.get("low")
        high = ts.get("high") or 0
        if low is None:
            return False
        ts = int(low) + (int(high) << 32)
        if ts > 10**12:
            ts //= 1000
    try:
        ts = int(ts)
    except Exception:
        return False
    if ts > 10**12:
        ts //= 1000
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _extract_text(item):
    msg = item.get("message") or {}
    if not isinstance(msg, dict):
        return ""
    if msg.get("conversation"):
        return str(msg["conversation"])
    ext = msg.get("extendedTextMessage") or {}
    if ext.get("text"):
        return str(ext["text"])
    return ""


def _want(item):
    text = _extract_text(item)
    if not text:
        return False
    keys = (
        "RPC_ERROR",
        "edafaa_student_profile",
        "batch_intake",
        "html4css1",
        "كفاءات",
        "قسيمة",
        "Batch Intake",
        "motakamel",
        "student_enrollment_portal",
        "ال 2 ايرور",
        "رقم 6",
        "رقم 3 قسيمة",
    )
    return any(k in text for k in keys)


def fetch_evo(limit=80):
    key = _load_evo_key()
    url = (
        f"{EVOLUTION_BASE}/chat/findMessages/{quote(INSTANCE)}"
        f"?remoteJid={quote(GROUP_JID)}&limit={limit}"
    )
    # Evolution often uses POST findMessages
    req = urllib.request.Request(
        f"{EVOLUTION_BASE}/chat/findMessages/{quote(INSTANCE)}",
        data=json.dumps(
            {"where": {"key": {"remoteJid": GROUP_JID}}, "limit": limit}
        ).encode(),
        headers={
            "Content-Type": "application/json",
            "apikey": key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode())
    except Exception:
        # fallback GET getMessages style used by MCP
        req2 = urllib.request.Request(
            f"{EVOLUTION_BASE}/chat/findMessages/{quote(INSTANCE)}",
            data=json.dumps({"number": GROUP_JID, "limit": limit}).encode(),
            headers={"Content-Type": "application/json", "apikey": key},
            method="POST",
        )
        with urllib.request.urlopen(req2, timeout=60) as resp:
            payload = json.loads(resp.read().decode())
    messages = payload
    if isinstance(payload, dict):
        messages = (
            payload.get("messages")
            or payload.get("records")
            or (payload.get("data") or {}).get("records")
            or payload.get("response")
            or []
        )
        if isinstance(messages, dict):
            messages = messages.get("records") or messages.get("messages") or []
    return messages if isinstance(messages, list) else []


def main():
    Message = env["whatsapp.message"]  # noqa: F821
    Analysis = env["dev.whatsapp.analysis"]  # noqa: F821
    source = env["dev.whatsapp.source"].browse(SOURCE_ID)  # noqa: F821

    evo_msgs = fetch_evo(120)
    selected = [m for m in evo_msgs if _want(m)]
    # keep chronological, max 12
    selected = sorted(
        selected,
        key=lambda m: int(m.get("messageTimestamp") or 0),
    )[:12]
    print(
        json.dumps(
            {"evo_total": len(evo_msgs), "selected": len(selected)},
            ensure_ascii=False,
        ),
        flush=True,
    )

    created_ids = []
    for item in selected:
        key = item.get("key") or {}
        evo_id = key.get("id") or item.get("id")
        text = _extract_text(item)
        sender = (
            key.get("participantAlt")
            or key.get("participant")
            or key.get("remoteJid")
            or ""
        )
        payload = {
            "group_jid": GROUP_JID,
            "group_name": GROUP_NAME,
            "evolution_message_id": evo_id,
            "evolution_instance": INSTANCE,
            "instance_reference": INSTANCE,
            "text": text,
            "body": text,
            "allow_empty": True,
            "sender_jid": sender,
            "sender_name": item.get("pushName") or False,
            "message_timestamp": _ts_to_odoo(item.get("messageTimestamp")),
            "chatwoot_inbox_id": 2,
            "raw_message_type": item.get("messageType") or False,
        }
        result = Message.service_ingest_normalized(payload)
        mid = result.get("message_id")
        if mid:
            created_ids.append(int(mid))
            msg = Message.browse(mid)
            if msg.inbox_state == "untriaged":
                msg.action_inbox_add()
        print(
            json.dumps(
                {
                    "evo_id": evo_id,
                    "result": {k: result.get(k) for k in ("message_id", "duplicate", "skipped", "reason")},
                    "preview": (text or "")[:100],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    env.cr.commit()  # noqa: F821

    # Prefer freshly touched message ids; fall back to body search in hub
    if not created_ids:
        created_ids = Message.search(
            [
                ("group_jid", "=", GROUP_JID),
                "|",
                "|",
                ("body", "ilike", "RPC_ERROR"),
                ("body", "ilike", "edafaa_student_profile"),
                ("body", "ilike", "batch_intake.view_batch_intake_form"),
            ],
            order="message_timestamp asc, id asc",
            limit=12,
        ).ids

    # Deduplicate preserve order
    seen = set()
    msg_ids = []
    for i in created_ids:
        if i not in seen:
            seen.add(i)
            msg_ids.append(i)
    msg_ids = msg_ids[:12]

    analysis = Analysis.action_enqueue_historical_quality_evaluation(
        SOURCE_ID, msg_ids, SAMPLE_ID, force_reanalyse=True
    )
    env.cr.commit()  # noqa: F821
    jobs = analysis.job_ids
    print(
        json.dumps(
            {
                "analysis_id": analysis.id,
                "state": analysis.state,
                "prompt_version": analysis.prompt_version,
                "message_ids": msg_ids,
                "job_ids": jobs.ids,
                "job_states": jobs.mapped("state"),
                "payload_len": len(jobs[:1].payload_json or "") if jobs else 0,
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )


main()
