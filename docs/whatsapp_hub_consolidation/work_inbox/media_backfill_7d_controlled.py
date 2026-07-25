# -*- coding: utf-8 -*-
"""Controlled seven-day Test media backfill runner.

Run through the Odoo shell with:

    BACKFILL_MODE=dry-run|enqueue
    BACKFILL_SOURCE_IDS=12
    BACKFILL_MEDIA_TYPE=image
    BACKFILL_RUN_REF=wa-media-7d-20260725-tourz-image

The guarded Odoo service enforces source approval, exact timestamps,
idempotency, supported media types, and non-mutation of inbox/Work Items.
"""
import json
import os


START_AT = "2026-07-18 09:22:14"
END_AT = "2026-07-25 09:22:14"

mode = (os.environ.get("BACKFILL_MODE") or "dry-run").strip()
source_ids = [
    int(item)
    for item in (os.environ.get("BACKFILL_SOURCE_IDS") or "").split(",")
    if item.strip()
]
media_type = (os.environ.get("BACKFILL_MEDIA_TYPE") or "").strip() or None
run_ref = (os.environ.get("BACKFILL_RUN_REF") or "wa-media-7d-20260725").strip()

manager = env["res.users"].search([("login", "=", "admin")], limit=1)
if not manager.has_group("devhub_core.group_dev_hub_manager"):
    manager = env["res.users"].search([], order="id").filtered(
        lambda user: user.has_group("devhub_core.group_dev_hub_manager")
    )[:1]
if not manager:
    raise RuntimeError("No Dev Hub manager is available.")

Backfill = env["dev.whatsapp.media.backfill"].with_user(manager)
if mode == "dry-run":
    result = Backfill.dry_run(
        START_AT,
        END_AT,
        source_ids=source_ids or None,
        media_type=media_type,
    )
elif mode == "enqueue":
    if not source_ids or not media_type:
        raise RuntimeError("enqueue requires BACKFILL_SOURCE_IDS and BACKFILL_MEDIA_TYPE")
    result = Backfill.enqueue_batch(
        START_AT,
        END_AT,
        source_ids=source_ids,
        media_type=media_type,
        limit=50,
        run_ref=run_ref,
    )
    env.cr.commit()
else:
    raise RuntimeError("BACKFILL_MODE must be dry-run or enqueue")

print("BACKFILL_RESULT=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
