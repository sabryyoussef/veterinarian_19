# -*- coding: utf-8 -*-
"""Evolution findMessages recovery + live upsert normalization for Hub ingest."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from urllib.parse import quote

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


def _parse_messages_list(payload):
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
        messages = (
            messages.get("records")
            or messages.get("messages")
            or messages.get("data")
            or []
        )
    return messages if isinstance(messages, list) else []


def _ts_to_odoo(value):
    if not value and value != 0:
        return False
    if isinstance(value, datetime):
        return fields.Datetime.to_string(value)
    if isinstance(value, str) and not value.isdigit():
        # Already ISO-ish
        try:
            return fields.Datetime.to_string(fields.Datetime.to_datetime(value))
        except Exception:
            return value[:19].replace("T", " ")
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return False
    if raw > 10_000_000_000:
        raw = raw // 1000
    return datetime.fromtimestamp(raw, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _extract_text(msg_data):
    msg = msg_data.get("message") or {}
    if not isinstance(msg, dict):
        return ""
    return (
        msg.get("conversation")
        or (msg.get("extendedTextMessage") or {}).get("text")
        or (msg.get("imageMessage") or {}).get("caption")
        or (msg.get("videoMessage") or {}).get("caption")
        or (msg.get("documentMessage") or {}).get("caption")
        or (msg.get("documentMessage") or {}).get("fileName")
        or (msg.get("documentMessage") or {}).get("title")
        or ""
    )


def _detect_media_kind(msg_data):
    msg = msg_data.get("message") or {}
    mtype = str(msg_data.get("messageType") or "")
    if not isinstance(msg, dict):
        msg = {}
    if mtype == "imageMessage" or msg.get("imageMessage"):
        return "image"
    if mtype == "videoMessage" or msg.get("videoMessage"):
        return "video"
    if mtype == "audioMessage" or msg.get("audioMessage"):
        return "audio"
    if mtype == "documentMessage" or msg.get("documentMessage"):
        return "document"
    if mtype == "stickerMessage" or msg.get("stickerMessage"):
        return "sticker"
    if mtype == "reactionMessage" or msg.get("reactionMessage"):
        return "reaction"
    return ""


class WhatsappEvolutionRecovery(models.AbstractModel):
    _name = "whatsapp.evolution.recovery"
    _description = "WhatsApp Evolution Recovery Helper"

    @api.model
    def normalize_evolution_upsert(self, msg_data, instance_name):
        """Normalize a live Evolution messages.upsert payload for Hub ingest."""
        if not isinstance(msg_data, dict):
            return False
        key = msg_data.get("key") or {}
        evo_id = str(key.get("id") or msg_data.get("id") or "").strip()
        if not evo_id:
            return False

        remote_jid = (
            key.get("remoteJid")
            or msg_data.get("remoteJid")
            or ""
        ).strip()
        from_me = bool(key.get("fromMe"))
        participant = (
            key.get("participantAlt")
            or key.get("participant")
            or msg_data.get("participant")
            or ""
        ).strip()
        sender_jid = participant or ("" if remote_jid.endswith("@g.us") else remote_jid)
        if from_me and not sender_jid:
            sender_jid = remote_jid

        text = (_extract_text(msg_data) or "").strip()
        media_kind = _detect_media_kind(msg_data)
        if not text:
            if media_kind:
                text = f"[{media_kind}]"
            else:
                text = "Content unavailable: encrypted or unsupported"

        group_jid = remote_jid if remote_jid.endswith("@g.us") else False
        ts = _ts_to_odoo(
            msg_data.get("messageTimestamp") or msg_data.get("timestamp")
        )

        payload = {
            "evolution_message_id": evo_id,
            "provider_message_id": evo_id,
            "provider": "evolution",
            "instance_reference": instance_name or False,
            "evolution_instance": instance_name or False,
            "sender_jid": sender_jid or False,
            "sender_name": msg_data.get("pushName") or False,
            "body": text,
            "text": text,
            "message_timestamp": ts or fields.Datetime.now(),
            "direction": "out" if from_me else "in",
            "allow_empty": True,
            "raw_message_type": msg_data.get("messageType") or False,
        }
        if group_jid:
            payload["group_jid"] = group_jid
            payload["group_name"] = msg_data.get("groupName") or group_jid
        else:
            # DM: contact peer is remote_jid
            payload["sender_jid"] = sender_jid or remote_jid
            if remote_jid:
                payload["remote_jid"] = remote_jid
        if media_kind:
            payload["media_type"] = media_kind
            payload["media_kind"] = media_kind
            payload["attachment_references"] = f"media_type={media_kind}"
        return payload

    @api.model
    def _config_looks_usable(self, cfg):
        url = (cfg or {}).get("url") or ""
        key = (cfg or {}).get("key") or ""
        instance = (cfg or {}).get("instance") or ""
        if not (url and key and instance):
            return False
        # Reject obviously broken UAT stubs like http://127.0.0.1:9
        if url.rstrip("/").endswith(":9") or url.rstrip("/").endswith(":9/"):
            return False
        return True

    @api.model
    def _resolve_config(self, conversation):
        Instance = self.env["whatsapp.instance"].sudo()
        candidates = []
        if conversation and conversation.instance_id:
            candidates.append(conversation.instance_id.get_config_dict())
        if conversation and conversation.instance_reference:
            inst = Instance.search(
                [("instance_name", "=", conversation.instance_reference)], limit=1
            )
            if inst:
                candidates.append(inst.get_config_dict())
        # Prefer a developer-purpose instance when recovering Dev groups
        purpose_cfg = Instance.get_config_for_purpose("developer")
        if purpose_cfg:
            candidates.append(purpose_cfg)
        candidates.append(Instance.get_default_config())
        for cfg in candidates:
            if self._config_looks_usable(cfg):
                return cfg
        # Last resort: return first candidate for clearer error messages
        return candidates[0] if candidates else {}

    @api.model
    def _fetch_find_messages(self, cfg, remote_jid, limit=100):
        import urllib.error
        import urllib.request

        base = (cfg.get("url") or "").rstrip("/")
        instance = cfg.get("instance") or ""
        instance_path = cfg.get("instance_path") or quote(instance, safe="")
        api_key = cfg.get("key") or ""
        if not base or not instance_path or not api_key:
            raise ValueError("Evolution instance is not configured for recovery.")
        if not remote_jid:
            raise ValueError("Conversation has no remote_jid for Evolution findMessages.")

        url = f"{base}/chat/findMessages/{instance_path}"
        body = json.dumps(
            {"where": {"key": {"remoteJid": remote_jid}}, "limit": int(limit) or 100},
            separators=(",", ":"),
        ).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "apikey": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            try:
                err = exc.read().decode("utf-8", errors="replace")[:400]
            except Exception:
                err = str(exc)
            raise ValueError(f"Evolution findMessages failed ({exc.code}): {err}") from exc
        return _parse_messages_list(payload)

    @api.model
    def _sort_oldest_first(self, messages):
        def sort_key(item):
            try:
                return int(
                    item.get("messageTimestamp") or item.get("timestamp") or 0
                )
            except (TypeError, ValueError):
                return 0

        return sorted(messages or [], key=sort_key)

    @api.model
    def _ingest_payload(self, payload):
        """Call Hub ingest as superuser (sudo bypasses ingest-service ACL)."""
        Message = self.env["whatsapp.message"].sudo()
        result = Message.service_ingest_normalized(payload)
        # Correct direction for fromMe recoveries (ingest hardcodes inbound).
        if (
            result.get("message_id")
            and not result.get("duplicate")
            and payload.get("direction") == "out"
        ):
            msg = Message.browse(result["message_id"])
            if msg.exists() and msg.direction != "out":
                msg.with_context(whatsapp_hub_mirroring=True).write(
                    {"direction": "out", "state": "sent", "delivery_state": "sent"}
                )
        return result

    @api.model
    def recover_conversation(self, conversation, limit=100, since_timestamp=None):
        """
        Pull Evolution findMessages for a conversation and ingest missing rows.

        Returns: {created, existing, errors, recovered_ids}
        """
        conversation.ensure_one()
        cfg = self._resolve_config(conversation)
        instance_name = cfg.get("instance") or conversation.instance_reference or ""
        remote_jid = (
            conversation.remote_jid
            or (conversation.group_id.jid if conversation.group_id else False)
            or False
        )
        created = 0
        existing = 0
        errors = []
        recovered_ids = []

        try:
            raw_messages = self._fetch_find_messages(
                cfg, remote_jid, limit=limit
            )
        except Exception as exc:
            _logger.exception(
                "whatsapp_hub evolution recovery fetch failed conversation=%s",
                conversation.id,
            )
            return {
                "created": 0,
                "existing": 0,
                "errors": [str(exc)],
                "recovered_ids": [],
            }

        messages = self._sort_oldest_first(raw_messages)
        since_dt = False
        if since_timestamp:
            try:
                since_dt = fields.Datetime.to_datetime(since_timestamp)
            except Exception:
                since_dt = False

        for msg_data in messages:
            try:
                payload = self.normalize_evolution_upsert(msg_data, instance_name)
                if not payload:
                    continue
                if since_dt and payload.get("message_timestamp"):
                    try:
                        msg_dt = fields.Datetime.to_datetime(
                            payload["message_timestamp"]
                        )
                        if msg_dt and msg_dt < since_dt:
                            continue
                    except Exception:
                        pass
                # Prefer conversation remote/group when normalizing DMs from fetch
                if conversation.group_id and conversation.group_id.jid:
                    payload.setdefault("group_jid", conversation.group_id.jid)
                    payload.setdefault("group_name", conversation.group_id.name)
                result = self._ingest_payload(payload)
                if result.get("duplicate") or result.get("reason") == "duplicate_message":
                    existing += 1
                    if result.get("message_id"):
                        recovered_ids.append(result["message_id"])
                elif result.get("skipped"):
                    continue
                elif result.get("message_id"):
                    created += 1
                    recovered_ids.append(result["message_id"])
                else:
                    errors.append(result.get("reason") or "unknown_ingest_result")
            except Exception as exc:
                errors.append(str(exc)[:500])
                _logger.warning(
                    "whatsapp_hub evolution recovery ingest error conversation=%s: %s",
                    conversation.id,
                    exc,
                )

        _logger.info(
            "whatsapp_hub evolution recovery conversation=%s created=%s existing=%s errors=%s",
            conversation.id,
            created,
            existing,
            len(errors),
        )
        return {
            "created": created,
            "existing": existing,
            "errors": errors,
            "recovered_ids": recovered_ids,
        }
