#!/usr/bin/env python3
"""Enqueue Phase-1 pilot media downloads on Test DB (approved sample only)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# Run inside odoo shell via stdin - this file documents selection; actual enqueue via shell below.
PROBE = Path(
    "/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/docs/"
    "whatsapp_hub_consolidation/work_inbox/media_phase0_results/probe_latest.json"
)


def pick_ids():
    data = json.loads(PROBE.read_text())
    results = data["results"]
    picked = []

    def take(kind, age, n, recovered_only=True):
        rows = [
            r
            for r in results
            if r["media_kind"] == kind
            and r["age_bucket"] == age
            and (
                not recovered_only
                or r["classification"] == "recovered_original"
            )
        ]
        # prefer Dev Needed + Torz mix
        rows.sort(key=lambda r: (0 if "Dev Needed" in r["source_group"] else 1, r["message_id"]))
        for r in rows[:n]:
            picked.append(r["message_id"])

    take("image", "recent", 8)
    take("image", "older", 2, recovered_only=False)  # expect expired
    take("audio", "recent", 8)
    take("audio", "older", 2, recovered_only=False)
    take("video", "recent", 4)  # keep fewer/smaller if possible — filter size later
    take("video", "older", 1, recovered_only=False)
    # Torz extras if not already
    for r in results:
        if "Torz" in r["source_group"] and r["classification"] == "recovered_original":
            if r["message_id"] not in picked:
                picked.append(r["message_id"])
            if sum(1 for i in picked if True) >= 30:
                break
    # unique preserve order
    out = []
    seen = set()
    for i in picked:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out[:32]


if __name__ == "__main__":
    ids = pick_ids()
    print(json.dumps({"count": len(ids), "message_ids": ids}))
