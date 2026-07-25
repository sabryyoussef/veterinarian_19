#!/usr/bin/env python3
"""Pull whitelist group history from Evolution into Hub and admit into Work Inbox.

Run via Odoo shell (superuser) on pet_spot_elsahel_test only:

  /home/sabry/odoo_base/base_odoo_19/venv19/bin/python3 \\
    /home/sabry/odoo_base/base_odoo_19/odoo19/odoo19/odoo-bin shell \\
    -c /home/sabry/odoo_base/base_odoo_19/config/projects/pet_spot_elsahel_test.conf \\
    -d pet_spot_elsahel_test --http-port=18028 --gevent-port=18072 \\
    < admit_whitelist_work_inbox.py
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

# Odoo shell injects `env`
env  # noqa: F821 — provided by odoo-bin shell

WHITELIST = [
    ("120363408076611149@g.us", "Torz Trading - Qatar"),
    ("120363408418840478@g.us", "انهاء مشروع ASTA"),
    ("120363408457090778@g.us", "Bright&I zone (Odoo ERP)"),
    ("120363409667117343@g.us", "Izone - Internal BIS"),
    ("120363409479957889@g.us", "Alzaeem Medical project - internal BIS"),
    ("120363411424964076@g.us", "Testopenclow"),
    ("120363422104853335@g.us", "Dev Needed"),
    ("120363404024033208@g.us", "Cycle X"),
    ("120363427125783045@g.us", "AZone - WorldPosta"),
    ("120363428056737368@g.us", "Asta development"),
    ("120363409395291215@g.us", "Pet spot sahel branch"),
    ("120363427581631722@g.us", "مهمات مفتوحة لاستكمال فرع الساحل petspot"),
]

# Recent window admitted into Inbox as New (history stays loadable via context).
ADMIT_RECENT_PER_GROUP = 80
# Max Evolution messages to scan/import per group (oldest→newest within window).
SCAN_LIMIT_PER_GROUP = 500
EVOLUTION_BASE = "http://127.0.0.1:8080"


def _load_evo_env():
    data = {}
    for path in (
        Path("/home/sabry/infra/chatwoot-evolution-bridge/.env"),
        Path("/home/sabry/infra/evolution-api/.env"),
    ):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            data.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    return data


def _parse_messages(payload):
    messages = payload
    if isinstance(payload, dict):
        messages = (
            payload.get("messages")
            or payload.get("response")
            or payload.get("data")
            or payload.get("records")
            or []
        )
    if isinstance(messages, dict):
        messages = messages.get("records") or messages.get("messages") or []
    return messages if isinstance(messages, list) else []


def _extract_text(item):
    msg = item.get("message") or {}
    if not isinstance(msg, dict):
        return ""
    return (
        msg.get("conversation")
        or (msg.get("extendedTextMessage") or {}).get("text")
        or (msg.get("imageMessage") or {}).get("caption")
        or (msg.get("videoMessage") or {}).get("caption")
        or (msg.get("documentMessage") or {}).get("fileName")
        or (msg.get("documentMessage") or {}).get("title")
        or ""
    )


def _media_placeholder(item):
    mtype = str(item.get("messageType") or "")
    mapping = {
        "imageMessage": "[image]",
        "audioMessage": "[audio]",
        "videoMessage": "[video]",
        "documentMessage": "[document]",
        "stickerMessage": "[sticker]",
        "reactionMessage": "[reaction]",
    }
    return mapping.get(mtype, "")


def _ts_to_odoo(value):
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return False
    if raw > 10_000_000_000:
        raw = raw // 1000
    return datetime.fromtimestamp(raw, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _fetch_group_messages(base, instance, api_key, group_jid, scan_limit):
    url = f"{base}/chat/findMessages/{quote(instance, safe='')}"
    page_size = min(int(scan_limit), 100)
    page = 1
    out = []
    while len(out) < scan_limit:
        body = {
            "where": {"key": {"remoteJid": group_jid}},
            "page": page,
            "offset": page_size,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers={"apikey": api_key, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            batch = _parse_messages(json.loads(resp.read().decode()))
        if not batch:
            break
        out.extend(batch)
        if len(batch) < page_size:
            break
        page += 1
    out = out[:scan_limit]

    def sort_key(item):
        try:
            return int(item.get("messageTimestamp") or item.get("timestamp") or 0)
        except (TypeError, ValueError):
            return 0

    out.sort(key=sort_key)
    return out


def main():
    evo = _load_evo_env()
    instance = evo.get("EVOLUTION_INSTANCE_NAME") or "sabry min"
    api_key = evo.get("EVOLUTION_API_KEY") or ""
    if not api_key:
        raise SystemExit("EVOLUTION_API_KEY missing")

    # Shell uid is often OdooBot (no Dev Hub groups). Use admin for triage ACLs.
    admin = env["res.users"].sudo().search([("login", "=", "admin")], limit=1)  # noqa: F821
    if not admin:
        raise SystemExit("admin user not found")
    Message = env["whatsapp.message"].sudo()  # noqa: F821
    TriageMessage = env["whatsapp.message"].with_user(admin)  # noqa: F821
    Source = env["dev.whatsapp.source"].sudo()  # noqa: F821

    # Mapping only — sources already synced; avoid Hub group write side-effects.
    Source._apply_p0_mapping_corrections()
    env.cr.commit()  # noqa: F821

    report = []
    for group_jid, group_name in WHITELIST:
        source = Source.search([("group_jid", "=", group_jid)], limit=1)
        try:
            evo_msgs = _fetch_group_messages(
                EVOLUTION_BASE, instance, api_key, group_jid, SCAN_LIMIT_PER_GROUP
            )
        except urllib.error.HTTPError as exc:
            report.append(
                {
                    "group_jid": group_jid,
                    "name": group_name,
                    "error": f"evolution_http_{exc.code}",
                }
            )
            continue

        created = 0
        duplicates = 0
        skipped = 0
        for item in evo_msgs:
            key = item.get("key") or {}
            evo_id = str(key.get("id") or item.get("id") or "").strip()
            if not evo_id:
                skipped += 1
                continue
            text = (_extract_text(item) or "").strip()
            if not text:
                text = _media_placeholder(item)
            if not text:
                text = "[empty]"
            sender = (
                key.get("participantAlt")
                or key.get("participant")
                or key.get("remoteJid")
                or ""
            )
            direction = "out" if key.get("fromMe") else "in"
            payload = {
                "group_jid": group_jid,
                "group_name": group_name,
                "evolution_message_id": evo_id,
                "evolution_instance": instance,
                "instance_reference": instance,
                "text": text,
                "body": text,
                "allow_empty": True,
                "sender_jid": sender,
                "sender_name": item.get("pushName") or False,
                "message_timestamp": _ts_to_odoo(item.get("messageTimestamp")),
                "chatwoot_inbox_id": (source.chatwoot_inbox_id if source else 2) or 2,
                "raw_message_type": item.get("messageType") or False,
            }
            result = Message.service_ingest_normalized(payload)
            if result.get("duplicate") or result.get("reason") == "duplicate_message":
                duplicates += 1
            elif result.get("skipped"):
                skipped += 1
            elif result.get("message_id"):
                created += 1
                msg = Message.browse(result["message_id"])
                if msg.exists() and direction == "out" and msg.direction != "out":
                    msg.with_context(whatsapp_hub_mirroring=True).write(
                        {"direction": "out", "state": "sent"}
                    )

        env.cr.commit()  # noqa: F821

        # Admit recent untriaged history into Work Inbox as New.
        # Skip messages under historical media review so concurrent backfill
        # rows cannot be mutated by operational admission.
        domain = [("group_jid", "=", group_jid), ("inbox_state", "=", "untriaged")]
        untriaged = Message.search(
            domain, order="message_timestamp desc, id desc", limit=ADMIT_RECENT_PER_GROUP
        )
        Media = env["dev.whatsapp.media"].sudo()  # noqa: F821
        protected_ids = set(
            Media.search(
                [
                    ("whatsapp_message_id", "in", untriaged.ids),
                    ("is_historical_review", "=", True),
                ]
            ).mapped("whatsapp_message_id").ids
        )
        admit_ids = [mid for mid in untriaged.ids if mid not in protected_ids]
        admitted = 0
        skipped_historical = len(protected_ids)
        if admit_ids:
            TriageMessage.browse(admit_ids).action_inbox_add()
            admitted = len(admit_ids)
            env.cr.commit()  # noqa: F821
        if protected_ids:
            TriageMessage.browse(list(protected_ids))._log_historical_skip(
                "admit_whitelist_work_inbox",
                "skipped during concurrent historical media review",
            )
            env.cr.commit()  # noqa: F821

        # If still no active inbox rows (all were already actioned), promote latest.
        active = Message.search_count(
            [("group_jid", "=", group_jid), ("inbox_state", "in", ["new", "pending"])]
        )
        promoted = 0
        if not active:
            latest = Message.search(
                [("group_jid", "=", group_jid)],
                order="message_timestamp desc, id desc",
                limit=1,
            )
            if latest and latest.inbox_state in ("actioned", "ignored"):
                TriageMessage.browse(latest.ids)._inbox_set_state(
                    "new", event_type="set_new"
                )
                promoted = 1
                env.cr.commit()  # noqa: F821

        hub_total = Message.search_count([("group_jid", "=", group_jid)])
        inbox_new = Message.search_count(
            [("group_jid", "=", group_jid), ("inbox_state", "=", "new")]
        )
        report.append(
            {
                "group_jid": group_jid,
                "name": group_name,
                "source_id": source.id if source else False,
                "evo_scanned": len(evo_msgs),
                "hub_created": created,
                "hub_duplicates": duplicates,
                "hub_skipped": skipped,
                "admitted_to_inbox": admitted,
                "skipped_historical_media": skipped_historical,
                "promoted_latest": promoted,
                "hub_total": hub_total,
                "inbox_new": inbox_new,
            }
        )
        print(json.dumps(report[-1], ensure_ascii=False), flush=True)

    print("---SUMMARY---", flush=True)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


main()
