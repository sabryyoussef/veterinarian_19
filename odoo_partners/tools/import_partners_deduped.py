#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Controlled import of odoo_partners demo XML into a target DB with dedupe + tagging.

Target must already have odoo_partners categories installed (data XML).
Does NOT load Odoo demo mode — parses demo XML as a curated source file.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
import xmlrpc.client
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse


SAFE_WRITE_IF_EMPTY = ("email", "phone", "website", "street", "city", "zip", "comment")


def norm_email(v: Optional[str]) -> str:
    return (v or "").strip().lower()


def norm_phone(v: Optional[str]) -> str:
    return re.sub(r"\D+", "", v or "")


def norm_domain(website: Optional[str]) -> str:
    if not website:
        return ""
    w = website.strip().lower()
    if not w.startswith(("http://", "https://")):
        w = "https://" + w
    try:
        host = urlparse(w).netloc or urlparse(w).path
    except Exception:
        return website.strip().lower()
    host = host.split("@")[-1]
    if host.startswith("www."):
        host = host[4:]
    return host.rstrip("/")


def norm_name(v: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (v or "").strip().lower())


class Odoo:
    def __init__(self, url: str, db: str, user: str, password: str):
        self.url = url.rstrip("/")
        self.db = db
        self.password = password
        common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common", allow_none=True)
        self.uid = common.authenticate(db, user, password, {})
        if not self.uid:
            raise RuntimeError("auth failed")
        self.models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object", allow_none=True)

    def execute(self, model: str, method: str, *args, **kwargs):
        return self.models.execute_kw(self.db, self.uid, self.password, model, method, list(args), kwargs or {})


def parse_demo(xml_path: Path) -> List[dict]:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    rows = []
    for rec in root.iter("record"):
        if rec.get("model") != "res.partner":
            continue
        xid = rec.get("id")
        vals: Dict[str, Any] = {"_xmlid": xid}
        cat_refs: List[str] = []
        for field in rec.findall("field"):
            name = field.get("name")
            if name is None:
                continue
            if name == "category_id":
                ev = field.get("eval") or ""
                cat_refs = re.findall(r"ref\('([^']+)'\)", ev)
                continue
            if field.get("ref"):
                vals[name] = ("ref", field.get("ref"))
                continue
            if field.get("eval") is not None:
                ev = field.get("eval")
                if ev in ("True", "False"):
                    vals[name] = ev == "True"
                else:
                    vals[name] = ev
                continue
            vals[name] = (field.text or "").strip()
        vals["_category_refs"] = cat_refs
        rows.append(vals)
    return rows


def resolve_country(odoo: Odoo, cache: dict, ref: str) -> Optional[int]:
    if ref in cache:
        return cache[ref]
    if not ref.startswith("base."):
        cache[ref] = None
        return None
    code = ref.split(".", 1)[1]
    # base.us -> code US-ish; country xmlids are base.us for United States
    found = odoo.execute("ir.model.data", "search_read", [["module", "=", "base"], ["name", "=", code], ["model", "=", "res.country"]], fields=["res_id"], limit=1)
    rid = found[0]["res_id"] if found else None
    cache[ref] = rid
    return rid


def resolve_category(odoo: Odoo, cache: dict, xmlid: str) -> Optional[int]:
    if xmlid in cache:
        return cache[xmlid]
    if "." not in xmlid:
        cache[xmlid] = None
        return None
    mod, name = xmlid.split(".", 1)
    found = odoo.execute(
        "ir.model.data",
        "search_read",
        [["module", "=", mod], ["name", "=", name], ["model", "=", "res.partner.category"]],
        fields=["res_id"],
        limit=1,
    )
    rid = found[0]["res_id"] if found else None
    cache[xmlid] = rid
    return rid


def build_indexes(odoo: Odoo) -> dict:
    partners = odoo.execute(
        "res.partner",
        "search_read",
        [],
        fields=["id", "name", "email", "website", "phone", "country_id", "x_x_owner_x_pets_count", "category_id"],
        order="id asc",
    )
    by_email: Dict[str, int] = {}
    by_domain: Dict[str, int] = {}
    by_name_country: Dict[Tuple[str, int], int] = {}
    by_phone: Dict[str, int] = {}
    clinic_ids = set()
    for p in partners:
        pid = p["id"]
        if (p.get("x_x_owner_x_pets_count") or 0) > 0:
            clinic_ids.add(pid)
        em = norm_email(p.get("email"))
        if em and em not in by_email:
            by_email[em] = pid
        dom = norm_domain(p.get("website"))
        if dom and dom not in by_domain:
            by_domain[dom] = pid
        ctry = p["country_id"][0] if p.get("country_id") else 0
        key = (norm_name(p.get("name")), ctry)
        if key[0] and key not in by_name_country:
            by_name_country[key] = pid
        ph = norm_phone(p.get("phone"))
        if len(ph) >= 8 and ph not in by_phone:
            by_phone[ph] = pid
    return {
        "by_email": by_email,
        "by_domain": by_domain,
        "by_name_country": by_name_country,
        "by_phone": by_phone,
        "clinic_ids": clinic_ids,
    }


def find_match(vals: dict, country_id: Optional[int], idx: dict) -> Tuple[Optional[int], str]:
    dom = norm_domain(vals.get("website") if not isinstance(vals.get("website"), tuple) else "")
    if isinstance(vals.get("website"), str):
        dom = norm_domain(vals.get("website"))
    if dom and dom in idx["by_domain"]:
        return idx["by_domain"][dom], "website"
    em = norm_email(vals.get("email") if isinstance(vals.get("email"), str) else "")
    if em and em in idx["by_email"]:
        return idx["by_email"][em], "email"
    name = norm_name(vals.get("name") if isinstance(vals.get("name"), str) else "")
    ctry = country_id or 0
    if name and (name, ctry) in idx["by_name_country"]:
        return idx["by_name_country"][(name, ctry)], "name_country"
    ph = norm_phone(vals.get("phone") if isinstance(vals.get("phone"), str) else "")
    if len(ph) >= 8 and ph in idx["by_phone"]:
        return idx["by_phone"][ph], "phone"
    return None, ""


def ensure_xmlid(odoo: Odoo, module: str, name: str, model: str, res_id: int) -> None:
    existing = odoo.execute(
        "ir.model.data",
        "search",
        [["module", "=", module], ["name", "=", name], ["model", "=", model]],
        limit=1,
    )
    if existing:
        return
    odoo.execute(
        "ir.model.data",
        "create",
        {
            "module": module,
            "name": name,
            "model": model,
            "res_id": res_id,
            "noupdate": True,
        },
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8028")
    ap.add_argument("--db", default="pet_spot_elsahel_test")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="admin")
    ap.add_argument(
        "--xml",
        default=str(Path(__file__).resolve().parents[1] / "demo" / "res_partner_demo.xml"),
    )
    ap.add_argument("--report", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    odoo = Odoo(args.url, args.db, args.user, args.password)
    hub_partner = resolve_category(odoo, {}, "developer_hub.category_odoo_partner")
    hub_company = resolve_category(odoo, {}, "developer_hub.category_odoo_company")
    if not hub_partner:
        print("FATAL: developer_hub.category_odoo_partner missing", file=sys.stderr)
        return 2

    rows = parse_demo(Path(args.xml))
    if args.limit:
        rows = rows[: args.limit]
    print(f"source rows={len(rows)} hub_partner_cat={hub_partner}")

    idx = build_indexes(odoo)
    country_cache: dict = {}
    cat_cache: dict = {}

    stats = {
        "source": len(rows),
        "created": 0,
        "updated": 0,
        "skipped_duplicate": 0,
        "skipped_invalid": 0,
        "failed": 0,
        "matched_existing": 0,
        "clinic_tag_only": 0,
        "match_reasons": {},
        "failures": [],
        "duplicate_clusters": [],
    }

    for i, raw in enumerate(rows, 1):
        xid = raw.get("_xmlid") or f"row_{i}"
        try:
            name = raw.get("name")
            if not isinstance(name, str) or not name.strip():
                stats["skipped_invalid"] += 1
                continue

            country_id = None
            if isinstance(raw.get("country_id"), tuple) and raw["country_id"][0] == "ref":
                country_id = resolve_country(odoo, country_cache, raw["country_id"][1])

            cat_ids = []
            for cref in raw.get("_category_refs") or []:
                cid = resolve_category(odoo, cat_cache, cref)
                if cid:
                    cat_ids.append(cid)
            # Always tag for Developer Hub visibility
            cat_ids.append(hub_partner)
            if raw.get("is_company") and hub_company:
                cat_ids.append(hub_company)
            cat_ids = sorted(set(cat_ids))

            match_id, reason = find_match(raw, country_id, idx)
            if match_id:
                stats["matched_existing"] += 1
                stats["match_reasons"][reason] = stats["match_reasons"].get(reason, 0) + 1
                is_clinic = match_id in idx["clinic_ids"]
                # link categories only (never remove)
                odoo.execute("res.partner", "write", [match_id], {"category_id": [(4, cid) for cid in cat_ids]})
                if is_clinic:
                    stats["clinic_tag_only"] += 1
                    stats["skipped_duplicate"] += 1
                else:
                    # fill empty safe fields only
                    existing = odoo.execute(
                        "res.partner",
                        "read",
                        [match_id],
                        fields=list(SAFE_WRITE_IF_EMPTY),
                    )[0]
                    patch = {}
                    for f in SAFE_WRITE_IF_EMPTY:
                        src = raw.get(f)
                        if not isinstance(src, str) or not src.strip():
                            continue
                        if not existing.get(f):
                            patch[f] = src.strip()
                    if country_id and not existing.get("country_id"):
                        # country may be missing from read fields; set if useful
                        patch["country_id"] = country_id
                    if patch:
                        odoo.execute("res.partner", "write", [match_id], patch)
                        stats["updated"] += 1
                    else:
                        stats["skipped_duplicate"] += 1
                ensure_xmlid(odoo, "odoo_partners", xid, "res.partner", match_id)
            else:
                vals = {
                    "name": name.strip(),
                    "is_company": bool(raw.get("is_company")),
                    "type": raw.get("type") if isinstance(raw.get("type"), str) else "contact",
                    "active": bool(raw.get("active", True)),
                    "category_id": [(6, 0, cat_ids)],
                }
                if isinstance(raw.get("lang"), str):
                    vals["lang"] = raw["lang"]
                for f in ("email", "phone", "website", "street", "city", "zip", "comment"):
                    if isinstance(raw.get(f), str) and raw[f].strip():
                        vals[f] = raw[f].strip()
                if country_id:
                    vals["country_id"] = country_id
                new_id = odoo.execute("res.partner", "create", vals)
                stats["created"] += 1
                ensure_xmlid(odoo, "odoo_partners", xid, "res.partner", new_id)
                # refresh indexes for subsequent dedupe within import
                em = norm_email(vals.get("email"))
                if em:
                    idx["by_email"].setdefault(em, new_id)
                dom = norm_domain(vals.get("website"))
                if dom:
                    idx["by_domain"].setdefault(dom, new_id)
                idx["by_name_country"].setdefault((norm_name(vals["name"]), country_id or 0), new_id)
                ph = norm_phone(vals.get("phone"))
                if len(ph) >= 8:
                    idx["by_phone"].setdefault(ph, new_id)

            if i % 100 == 0:
                print(
                    f"… {i}/{len(rows)} created={stats['created']} updated={stats['updated']} "
                    f"skip_dup={stats['skipped_duplicate']} fail={stats['failed']}"
                )
        except Exception as exc:  # noqa: BLE001
            stats["failed"] += 1
            if len(stats["failures"]) < 40:
                stats["failures"].append({"xmlid": xid, "error": str(exc)[:400]})
            print(f"FAIL {xid}: {exc}", file=sys.stderr)

    # final counts
    tagged = odoo.execute(
        "res.partner",
        "search_count",
        [["category_id", "in", [hub_partner, hub_company] if hub_company else [hub_partner]]],
    )
    total = odoo.execute("res.partner", "search_count", [])
    stats["final_odoo_partner_tagged"] = tagged
    stats["final_total_partners"] = total

    report_path = Path(args.report) if args.report else Path(__file__).resolve().parents[1] / "tools" / "import_report.json"
    report_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=2))
    print(f"Wrote {report_path}")
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
