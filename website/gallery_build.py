"""Pick and stage clinic photos from the Facebook scrape for the website gallery."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SLOT_RULES: list[tuple[str, str, str, tuple[str, ...]]] = [
    (
        "clinic-front.jpg",
        "clinic_front",
        "PetSpot El Sahel clinic front",
        ("clinic", "front", "facade", "entrance", "open", "عياد", "فرع", "سبوت", "ساحل"),
    ),
    (
        "grooming-area.jpg",
        "grooming",
        "PetSpot grooming area",
        ("groom", "جرو", "salon", "spa", "bath", "shower", "تجميل"),
    ),
    (
        "boarding-area.jpg",
        "boarding",
        "PetSpot boarding area",
        ("board", "بورد", "hotel", "stay", "cage", "إقامة"),
    ),
    (
        "veterinary-care.jpg",
        "veterinary",
        "PetSpot veterinary care",
        ("vet", "care", "طوارئ", "كشف", "علاج", "surgery", "فحص", "رعاية", "بيطر"),
    ),
]


def _alt_from_caption(caption: str, fallback: str = "PetSpot clinic photo") -> str:
    line = (caption or "").strip().split("\n", 1)[0]
    line = re.sub(r"\[PetSpot FB\]\s*", "", line)
    line = re.sub(r"[^\w\s\u0600-\u06FF.,!?'-]", " ", line)
    line = re.sub(r"\s+", " ", line).strip(" .")
    if len(line) < 8:
        return fallback
    return line[:100]


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_bytes: set[int] = set()
    unique: list[dict[str, Any]] = []
    ordered = sorted(
        items,
        key=lambda item: (
            0 if item.get("kind") == "photo" else 1,
            -(item.get("bytes") or 0),
        ),
    )
    for item in ordered:
        size = item.get("bytes")
        if size and size in seen_bytes:
            continue
        if size:
            seen_bytes.add(size)
        unique.append(item)
    return unique


def _item_path(gallery_dir: Path, item: dict[str, Any]) -> Path | None:
    rel = item.get("file")
    if not rel:
        return None
    path = gallery_dir / rel
    if path.is_file():
        return path
    stem = Path(rel).stem
    for ext in (".jpg", ".png", ".jpeg", ".webp"):
        candidate = gallery_dir / "facebook" / f"{stem}{ext}"
        if candidate.is_file():
            return candidate
    return None


def _copy_item(gallery_dir: Path, item: dict[str, Any], dest: Path) -> bool:
    src = _item_path(gallery_dir, item)
    if not src:
        return False
    dest.write_bytes(src.read_bytes())
    return True


def _pick_by_keywords(
    items: list[dict[str, Any]],
    keywords: tuple[str, ...],
    used_ids: set[str],
) -> dict[str, Any] | None:
    for item in items:
        if item["id"] in used_ids:
            continue
        text = (item.get("caption") or "").lower()
        if any(keyword in text for keyword in keywords):
            return item
    return None


def prepare_gallery(
    gallery_dir: Path,
    *,
    extra_count: int = 12,
) -> dict[str, Any] | None:
    """Stage homepage slot images + extra gallery files from facebook/manifest.json."""
    manifest_path = gallery_dir / "facebook" / "manifest.json"
    if not manifest_path.is_file():
        return None

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = _dedupe_items(payload.get("items") or [])
    if not items:
        return None

    used_ids: set[str] = set()
    slots: list[dict[str, str]] = []

    for slot_file, slot_id, alt, keywords in SLOT_RULES:
        pick = _pick_by_keywords(items, keywords, used_ids)
        if not pick:
            for item in items:
                if item["id"] not in used_ids:
                    pick = item
                    break
        if not pick:
            continue
        if _copy_item(gallery_dir, pick, gallery_dir / slot_file):
            used_ids.add(pick["id"])
            slots.append(
                {
                    "id": slot_id,
                    "file": slot_file,
                    "alt": alt,
                    "source_id": pick["id"],
                }
            )

    extras: list[dict[str, str]] = []
    remaining = [item for item in items if item["id"] not in used_ids]
    remaining.sort(key=lambda item: -(item.get("bytes") or 0))
    for item in remaining[:extra_count]:
        dest_name = f"gallery-{item['id']}.jpg"
        if not _copy_item(gallery_dir, item, gallery_dir / dest_name):
            continue
        used_ids.add(item["id"])
        extras.append(
            {
                "id": item["id"],
                "file": dest_name,
                "alt": _alt_from_caption(item.get("caption", "")),
            }
        )

    selection = {
        "page_name": payload.get("page_name"),
        "slot_count": len(slots),
        "extra_count": len(extras),
        "slots": slots,
        "extras": extras,
    }
    (gallery_dir / "selection.json").write_text(
        json.dumps(selection, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return selection
