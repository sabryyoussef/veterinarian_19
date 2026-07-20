# -*- coding: utf-8 -*-
"""OpenProject company / parent classification helpers."""
from __future__ import annotations

import json
import logging
from pathlib import Path

_logger = logging.getLogger(__name__)

# Fallback when group-project-map.json is unavailable (matches nextcloud map).
DEFAULT_COMPANY_PARENTS = {
    "bright": {"project_id": 15, "identifier": "izone-erp", "name": "Bright"},
    "edafa": {"project_id": 20, "identifier": "edafa", "name": "Edafa"},
    "testing": {"project_id": 21, "identifier": "testing", "name": "Testing"},
    "platform-ops": {"project_id": 22, "identifier": "platform-ops", "name": "Platform Ops"},
    "personal": {"project_id": 23, "identifier": "personal", "name": "Personal & Freelance"},
}

GROUP_PROJECT_MAP_PATHS = (
    Path("/home/sabry/nextcloud/group-project-map.json"),
    Path("/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/openproject_sync/data/group-project-map.json"),
)


def load_group_project_map() -> dict:
    for path in GROUP_PROJECT_MAP_PATHS:
        try:
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            _logger.warning("Could not read %s: %s", path, e)
    return {"_meta": {"company_parents": DEFAULT_COMPANY_PARENTS}}


def company_parents_by_key(data: dict | None = None) -> dict[str, dict]:
    data = data or load_group_project_map()
    parents = (data.get("_meta") or {}).get("company_parents") or {}
    if not parents:
        return dict(DEFAULT_COMPANY_PARENTS)
    # Normalize names
    out = {}
    for key, info in parents.items():
        out[key] = {
            "project_id": int(info.get("project_id")),
            "identifier": info.get("identifier") or key,
            "name": info.get("name") or key,
        }
    return out


def company_parents_by_op_id(data: dict | None = None) -> dict[int, dict]:
    by_key = company_parents_by_key(data)
    return {
        int(info["project_id"]): {"key": key, **info}
        for key, info in by_key.items()
    }


def company_key_by_project_id(data: dict | None = None) -> dict[int, str]:
    """Map OP project_id → company key from WA group entries + company parents."""
    data = data or load_group_project_map()
    result: dict[int, str] = {}
    for key, info in company_parents_by_key(data).items():
        result[int(info["project_id"])] = key
    for k, v in data.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        pid = v.get("project_id")
        company = v.get("company") or v.get("op_parent")
        if pid and company:
            result[int(pid)] = str(company)
    return result


def href_id(href: str | None) -> int | None:
    if not href or href == "urn:openproject-org:api:v3:null":
        return None
    try:
        return int(str(href).rstrip("/").split("/")[-1])
    except (TypeError, ValueError):
        return None


def resolve_classification(
    op_project_id: int,
    *,
    parent_id: int | None = None,
    parent_chain: list[int] | None = None,
    map_data: dict | None = None,
) -> dict:
    """
    Resolve company folder / work project classification for an OP project.

    parent_chain: [self?, direct_parent, ..., root] — optional; if provided,
    used to find the nearest company parent. Otherwise uses parent_id + map.
    """
    map_data = map_data or load_group_project_map()
    by_op = company_parents_by_op_id(map_data)
    by_proj_key = company_key_by_project_id(map_data)
    by_key = company_parents_by_key(map_data)

    op_project_id = int(op_project_id)
    is_company = op_project_id in by_op

    company_op_id = None
    company_key = None
    company_name = None

    if is_company:
        info = by_op[op_project_id]
        company_op_id = op_project_id
        company_key = info["key"]
        company_name = info["name"]
    else:
        # Walk chain: self key from WA map, then parents, then company parents set
        candidates = []
        if parent_chain:
            candidates.extend(int(x) for x in parent_chain if x)
        if parent_id:
            candidates.append(int(parent_id))
        candidates.append(op_project_id)

        for cid in candidates:
            if cid in by_op:
                info = by_op[cid]
                company_op_id = cid
                company_key = info["key"]
                company_name = info["name"]
                break
            if cid in by_proj_key:
                company_key = by_proj_key[cid]
                info = by_key.get(company_key) or {}
                company_op_id = int(info.get("project_id") or 0) or None
                company_name = info.get("name") or company_key
                break

        # If we only got key from WA map on self, still fill company_op_id
        if company_key and not company_op_id:
            info = by_key.get(company_key) or {}
            company_op_id = int(info.get("project_id") or 0) or None
            company_name = company_name or info.get("name") or company_key

    return {
        "op_project_id": op_project_id,
        "op_parent_project_id": int(parent_id) if parent_id else False,
        "op_company_project_id": int(company_op_id) if company_op_id else False,
        "op_company_key": company_key or False,
        "op_company_name": company_name or False,
        "op_is_company_folder": bool(is_company),
        "op_is_work_project": not bool(is_company),
    }
