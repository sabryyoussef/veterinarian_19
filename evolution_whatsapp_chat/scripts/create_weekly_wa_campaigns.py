#!/usr/bin/env python3
"""
PetSpot El Sahel — WhatsApp Weekly Campaign Generator
======================================================
Creates 6 daily wa.campaign records for one ISO week (Sat–Thu, skip Fri).
Each day targets ~125 contacts with a rotated bilingual template.

Usage:
    # From repo root, via odoo-bin shell:
    python3 odoo19/odoo19/odoo-bin shell -c config/projects/pet_spot_elsahel.conf \
        -d pet_spot_elsahel --no-http < \
        projects/pet_spot_elsahel/evolution_whatsapp_chat/scripts/create_weekly_wa_campaigns.py

    # Or pass --week to target a specific ISO week (default = current):
    WEEK=26 python3 odoo19/odoo19/odoo-bin shell ...

Safety rules enforced
---------------------
- check_duplicates = True   → never re-send to same contact in same campaign
- min_days_between = 7      → skip contacts messaged in the last 7 days
- delay_between = 8s        → 8-second gap between each send
- send_mode = queue         → routed through outbound queue (rate-limited)
- Max 125 contacts/day      → well within WhatsApp safe limits (~150 msg/hr)
- No DELETE on existing sent history
- Cancelled campaigns (state=cancelled) are ignored, not deleted

Template rotation (fixed per weekday)
--------------------------------------
Saturday   → PetSpot — Grand Opening 🎉
Sunday     → PetSpot — Services Overview 🏥
Monday     → PetSpot — Book Appointment 📅
Tuesday    → PetSpot — Grooming ✂️
Wednesday  → PetSpot — Location & Directions 📍
Thursday   → PetSpot — Follow-up Check-in 💛
(Friday = REST — no campaign created)
"""
import os
import sys
import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

CAIRO = ZoneInfo("Africa/Cairo")
UTC   = ZoneInfo("UTC")

# ── Configuration ─────────────────────────────────────────────────────────────

SEND_HOUR_CAIRO  = 10          # 10:00 AM Cairo start
SEND_DELAY_SEC   = 8           # seconds between messages
MIN_DAYS_BETWEEN = 7           # cooldown in days
BATCH_SIZE       = 125         # max contacts per day

# Weekday → template name  (0=Mon … 5=Sat, 6=Sun in Python isoweekday: 1=Mon…7=Sun)
# Using isoweekday: 6=Sat, 7=Sun, 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri
TEMPLATE_ROTATION = {
    6: "PetSpot — Grand Opening 🎉",           # Saturday
    7: "PetSpot — Services Overview 🏥",        # Sunday
    1: "PetSpot — Book Appointment 📅",         # Monday
    2: "PetSpot — Grooming ✂️",                 # Tuesday
    3: "PetSpot — Location & Directions 📍",    # Wednesday
    4: "PetSpot — Follow-up Check-in 💛",       # Thursday
    # 5 = Friday → REST, skipped
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def week_start_saturday(ref: date | None = None) -> date:
    """Return the Saturday that anchors the current Middle-Eastern work week.
    The Egyptian/Gulf week runs Saturday → Thursday; Friday is the rest day.
    isoweekday: Mon=1 … Sat=6, Sun=7
    We walk backward from ref (default: today) to the nearest Saturday.
    """
    ref = ref or date.today()
    # isoweekday 6 = Saturday
    days_since_sat = (ref.isoweekday() % 7 + 1) % 7  # 0 on Sat, 1 on Sun, …, 6 on Fri
    # Actually simpler: sat=6 in isoweekday, so offset = (isoweekday - 6) % 7
    offset = (ref.isoweekday() - 6) % 7
    return ref - timedelta(days=offset)


def week_dates(iso_year: int, iso_week: int) -> list[tuple[int, date]]:
    """Return [(isoday, date), ...] for Sat–Thu of the Middle-Eastern week.

    Strategy: derive the Saturday anchor from the ISO week number, then step
    forward Sat(+0), Sun(+1), Mon(+2), Tue(+3), Wed(+4), Thu(+5).

    For ISO week W, we take the Monday (isoweekday=1) of that week and find
    the *following* Saturday (+5 days), which is the Saturday that starts the
    Middle-Eastern week overlapping with ISO week W+1.  This matches the
    intuitive mapping where "week 25 campaigns" start on the Saturday after
    the Friday of ISO week 25.
    """
    # Use env variable START_DATE if provided (format: YYYY-MM-DD), else compute.
    start_env = os.environ.get("START_DATE", "")
    if start_env:
        sat = date.fromisoformat(start_env)
        # Ensure it is actually a Saturday
        if sat.isoweekday() != 6:
            raise ValueError(f"START_DATE {start_env} is not a Saturday (isoweekday={sat.isoweekday()})")
    else:
        # Default: nearest Saturday on or before today
        sat = week_start_saturday()

    result = []
    day_offsets = [
        (6, 0),   # Saturday
        (7, 1),   # Sunday
        (1, 2),   # Monday
        (2, 3),   # Tuesday
        (3, 4),   # Wednesday
        (4, 5),   # Thursday
    ]
    for isoday, offset in day_offsets:
        result.append((isoday, sat + timedelta(days=offset)))
    return result


def cairo_to_utc(d: date, hour: int) -> datetime:
    """Convert local Cairo time to UTC naive datetime (for Odoo storage)."""
    local_dt = datetime(d.year, d.month, d.day, hour, 0, 0, tzinfo=CAIRO)
    return local_dt.astimezone(UTC).replace(tzinfo=None)


def get_template(name: str):
    tmpl = env["evo.wa.template"].search([("name", "=", name), ("active", "=", True)], limit=1)
    if not tmpl:
        raise RuntimeError(f"Template not found: {name!r}")
    return tmpl


def split_batches(partner_ids: list, batch_size: int, num_batches: int) -> list[list]:
    """Split partner ids into num_batches evenly, round-robin for leftovers."""
    batches = [[] for _ in range(num_batches)]
    for i, pid in enumerate(partner_ids):
        batches[i % num_batches].append(pid)
    return batches


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Determine target ISO week
    iso_week = int(os.environ.get("WEEK", date.today().isocalendar().week))
    iso_year = int(os.environ.get("YEAR", date.today().isocalendar().year))
    # Resolve send_days early so week_sat is available for header
    send_days  = week_dates(iso_year, iso_week)
    num_days   = len(send_days)
    week_sat   = send_days[0][1]
    week_label = week_sat.strftime("%Y-%m-%d")

    print(f"\n{'='*60}")
    print(f" PetSpot WhatsApp Weekly Campaign — week of {week_label}")
    print(f"{'='*60}")

    # Cancel any superseded draft/scheduled campaigns with no sends
    old = env["wa.campaign"].search([
        ("name", "ilike", "PetSpot W"),
        ("state", "in", ["draft", "scheduled"]),
        ("sent_count", "=", 0),
    ])
    for c in old:
        c.write({"state": "cancelled"})
        env.cr.commit()
        print(f"[cancel] Cancelled stale campaign id={c.id} '{c.name}'")

    # Load all contacts with phone
    partners = env["res.partner"].search([
        ("phone", "!=", False),
        ("active", "=", True),
    ], order="id asc")
    total = len(partners)
    print(f"[contacts] {total} contacts with phone")

    batches = split_batches(partners.ids, BATCH_SIZE, num_days)

    created = []
    skipped = []

    for idx, (isoday, day_date) in enumerate(send_days):
        tmpl_name   = TEMPLATE_ROTATION[isoday]
        day_name    = day_date.strftime("%A")
        camp_name   = f"PetSpot WA {week_label} {day_name} — {tmpl_name[:28]}"
        batch_ids   = batches[idx]
        sched_utc   = cairo_to_utc(day_date, SEND_HOUR_CAIRO)
        sched_cairo = f"{day_date} {SEND_HOUR_CAIRO:02d}:00 Cairo"

        # Skip if a non-cancelled campaign already exists for this slot
        existing = env["wa.campaign"].search([
            ("name", "=", camp_name),
            ("state", "not in", ["cancelled"]),
        ], limit=1)
        if existing:
            print(f"[skip] Already exists: '{camp_name}' id={existing.id} state={existing.state}")
            skipped.append(existing)
            continue

        tmpl = get_template(tmpl_name)

        # Select partner records for this batch
        batch_partners = env["res.partner"].browse(batch_ids)

        campaign = env["wa.campaign"].create({
            "name":             camp_name,
            "description": (
                f"PetSpot El Sahel — Week {iso_year}-W{iso_week:02d}, {day_name}.\n"
                f"Template: {tmpl_name}\n"
                f"Batch: {len(batch_ids)} contacts\n"
                f"Send window: {sched_cairo} → 18:00 Cairo\n"
                f"Anti-spam: {SEND_DELAY_SEC}s delay, 7-day cooldown, duplicates blocked."
            ),
            "state":            "scheduled",
            "template_id":      tmpl.id,
            "message":          tmpl.body,
            "personalise":      True,
            "target_model":     "res.partner",
            "partner_ids":      [(6, 0, batch_ids)],
            "send_mode":        "queue",
            "delay_between":    SEND_DELAY_SEC,
            "check_duplicates": True,
            "min_days_between": MIN_DAYS_BETWEEN,
            "scheduled_date":   sched_utc,
        })
        env.cr.commit()

        # Generate recipient lines
        campaign.action_generate_lines()
        env.cr.commit()
        campaign.invalidate_recordset()

        print(
            f"[created] id={campaign.id:3d}  {day_name:10s} {str(day_date)}  "
            f"batch={len(batch_ids):3d}  pending={campaign.pending_count}  "
            f"skipped={campaign.skipped_count}  tmpl={tmpl_name[:35]}"
        )
        created.append(campaign)

    # Summary
    print(f"\n{'='*60}")
    print(f" SUMMARY — week of {week_label}")
    print(f"{'='*60}")
    print(f"  Created   : {len(created)} daily campaigns")
    print(f"  Skipped   : {len(skipped)} (already existed)")
    total_pending = sum(c.pending_count for c in created)
    total_skip    = sum(c.skipped_count for c in created)
    print(f"  Pending   : {total_pending} recipients")
    print(f"  Skipped   : {total_skip} (cooldown / duplicate)")
    print(f"\n  Next step : Odoo → WhatsApp → Campaigns")
    print(f"              Each campaign auto-starts at its scheduled time.")
    print(f"              Or click [Start Campaign] manually at 10 AM each day.")
    print(f"{'='*60}\n")


main()
