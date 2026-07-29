# -*- coding: utf-8 -*-
"""Normalize ShipBlu order statuses to Odoo shipment statuses."""

from __future__ import annotations

NORMALIZED = [
    ("created", "Created"),
    ("picked_up", "Picked up"),
    ("in_transit", "In transit"),
    ("out_for_delivery", "Out for delivery"),
    ("delivered", "Delivered"),
    ("delivery_failed", "Delivery failed"),
    ("returned", "Returned / RTO"),
    ("cancelled", "Cancelled"),
    ("manual_review", "Unknown / Manual review"),
]

RAW_STATUS_SELECTION = [
    ("CREATED", "Created"),
    ("PICKUP_REQUESTED", "Pickup requested"),
    ("PICKUP_RESCHEDULED", "Pickup rescheduled"),
    ("PICKED_UP", "Picked up"),
    ("IN_TRANSIT", "In transit"),
    ("EN_ROUTE", "En route"),
    ("OUT_FOR_DELIVERY", "Out for delivery"),
    ("DELIVERY_ATTEMPTED", "Delivery attempted"),
    ("DELIVERED", "Delivered"),
    ("RETURN_TO_ORIGIN", "Return to origin"),
    ("RETURN_REQUESTED", "Return requested"),
    ("RETURN_ATTEMPTED", "Return attempted"),
    ("OUT_FOR_RETURN", "Out for return"),
    ("RETURN_REFUSED", "Return refused"),
    ("RETURN_POSTPONED", "Return postponed"),
    ("RETURNED", "Returned"),
    ("CANCELLED", "Cancelled"),
]

_RULES = [
    (("cancel",), "cancelled"),
    (("return_to_origin", "returned", "return_refused", "out_for_return", "return_"), "returned"),
    (("delivery_attempted", "fail", "exception"), "delivery_failed"),
    (("out_for_delivery",), "out_for_delivery"),
    (("delivered",), "delivered"),
    (("in_transit", "en_route"), "in_transit"),
    (("picked_up", "pickup_requested", "pickup_rescheduled"), "picked_up"),
    (("created",), "created"),
]


def normalize_shipblu_status(raw_status) -> str:
    if raw_status is None:
        return "manual_review"
    text = str(raw_status).strip().lower()
    if not text:
        return "manual_review"
    for needles, code in _RULES:
        for needle in needles:
            if needle in text:
                return code
    return "manual_review"


def coerce_raw_status(raw_status):
    if not raw_status:
        return False
    text = str(raw_status).strip().upper()
    allowed = {x[0] for x in RAW_STATUS_SELECTION}
    return text if text in allowed else False
