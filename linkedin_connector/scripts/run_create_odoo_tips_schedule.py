# -*- coding: utf-8 -*-
# Personal job-branding only. Run inside Odoo shell after upgrading linkedin_connector:
#   python odoo-bin shell -c <conf> -d <db> < .../linkedin_connector/scripts/run_create_odoo_tips_schedule.py
#
# Requires a linkedin.account with account_type=personal (never PetSpot/company).
# Keep publish cron off / account disconnected until UAT is approved.
personal = env["linkedin.account"].get_personal_account()
if not personal:
    raise SystemExit("No personal linkedin.account found — create one first.")
posts = env["linkedin.post"].create_odoo_tips_schedule_batch(account_id=personal.id)
env.cr.commit()
print("account", personal.id, personal.name, personal.account_type)
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
