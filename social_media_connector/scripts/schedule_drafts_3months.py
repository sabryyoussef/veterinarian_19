# -*- coding: utf-8 -*-
"""Schedule the 7 draft campaign posts daily 10:00-22:00 (Africa/Cairo) for 3 months.

Run via Odoo shell:
    odoo-bin shell -c <conf> -d pet_spot_elsahel --no-http < schedule_drafts_3months.py

- All 7 posts go out every day, spread evenly across 10:00..22:00 (2h apart).
- Repeats daily for DAYS days (~3 months).
- Publishing is NOT triggered: posts are set to state 'ready' + post_method 'scheduled'
  while auto-push stays disabled, so nothing is sent until publishing is wired.
- Day 1 reuses the existing draft records; later days are copies (images included).
"""
import datetime
from zoneinfo import ZoneInfo

DAYS = 90
TZ = ZoneInfo("Africa/Cairo")
UTC = ZoneInfo("UTC")
START_HOUR = 10
END_HOUR = 22

Post = env["social.media.post"]
ICP = env["ir.config_parameter"].sudo()

# Keep window params in sync for future use of the module scheduler.
ICP.set_param("social_media_connector.campaign_schedule_start_hour", str(START_HOUR))
ICP.set_param("social_media_connector.campaign_schedule_end_hour", str(END_HOUR))

# Safety: never auto-publish from this scheduling pass.
ICP.set_param("social_media_connector.auto_push_enabled", "False")

templates = Post.search(
    [("state", "=", "draft"), ("title", "ilike", "Summer Knowledge Quest")],
    order="scheduled_date, id",
)
if not templates:
    templates = Post.search([("state", "=", "draft")], order="id")

templates = list(templates)
n = len(templates)
if n == 0:
    raise SystemExit("No draft posts found to schedule.")

# Even slots across [START_HOUR, END_HOUR] inclusive.
step = (END_HOUR - START_HOUR) / (n - 1) if n > 1 else 0
slots = []
for i in range(n):
    h = START_HOUR + step * i
    hour = int(h)
    minute = int(round((h - hour) * 60))
    slots.append((hour, minute))

# Guard against accidental double-run: bail if a large future 'ready' backlog exists.
now_naive = datetime.datetime.utcnow()
existing_future = Post.search_count(
    [("state", "=", "ready"), ("scheduled_date", ">", now_naive)]
)
if existing_future > n:
    raise SystemExit(
        "Aborting: %s future 'ready' posts already exist (looks already scheduled)."
        % existing_future
    )

start_date = datetime.date.today()
# If today's last slot has already passed, start tomorrow.
last_hour = slots[-1][0]
local_now = datetime.datetime.now(TZ)
if local_now.hour >= last_hour:
    start_date = start_date + datetime.timedelta(days=1)

created = 0
rescheduled = 0
for d in range(DAYS):
    day = start_date + datetime.timedelta(days=d)
    for i, tmpl in enumerate(templates):
        hour, minute = slots[i]
        local_dt = datetime.datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)
        utc_naive = local_dt.astimezone(UTC).replace(tzinfo=None)
        vals = {
            "scheduled_date": utc_naive,
            "post_method": "scheduled",
            "state": "ready",
            "remote_post_id": False,
            "remote_stream_post_id": False,
            "facebook_post_id": False,
            "remote_state": False,
            "failure_reason": False,
            "pushed_date": False,
        }
        if d == 0:
            tmpl.write(vals)
            rescheduled += 1
        else:
            tmpl.copy({**vals, "title": tmpl.title})
            created += 1

env.cr.commit()
print(
    "Scheduled: %s day-1 rescheduled + %s copies = %s total posts across %s days (%s/day)."
    % (rescheduled, created, rescheduled + created, DAYS, n)
)
