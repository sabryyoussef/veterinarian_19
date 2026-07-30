# -*- coding: utf-8 -*-
"""Cairo-timezone pickup / flyer cutoff helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from odoo import fields


def _tz(backend):
    name = backend.company_timezone or "Africa/Cairo"
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("Africa/Cairo")


def local_now(backend, when=None):
    """Return timezone-aware datetime in company TZ."""
    tz = _tz(backend)
    if when is None:
        when = fields.Datetime.now()
    if isinstance(when, str):
        when = fields.Datetime.to_datetime(when)
    if when.tzinfo is None:
        # Odoo naive datetimes are UTC
        when = when.replace(tzinfo=ZoneInfo("UTC"))
    return when.astimezone(tz)


def _cutoff_passed(backend, cutoff_float, when=None):
    local = local_now(backend, when)
    hours = int(cutoff_float)
    minutes = int(round((cutoff_float - hours) * 60))
    cutoff_dt = local.replace(hour=hours, minute=minutes, second=0, microsecond=0)
    return local >= cutoff_dt, local, cutoff_dt


def pickup_cutoff_info(backend, when=None):
    passed, local, cutoff_dt = _cutoff_passed(backend, backend.pickup_cutoff_time, when)
    if passed:
        eligible = (local.date() + timedelta(days=1))
        same_day = False
    else:
        eligible = local.date()
        same_day = True
    return {
        "pickup_cutoff_passed": passed,
        "same_day_pickup_possible": same_day,
        "eligible_pickup_date": eligible,
        "local_now": local,
        "cutoff_local": cutoff_dt,
    }


def flyer_cutoff_info(backend, when=None):
    passed, local, cutoff_dt = _cutoff_passed(backend, backend.flyer_cutoff_time, when)
    return {
        "flyer_cutoff_passed": passed,
        "local_now": local,
        "cutoff_local": cutoff_dt,
    }


def pickup_warning_text(backend, shipment_count=None, when=None):
    parts = []
    info = pickup_cutoff_info(backend, when)
    if info["pickup_cutoff_passed"]:
        parts.append(
            f"Pickup cutoff ({backend.float_time_to_str(backend.pickup_cutoff_time)}) passed — "
            f"eligible pickup date {info['eligible_pickup_date']}."
        )
    else:
        parts.append("Same-day pickup still possible before cutoff.")
    flyer = flyer_cutoff_info(backend, when)
    if flyer["flyer_cutoff_passed"]:
        parts.append(
            f"Flyer cutoff ({backend.float_time_to_str(backend.flyer_cutoff_time)}) passed."
        )
    if shipment_count is not None and shipment_count < int(backend.min_shipments_per_pickup or 5):
        parts.append(
            f"Pickup has {shipment_count} shipments (min {backend.min_shipments_per_pickup}); "
            f"estimated surcharge {backend.low_volume_pickup_surcharge:.2f} EGP — confirmation required."
        )
    return " ".join(parts)
