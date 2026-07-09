#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Auto-publish due PetSpot campaign posts DIRECTLY to Facebook (no Odoo Online).

Reads config from ir_config_parameter:
  social_media_connector.direct_publish_enabled  (True/False)
  social_media_connector.direct_page_id          (Facebook page id)
  social_media_connector.direct_page_token        (Page access token)

Publishes social.media.post rows with state='ready' whose scheduled_date <= now (UTC),
oldest first, marks them pushed/posted with the returned facebook_post_id.
Designed to run every ~10 min via a systemd --user timer.

Usage:
  direct_publish_due.py [--dry-run] [--limit N]
"""
import argparse
import json
import ssl
import sys
import uuid
import urllib.request
import urllib.error
from datetime import datetime, timezone

import psycopg2

DB_NAME = "pet_spot_elsahel"
DB_HOST = "localhost"
DB_USER = "odoo"
CONF = "/home/sabry/odoo_base/base_odoo_19/config/projects/pet_spot_elsahel.conf"
FILESTORE = "/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/.filestore/filestore/pet_spot_elsahel"
GRAPH_VER = "v21.0"
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def db_password():
    with open(CONF) as fh:
        for line in fh:
            if line.strip().startswith("db_password"):
                return line.split("=", 1)[1].strip()
    raise SystemExit("db_password not found in conf")


def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


def graph_post_photo(page_id, token, caption, img_bytes, fname, mimetype):
    ctx = ssl.create_default_context()
    boundary = uuid.uuid4().hex
    url = f"https://graph.facebook.com/{GRAPH_VER}/{page_id}/photos"

    def field(name, value):
        return (f"--{boundary}\r\nContent-Disposition: form-data; "
                f"name=\"{name}\"\r\n\r\n{value}\r\n").encode("utf-8")

    body = b""
    body += field("access_token", token)
    body += field("caption", caption)
    body += field("published", "true")
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"source\"; "
             f"filename=\"{fname}\"\r\nContent-Type: {mimetype or 'image/png'}\r\n\r\n").encode("utf-8")
    body += img_bytes + b"\r\n"
    body += f"--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
        return json.loads(resp.read().decode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=5,
                    help="Max posts to publish per run (rate safety).")
    args = ap.parse_args()

    conn = psycopg2.connect(host=DB_HOST, user=DB_USER, password=db_password(), dbname=DB_NAME)
    conn.autocommit = False
    cur = conn.cursor()

    def cfg(key, default=None):
        cur.execute("SELECT value FROM ir_config_parameter WHERE key=%s", (key,))
        row = cur.fetchone()
        return row[0] if row else default

    if (cfg("social_media_connector.direct_publish_enabled", "False") or "False") != "True":
        log("direct_publish disabled; exiting.")
        return
    page_id = cfg("social_media_connector.direct_page_id")
    token = cfg("social_media_connector.direct_page_token")
    if not page_id or not token:
        log("missing page id/token; exiting.")
        return

    cur.execute("""
        SELECT id, message FROM social_media_post
        WHERE state='ready' AND scheduled_date IS NOT NULL
          AND scheduled_date <= (now() AT TIME ZONE 'UTC')
        ORDER BY scheduled_date, id
        LIMIT %s""", (args.limit,))
    due = cur.fetchall()
    log(f"due posts: {len(due)} (limit {args.limit})")
    if not due:
        return

    published = 0
    for post_id, message in due:
        cur.execute("""
            SELECT a.store_fname, a.mimetype, a.name, a.db_datas
            FROM social_media_post_attachment_rel r
            JOIN ir_attachment a ON a.id=r.attachment_id
            WHERE r.post_id=%s LIMIT 1""", (post_id,))
        row = cur.fetchone()
        if not row:
            log(f"post {post_id}: no image, marking failed")
            cur.execute("UPDATE social_media_post SET state='failed', failure_reason=%s WHERE id=%s",
                        ("No image attached", post_id))
            conn.commit()
            continue
        store_fname, mimetype, fname, db_datas = row
        try:
            if db_datas:
                import base64
                img_bytes = base64.b64decode(db_datas)
            else:
                with open(f"{FILESTORE}/{store_fname}", "rb") as fh:
                    img_bytes = fh.read()
        except Exception as exc:  # noqa: BLE001
            log(f"post {post_id}: image read error {exc}; marking failed")
            cur.execute("UPDATE social_media_post SET state='failed', failure_reason=%s WHERE id=%s",
                        (f"Image read: {exc}", post_id))
            conn.commit()
            continue

        if len(img_bytes) > MAX_IMAGE_BYTES:
            log(f"post {post_id}: image too large ({len(img_bytes)}); marking failed")
            cur.execute("UPDATE social_media_post SET state='failed', failure_reason=%s WHERE id=%s",
                        ("Image > 5MB", post_id))
            conn.commit()
            continue

        if args.dry_run:
            log(f"[dry-run] would publish post {post_id} ({fname}, {len(img_bytes)}B)")
            continue

        try:
            result = graph_post_photo(page_id, token, message or "", img_bytes, fname, mimetype)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()[:400]
            log(f"post {post_id}: Graph HTTP {exc.code}: {detail}")
            cur.execute("UPDATE social_media_post SET state='failed', failure_reason=%s WHERE id=%s",
                        (f"Graph {exc.code}: {detail}", post_id))
            conn.commit()
            # Auth error -> stop the whole run (token dead); avoid hammering.
            if exc.code in (400, 401, 403) and "OAuth" in detail:
                log("auth error detected; stopping run.")
                break
            continue
        except Exception as exc:  # noqa: BLE001
            log(f"post {post_id}: error {exc}")
            cur.execute("UPDATE social_media_post SET state='failed', failure_reason=%s WHERE id=%s",
                        (str(exc)[:400], post_id))
            conn.commit()
            continue

        fb_post_id = result.get("post_id") or result.get("id")
        cur.execute("""
            UPDATE social_media_post
            SET state='pushed', remote_state='posted', facebook_post_id=%s,
                pushed_date=(now() AT TIME ZONE 'UTC'), failure_reason=NULL
            WHERE id=%s""", (str(fb_post_id), post_id))
        conn.commit()
        published += 1
        log(f"post {post_id}: PUBLISHED fb_post_id={fb_post_id}")

    log(f"run complete: {published} published.")


if __name__ == "__main__":
    main()
