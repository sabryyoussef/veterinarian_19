#!/usr/bin/env python3
"""Phase 0 read-only Evolution media recovery probe (Test DB identifiers only).

Does not persist media. Deletes temp files. Does not log API keys.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "media_phase0_results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CONF = Path("/home/sabry/odoo_base/base_odoo_19/config/projects/pet_spot_elsahel_test.conf")
N8N_ENV = Path("/home/sabry/infra/n8n/.env")
EVO_BASE = "http://127.0.0.1:8080"
RECENT_CUTOFF = "2026-07-01"  # recent vs older for reporting


def load_kv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def db_password() -> str:
    return load_kv(CONF).get("db_password", "odoo")


def psql(sql: str) -> list[dict]:
    env = os.environ.copy()
    env["PGPASSWORD"] = db_password()
    proc = subprocess.run(
        [
            "psql",
            "-h",
            "localhost",
            "-U",
            "odoo",
            "-d",
            "pet_spot_elsahel_test",
            "-v",
            "ON_ERROR_STOP=1",
            "-At",
            "-F",
            "\t",
            "-c",
            sql,
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[:500])
    rows = []
    # Expect header via separate query with column aliases matching SELECT order
    return proc.stdout.strip()


def psql_dicts(sql: str, cols: list[str]) -> list[dict]:
    raw = psql(sql)
    if not raw:
        return []
    out = []
    for line in raw.splitlines():
        parts = line.split("\t")
        row = {cols[i]: (parts[i] if i < len(parts) else "") for i in range(len(cols))}
        out.append(row)
    return out


def evo_key_from_row(row: dict, from_me: bool | None = None) -> dict:
    direction = (row.get("direction") or "in").strip()
    if from_me is None:
        from_me = direction == "out"
    remote = (row.get("group_jid") or row.get("remote_jid") or "").strip()
    sender = (row.get("sender_jid") or "").strip()
    key = {
        "remoteJid": remote,
        "id": (row.get("evolution_message_id") or "").strip(),
        "fromMe": bool(from_me),
    }
    # Group chats need participant for inbound messages
    if remote.endswith("@g.us") and sender and not from_me:
        key["participant"] = sender
    return key


def sniff_mime(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:4] == b"\x00\x00\x00\x18" or data[4:8] == b"ftyp":
        return "video/mp4"
    if data[:4] == b"OggS":
        return "audio/ogg"
    if data[:3] == b"ID3" or data[:2] == b"\xff\xfb":
        return "audio/mpeg"
    if data[:4] == b"%PDF":
        return "application/pdf"
    if data[:2] == b"PK":
        return "application/zip"
    return "application/octet-stream"


def classify(
    *,
    http_status: int | None,
    err_text: str,
    size: int,
    reported_mime: str,
    sniffed: str,
    media_kind: str,
) -> str:
    et = (err_text or "").lower()
    if http_status == 401 or http_status == 403 or "unauthorized" in et:
        return "authentication_failed"
    if http_status == 404 or "not found" in et or "no media" in et:
        return "expired" if "expir" in et else "unavailable"
    if "expir" in et or "media was not found" in et or "baileys" in et and "404" in et:
        return "expired"
    if http_status and http_status >= 400:
        if "key" in et or "message" in et and "not" in et:
            return "invalid_key"
        return "unknown_failure"
    if size <= 0:
        return "unavailable"
    # Thumbnail heuristic: very small jpeg/png for video/image claims
    if media_kind in ("image", "video") and size < 8_000 and sniffed.startswith("image/"):
        return "recovered_thumbnail_only"
    if media_kind == "audio" and sniffed.startswith("image/"):
        return "recovered_thumbnail_only"
    if media_kind == "video" and sniffed.startswith("image/") and size < 50_000:
        return "recovered_thumbnail_only"
    if sniffed == "application/octet-stream" and size < 64:
        return "corrupt"
    # MIME family conflict
    family = {
        "image": "image/",
        "audio": "audio/",
        "video": "video/",
        "document": "",
    }.get(media_kind, "")
    if family and sniffed != "application/octet-stream" and not sniffed.startswith(family):
        # ogg audio sometimes reported oddly — still accept if size healthy
        if media_kind == "audio" and sniffed in ("application/ogg", "video/ogg"):
            return "recovered_original"
        if media_kind == "video" and sniffed.startswith("video/"):
            return "recovered_original"
        if size > 50_000:
            return "recovered_original"  # trust size over sniff edge cases
        return "corrupt"
    return "recovered_original"


def call_get_base64(instance: str, key: dict, api_key: str, timeout: float = 90.0):
    encoded = urllib.parse.quote(instance, safe="")
    url = f"{EVO_BASE.rstrip('/')}/chat/getBase64FromMediaMessage/{encoded}"
    body = json.dumps({"message": {"key": key}, "convertToMp4": False}).encode()
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
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
        elapsed = round((time.monotonic() - t0) * 1000)
        payload = json.loads(raw.decode("utf-8", errors="replace"))
        return status, payload, elapsed, ""
    except urllib.error.HTTPError as e:
        elapsed = round((time.monotonic() - t0) * 1000)
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            err_body = str(e)
        return e.code, {}, elapsed, err_body
    except Exception as e:
        elapsed = round((time.monotonic() - t0) * 1000)
        return None, {}, elapsed, str(e)[:400]


def _fetch_stratum(stratum: str, where: str, order: str, limit: int) -> list[dict]:
    cols = [
        "id",
        "media_kind",
        "message_timestamp",
        "group_name",
        "direction",
        "group_jid",
        "remote_jid",
        "sender_jid",
        "evolution_message_id",
        "instance_reference",
        "has_refs",
        "has_thumb",
        "body",
        "age_bucket",
        "stratum",
    ]
    sql = f"""
SELECT m.id::text, m.media_kind, m.message_timestamp::text,
       COALESCE(g.name,'?'), m.direction, COALESCE(m.group_jid,''), COALESCE(m.remote_jid,''),
       COALESCE(m.sender_jid,''), m.evolution_message_id,
       COALESCE(m.instance_reference,'sabry min'),
       CASE WHEN COALESCE(m.attachment_references,'') <> '' THEN 't' ELSE 'f' END,
       CASE WHEN EXISTS (
         SELECT 1 FROM ir_attachment a
         WHERE a.res_model='whatsapp.message' AND a.res_id=m.id
       ) THEN 't' ELSE 'f' END,
       LEFT(COALESCE(m.body,''), 40),
       CASE WHEN m.message_timestamp::date >= DATE '{RECENT_CUTOFF}' THEN 'recent' ELSE 'older' END,
       '{stratum}'
FROM whatsapp_message m
LEFT JOIN whatsapp_group g ON g.id = m.group_id
WHERE m.evolution_message_id IS NOT NULL AND m.evolution_message_id <> ''
  AND ({where})
ORDER BY {order}
LIMIT {int(limit)};
"""
    return psql_dicts(sql, cols)


def select_sample() -> list[dict]:
    parts = [
        _fetch_stratum(
            "dn_image_recent",
            "g.name ILIKE '%Dev Needed%' AND m.media_kind='image' AND m.message_timestamp::date >= DATE '2026-07-01'",
            "m.message_timestamp DESC",
            4,
        ),
        _fetch_stratum(
            "dn_image_older",
            "g.name ILIKE '%Dev Needed%' AND m.media_kind='image' AND m.message_timestamp::date < DATE '2026-07-01'",
            "m.message_timestamp ASC",
            4,
        ),
        _fetch_stratum(
            "dn_audio_recent",
            "g.name ILIKE '%Dev Needed%' AND m.media_kind='audio' AND m.message_timestamp::date >= DATE '2026-07-01'",
            "m.message_timestamp DESC",
            4,
        ),
        _fetch_stratum(
            "dn_audio_older",
            "g.name ILIKE '%Dev Needed%' AND m.media_kind='audio' AND m.message_timestamp::date < DATE '2026-07-01'",
            "m.message_timestamp ASC",
            4,
        ),
        _fetch_stratum(
            "dn_video_recent",
            "g.name ILIKE '%Dev Needed%' AND m.media_kind='video' AND m.message_timestamp::date >= DATE '2026-07-01'",
            "m.message_timestamp DESC",
            3,
        ),
        _fetch_stratum(
            "dn_video_older",
            "g.name ILIKE '%Dev Needed%' AND m.media_kind='video' AND m.message_timestamp::date < DATE '2026-07-01'",
            "m.message_timestamp ASC",
            3,
        ),
        _fetch_stratum(
            "torz_image",
            "g.name ILIKE '%Torz%' AND m.media_kind='image'",
            "m.message_timestamp DESC",
            3,
        ),
        _fetch_stratum(
            "torz_audio",
            "g.name ILIKE '%Torz%' AND m.media_kind='audio'",
            "m.message_timestamp DESC",
            2,
        ),
        _fetch_stratum(
            "torz_video",
            "g.name ILIKE '%Torz%' AND m.media_kind='video'",
            "m.message_timestamp DESC",
            2,
        ),
        _fetch_stratum(
            "torz_document",
            "g.name ILIKE '%Torz%' AND m.media_kind='document'",
            "m.message_timestamp DESC",
            2,
        ),
        _fetch_stratum(
            "with_refs",
            "m.media_kind IN ('image','audio','video','document') AND COALESCE(m.attachment_references,'') <> ''",
            "m.message_timestamp DESC",
            3,
        ),
        _fetch_stratum(
            "with_thumb",
            "m.media_kind IN ('image','audio','video','document') AND EXISTS (SELECT 1 FROM ir_attachment a WHERE a.res_model='whatsapp.message' AND a.res_id=m.id)",
            "m.message_timestamp DESC",
            3,
        ),
    ]
    seen = set()
    uniq = []
    for chunk in parts:
        for r in chunk:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            uniq.append(r)
    return uniq


def redact(s: str) -> str:
    # strip anything that looks like the api key pattern if somehow present
    return re.sub(r"[a-f0-9]{32,}", "[REDACTED]", s or "")


def main():
    env = load_kv(N8N_ENV)
    api_key = env.get("EVOLUTION_API_KEY", "")
    if not api_key:
        raise SystemExit("EVOLUTION_API_KEY missing")

    sample = select_sample()
    print(f"sample_size={len(sample)}")

    results = []
    tmp_root = Path(tempfile.mkdtemp(prefix="wa_media_probe_"))
    try:
        for row in sample:
            instance = row.get("instance_reference") or "sabry min"
            key = evo_key_from_row(row, from_me=False)
            # Also try fromMe=True only if first fails with invalid_key-ish — recorded separately
            attempts = [("fromMe_false", key)]
            status, payload, elapsed_ms, err = call_get_base64(instance, key, api_key)
            used_key = key
            attempt_label = "fromMe_false"

            def _ok(st, pl):
                return bool(st) and 200 <= int(st) < 300 and bool(pl.get("base64") or pl.get("data"))

            if status and int(status) >= 400:
                key2 = dict(key)
                key2["fromMe"] = True
                # remove participant when fromMe
                key2.pop("participant", None)
                status2, payload2, elapsed2, err2 = call_get_base64(instance, key2, api_key)
                if _ok(status2, payload2):
                    status, payload, elapsed_ms, err = status2, payload2, elapsed2, err2
                    used_key, attempt_label = key2, "fromMe_true_fallback"
                else:
                    # keep original failure; note secondary
                    err = f"{err} | alt_fromMe_true={status2}:{redact(err2)[:120]}"

            mime = ""
            filename = ""
            size = 0
            checksum = ""
            sniffed = ""
            duration = None
            classification = "unknown_failure"
            b64 = ""

            if _ok(status, payload):
                b64 = payload.get("base64") or payload.get("data") or ""
                mime = str(payload.get("mimetype") or payload.get("mimeType") or "").split(";")[0]
                filename = str(payload.get("fileName") or payload.get("filename") or "")
                if isinstance(payload.get("seconds"), (int, float)):
                    duration = float(payload["seconds"])
                try:
                    data = base64.b64decode(b64, validate=False)
                except Exception:
                    data = b""
                    classification = "corrupt"
                    err = "base64_decode_failed"
                else:
                    size = len(data)
                    checksum = hashlib.sha256(data).hexdigest()
                    sniffed = sniff_mime(data)
                    # write temp then delete
                    tpath = tmp_root / f"{row['id']}_{checksum[:12]}.bin"
                    tpath.write_bytes(data)
                    classification = classify(
                        http_status=status,
                        err_text=err,
                        size=size,
                        reported_mime=mime,
                        sniffed=sniffed,
                        media_kind=row["media_kind"],
                    )
                    tpath.unlink(missing_ok=True)
                    del data
            else:
                classification = classify(
                    http_status=status,
                    err_text=err,
                    size=0,
                    reported_mime="",
                    sniffed="",
                    media_kind=row["media_kind"],
                )

            results.append(
                {
                    "message_id": int(row["id"]),
                    "media_kind": row["media_kind"],
                    "message_date": row["message_timestamp"],
                    "age_bucket": row["age_bucket"],
                    "source_group": row["group_name"],
                    "stratum": row["stratum"],
                    "direction": row["direction"],
                    "has_attachment_references": row["has_refs"] == "t",
                    "has_thumbnail_attachment": row["has_thumb"] == "t",
                    "body_preview": row["body"],
                    "instance": instance,
                    "reconstructed_key": used_key,
                    "attempt_label": attempt_label,
                    "http_status": status,
                    "evolution_ok": bool(status) and 200 <= int(status) < 300 and size > 0,
                    "mime_type_reported": mime,
                    "mime_type_sniffed": sniffed,
                    "filename": filename,
                    "decoded_byte_size": size,
                    "duration_seconds": duration,
                    "checksum_sha256": checksum,
                    "classification": classification,
                    "failure_reason": redact(err)[:300] if classification not in (
                        "recovered_original",
                        "recovered_thumbnail_only",
                    ) else "",
                    "execution_ms": elapsed_ms,
                }
            )
            print(
                f"{row['id']} {row['media_kind']} {row['age_bucket']} "
                f"{classification} size={size} http={status} ms={elapsed_ms}",
                flush=True,
            )
    finally:
        # ensure temp tree gone
        for p in tmp_root.glob("*"):
            p.unlink(missing_ok=True)
        tmp_root.rmdir()

    # Summaries
    def rate(subset):
        if not subset:
            return {"n": 0, "success": 0, "pct": None}
        ok = sum(
            1
            for r in subset
            if r["classification"] in ("recovered_original", "recovered_thumbnail_only")
        )
        # for exit criteria, original preferred; still report both
        orig = sum(1 for r in subset if r["classification"] == "recovered_original")
        return {
            "n": len(subset),
            "recovered_any": ok,
            "recovered_original": orig,
            "pct_any": round(100.0 * ok / len(subset), 1),
            "pct_original": round(100.0 * orig / len(subset), 1),
        }

    by_class: dict[str, int] = {}
    for r in results:
        by_class[r["classification"]] = by_class.get(r["classification"], 0) + 1

    recent = [r for r in results if r["age_bucket"] == "recent"]
    older = [r for r in results if r["age_bucket"] == "older"]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_size": len(results),
        "by_classification": by_class,
        "recent": rate(recent),
        "older": rate(older),
        "by_media_kind": {
            k: rate([r for r in results if r["media_kind"] == k])
            for k in ("image", "audio", "video", "document")
        },
        "kinds_recovered_original": sorted(
            {
                r["media_kind"]
                for r in results
                if r["classification"] == "recovered_original"
            }
        ),
        "note_fromMe": (
            "Hub has 0 outbound media rows; primary key uses fromMe=false "
            "with participant=sender_jid for @g.us. Fallback fromMe=true tried on HTTP errors."
        ),
        "credentials_in_output": False,
        "temp_dir_cleaned": True,
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_json = OUT_DIR / f"probe_{stamp}.json"
    out_json.write_text(json.dumps({"summary": summary, "results": results}, indent=2))
    # also latest symlink-like copy
    (OUT_DIR / "probe_latest.json").write_text(out_json.read_text())
    print(json.dumps(summary, indent=2))
    print(f"wrote {out_json}")


if __name__ == "__main__":
    main()
