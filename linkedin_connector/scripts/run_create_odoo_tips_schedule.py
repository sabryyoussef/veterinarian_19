# -*- coding: utf-8 -*-
# Run inside Odoo shell after upgrading linkedin_connector:
#   python odoo-bin shell -c <conf> -d <db> < projects/resume/linkedin_connector/scripts/run_create_odoo_tips_schedule.py
posts = env["linkedin.post"].create_odoo_tips_schedule_batch()
env.cr.commit()
print("created_count", len(posts))
for p in posts.sorted("scheduled_date"):
    msg = (p.message or "").replace("\n", " ")
    snippet = " ".join(msg.split()[:12])
    print(
        p.internal_title,
        "|",
        p.scheduled_date,
        "|",
        snippet,
    )
