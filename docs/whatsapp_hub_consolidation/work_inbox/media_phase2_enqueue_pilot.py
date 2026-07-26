# -*- coding: utf-8 -*-
"""Phase 2 pilot: enqueue enrichment for already-downloaded media only.

Run inside odoo shell (pet_spot_elsahel_test):
  ./venv19/bin/python3 ./odoo19/odoo19/odoo-bin shell -c ./config/projects/pet_spot_elsahel_test.conf \
      -d pet_spot_elsahel_test --http-port=18179 < media_phase2_enqueue_pilot.py

Does NOT retry expired rows. Does NOT touch Production/OpenProject.
"""
import json

env["ir.config_parameter"].sudo().set_param(
    "devhub_whatsapp.media_enrichment_enabled", "True"
)

Media = env["dev.whatsapp.media"].sudo()
Job = env["dev.whatsapp.media.job"].sudo()

downloaded = Media.search([("retrieval_state", "=", "downloaded")], order="id asc")
print("downloaded media:", len(downloaded))

snapshot = []
jobs_created = []
for media in downloaded:
    msg = media.whatsapp_message_id
    snapshot.append(
        {
            "media_id": media.id,
            "message_id": msg.id,
            "media_type": media.media_type,
            "mime": media.mime_type,
            "size": media.file_size,
            "inbox_state_before": msg.inbox_state,
            "enrichment_state_before": media.enrichment_state,
        }
    )
    jobs = Job._enqueue_enrichment(media)
    for job in jobs:
        jobs_created.append(
            {"job_id": job.id, "kind": job.kind, "media_id": media.id}
        )

env.cr.commit()
out = {"snapshot": snapshot, "jobs": jobs_created}
with open("/tmp/media_phase2_pilot.json", "w") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=1)
print("jobs created:", len(jobs_created))
print(json.dumps(jobs_created, indent=1))
