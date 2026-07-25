# -*- coding: utf-8 -*-
"""WhatsApp media retrieval helpers (key reconstruction, MIME, limits)."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from typing import Any

# Conservative Phase-1 limits (bytes)
DEFAULT_SIZE_LIMITS = {
    "image": 15 * 1024 * 1024,
    "audio": 25 * 1024 * 1024,
    "video": 100 * 1024 * 1024,
    "document": 25 * 1024 * 1024,
    "sticker": 5 * 1024 * 1024,
    "unknown": 25 * 1024 * 1024,
}

ALLOWED_MIME_PREFIXES = {
    "image": ("image/",),
    "audio": ("audio/", "application/ogg"),
    "video": ("video/",),
    "document": (
        "application/pdf",
        "text/",
        "application/msword",
        "application/vnd.",
        "application/octet-stream",
    ),
    "sticker": ("image/",),
}

BLOCKED_MIME = (
    "application/zip",
    "application/x-msdownload",
    "application/x-executable",
    "application/x-dosexec",
    "application/java-archive",
)


def reconstruct_evolution_key(message) -> dict[str, Any]:
    """Build Evolution getBase64 message key from a whatsapp.message record."""
    direction = (getattr(message, "direction", None) or "in").strip()
    from_me = direction == "out"
    remote = (
        (getattr(message, "group_jid", None) or "")
        or (getattr(message, "remote_jid", None) or "")
    ).strip()
    sender = (getattr(message, "sender_jid", None) or "").strip()
    evo_id = (getattr(message, "evolution_message_id", None) or "").strip()
    key: dict[str, Any] = {
        "remoteJid": remote,
        "id": evo_id,
        "fromMe": bool(from_me),
    }
    if remote.endswith("@g.us") and sender and not from_me:
        key["participant"] = sender
    return key


def media_type_from_message(message) -> str:
    kind = (getattr(message, "media_kind", None) or "unknown").strip()
    if kind in DEFAULT_SIZE_LIMITS:
        return kind
    return "unknown"


def sniff_mime(data: bytes) -> str:
    if not data:
        return "application/octet-stream"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) >= 8 and data[4:8] == b"ftyp":
        return "video/mp4"
    if data[:4] == b"OggS":
        return "audio/ogg"
    if data[:3] == b"ID3" or (len(data) >= 2 and data[:2] == b"\xff\xfb"):
        return "audio/mpeg"
    if data[:4] == b"%PDF":
        return "application/pdf"
    if data[:2] == b"PK":
        return "application/zip"
    return "application/octet-stream"


def mime_family_ok(media_type: str, sniffed: str, reported: str = "") -> bool:
    sniffed = (sniffed or "").split(";")[0].strip().lower()
    reported = (reported or "").split(";")[0].strip().lower()
    if sniffed in BLOCKED_MIME or reported in BLOCKED_MIME:
        return False
    if media_type == "document":
        if sniffed in BLOCKED_MIME:
            return False
        # ZIP never accepted without explicit future security controls
        if sniffed == "application/zip":
            return False
        return True
    prefixes = ALLOWED_MIME_PREFIXES.get(media_type, ())
    if not prefixes:
        return sniffed not in BLOCKED_MIME
    if any(sniffed.startswith(p) or sniffed == p.rstrip("/") for p in prefixes):
        return True
    # audio/ogg edge
    if media_type == "audio" and sniffed in ("application/ogg", "video/ogg"):
        return True
    # material conflict: reported image but sniffed zip etc.
    if reported and any(reported.startswith(p) for p in prefixes):
        # allow if sniff failed but reported ok and not blocked
        if sniffed == "application/octet-stream":
            return True
    return False


def size_limit_for(media_type: str, icp_get=None) -> int:
    key = f"devhub_whatsapp.media_max_bytes_{media_type}"
    default = DEFAULT_SIZE_LIMITS.get(media_type, DEFAULT_SIZE_LIMITS["unknown"])
    if icp_get:
        raw = icp_get(key)
        if raw:
            try:
                return max(1024, int(raw))
            except (TypeError, ValueError):
                pass
    return default


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def classify_evolution_error(http_status: int | None, body: str = "") -> str:
    text = (body or "").lower()
    if http_status in (401, 403) or "unauthorized" in text:
        return "authentication_failed"
    if "failed to fetch stream" in text or "mmg.whatsapp.net" in text:
        return "expired"
    if http_status == 404 or "not found" in text or "no media" in text:
        return "unavailable"
    if "expir" in text:
        return "expired"
    if http_status and http_status >= 400 and ("key" in text or "message" in text):
        return "invalid_key"
    if http_status and http_status >= 400:
        return "unavailable"
    return "unknown_failure"


def safe_filename(name: str, mime: str, media_type: str) -> str:
    name = (name or "").strip().replace("\x00", "")
    name = re.sub(r"[^\w.\- ()\[\]]+", "_", name)[:180]
    if name and name not in (".", ".."):
        return name
    ext = mimetypes.guess_extension((mime or "").split(";")[0].strip()) or {
        "image": ".jpg",
        "audio": ".ogg",
        "video": ".mp4",
        "document": ".bin",
    }.get(media_type, ".bin")
    return f"whatsapp_{media_type}{ext}"


def idempotency_key(
    source_provider: str,
    source_instance: str,
    source_media_id: str,
    media_asset_index: int = 0,
) -> str:
    return "|".join(
        [
            (source_provider or "evolution").strip(),
            (source_instance or "").strip(),
            (source_media_id or "").strip(),
            str(int(media_asset_index or 0)),
        ]
    )


def key_json_dumps(key: dict) -> str:
    return json.dumps(key, sort_keys=True, separators=(",", ":"))
