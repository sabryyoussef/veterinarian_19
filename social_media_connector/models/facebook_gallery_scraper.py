# -*- coding: utf-8 -*-
"""Download photos from Facebook page Graph API into website gallery folder."""
from __future__ import annotations

import json
import logging
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_logger = logging.getLogger(__name__)

GRAPH_VERSION = "v19.0"
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _website_gallery_root(module_root: Path) -> Path:
    return module_root.parent / "website" / "assets" / "gallery"


def _graph_get_url(url: str) -> dict:
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(urllib.request.Request(url), context=ctx, timeout=120) as resp:
        return json.loads(resp.read().decode())


def _graph_get(path_and_query: str, access_token: str) -> dict:
    sep = "&" if "?" in path_and_query else "?"
    url = (
        f"https://graph.facebook.com/{GRAPH_VERSION}/{path_and_query}"
        f"{sep}access_token={urllib.parse.quote(access_token)}"
    )
    return _graph_get_url(url)


def _paginate(path_and_query: str, access_token: str, max_items: int) -> list[dict]:
    rows: list[dict] = []
    next_url: str | None = None
    while len(rows) < max_items:
        if next_url:
            payload = _graph_get_url(next_url)
        else:
            payload = _graph_get(path_and_query, access_token)
        rows.extend(payload.get("data", []))
        next_url = payload.get("paging", {}).get("next")
        if not next_url:
            break
    return rows[:max_items]


def _best_image_url(item: dict) -> str | None:
    images = item.get("images") or []
    if images:
        best = max(images, key=lambda img: (img.get("width") or 0) * (img.get("height") or 0))
        return best.get("source")
    return item.get("full_picture")


def _download_image(url: str) -> tuple[bytes, str]:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
        raw = resp.read()
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError(f"Image too large ({len(raw)} bytes)")
        mimetype = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        return raw, mimetype


def _safe_slug(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^\w\-]+", "-", (text or "").strip(), flags=re.UNICODE)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return (slug[:limit] or "photo").lower()


def scrape_facebook_gallery(
    client,
    *,
    page_facebook_id: str,
    remote_account_id: int,
    module_root: Path,
    max_photos: int = 200,
    fill_slots: bool = False,
) -> dict:
    """Scrape page photos/posts from Facebook Graph API using Odoo page token."""
    client.authenticate()
    rows = client.search_read(
        "social.account",
        [("id", "=", remote_account_id)],
        ["name", "facebook_access_token"],
        limit=1,
    )
    if not rows or not rows[0].get("facebook_access_token"):
        raise RuntimeError("Facebook page token missing on Odoo Online — reconnect the page.")

    token = rows[0]["facebook_access_token"]
    page_name = rows[0]["name"]
    gallery_root = _website_gallery_root(module_root)
    fb_dir = gallery_root / "facebook"
    fb_dir.mkdir(parents=True, exist_ok=True)

    uploaded = _paginate(
        f"{page_facebook_id}/photos?type=uploaded&fields=id,images,created_time,name&limit=50",
        token,
        max_photos,
    )
    posts = _paginate(
        f"{page_facebook_id}/posts?fields=id,message,full_picture,created_time&limit=50",
        token,
        max_photos,
    )

    candidates: list[dict] = []
    seen_ids: set[str] = set()

    for item in uploaded:
        photo_id = str(item.get("id") or "")
        if not photo_id or photo_id in seen_ids:
            continue
        url = _best_image_url(item)
        if not url:
            continue
        seen_ids.add(photo_id)
        candidates.append(
            {
                "id": photo_id,
                "kind": "photo",
                "url": url,
                "created_time": item.get("created_time"),
                "caption": item.get("name") or "",
            }
        )

    for item in posts:
        post_id = str(item.get("id") or "")
        if not post_id or post_id in seen_ids:
            continue
        url = item.get("full_picture")
        if not url:
            continue
        seen_ids.add(post_id)
        candidates.append(
            {
                "id": post_id.replace("/", "_"),
                "kind": "post",
                "url": url,
                "created_time": item.get("created_time"),
                "caption": (item.get("message") or "")[:300],
            }
        )

    candidates.sort(key=lambda c: c.get("created_time") or "", reverse=True)
    candidates = candidates[:max_photos]

    saved: list[dict] = []
    for item in candidates:
        dest = fb_dir / f"{item['id']}.jpg"
        if dest.is_file() and dest.stat().st_size > 1000:
            saved.append({**item, "file": str(dest.relative_to(gallery_root))})
            continue
        try:
            raw, mimetype = _download_image(item["url"])
            if "png" in mimetype:
                dest = fb_dir / f"{item['id']}.png"
            dest.write_bytes(raw)
            saved.append(
                {
                    **item,
                    "file": str(dest.relative_to(gallery_root)),
                    "bytes": len(raw),
                }
            )
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:
            _logger.warning("Skip %s: %s", item["id"], exc)

    manifest = gallery_root / "facebook" / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "page_id": page_facebook_id,
                "page_name": page_name,
                "source": "Facebook Graph API (your page photos)",
                "count": len(saved),
                "items": saved,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    slot_map = {}
    if fill_slots and saved:
        slot_names = [
            ("clinic-front.jpg", ("clinic", "front", "open", "عياد", "فرع")),
            ("grooming-area.jpg", ("groom", "جرو", "salon", "spa")),
            ("boarding-area.jpg", ("board", "بورد", "hotel", "stay")),
            ("veterinary-care.jpg", ("vet", "care", "طوارئ", "كشف", "علاج")),
        ]
        used: set[str] = set()

        def _src_path(item: dict) -> Path | None:
            for ext in (".jpg", ".png"):
                path = fb_dir / f"{item['id']}{ext}"
                if path.is_file():
                    return path
            return None

        for slot_file, keywords in slot_names:
            pick = None
            for item in saved:
                if item["id"] in used:
                    continue
                text = (item.get("caption") or "").lower()
                if any(k in text for k in keywords):
                    pick = item
                    break
            if not pick:
                for item in saved:
                    if item["id"] not in used:
                        pick = item
                        break
            if not pick:
                continue
            src = _src_path(pick)
            if src:
                (gallery_root / slot_file).write_bytes(src.read_bytes())
                used.add(pick["id"])
                slot_map[slot_file] = slot_file

    return {
        "page_name": page_name,
        "downloaded": len(saved),
        "gallery_dir": str(fb_dir),
        "manifest": str(manifest),
        "slots_filled": slot_map,
    }
