# -*- coding: utf-8 -*-
"""Shared enums for PetSpot fulfillment orchestration."""

FULFILLMENT_PATHS = [
    ("store_stock", "Store stock"),
    ("supplier_b2b", "Supplier B2B"),
    ("manual_whatsapp", "Manual WhatsApp"),
    ("store_pickup", "Store pickup"),
    ("shipblu_delivery", "ShipBlu delivery"),
    ("unavailable", "Unavailable"),
    ("mixed", "Mixed"),
]

LINE_SOURCE = [
    ("store_stock", "Store stock"),
    ("supplier_b2b", "Supplier B2B"),
    ("manual_whatsapp", "Manual WhatsApp"),
    ("unavailable", "Unavailable"),
    ("unclassified", "Unclassified"),
]

DELIVERY_METHOD = [
    ("shipblu_delivery", "ShipBlu delivery"),
    ("store_pickup", "Store pickup"),
    ("undecided", "Undecided"),
]

# Operational orchestration states (coordinate native SO/PO/payment; do not replace them)
ORCH_STATES = [
    ("new", "New"),
    ("availability_check", "Availability check"),
    ("supplier_rfq", "Supplier RFQ"),
    ("supplier_confirmed", "Supplier confirmed"),
    ("customer_approval_required", "Customer approval required"),
    ("payment_pending", "Payment pending"),
    ("paid", "Paid"),
    ("purchase_confirmed", "Purchase confirmed"),
    ("awaiting_receipt", "Awaiting receipt"),
    ("ready_for_delivery", "Ready for delivery"),
    ("shipping_created", "Shipping created"),
    ("delivered", "Delivered"),
    ("store_pickup_ready", "Store pickup ready"),
    ("completed", "Completed"),
    ("unavailable", "Unavailable"),
    ("cancelled", "Cancelled"),
    ("exception", "Exception / refund review"),
]

# Allowed transitions: from -> frozenset(to)
ALLOWED_TRANSITIONS = {
    "new": frozenset({
        "availability_check", "supplier_rfq", "payment_pending", "paid",
        "unavailable", "cancelled", "exception",
    }),
    "availability_check": frozenset({
        "supplier_rfq", "paid", "payment_pending", "unavailable",
        "cancelled", "exception", "ready_for_delivery", "store_pickup_ready",
    }),
    "supplier_rfq": frozenset({
        "supplier_confirmed", "customer_approval_required", "unavailable",
        "cancelled", "exception",
    }),
    "supplier_confirmed": frozenset({
        "customer_approval_required", "payment_pending", "paid",
        "purchase_confirmed", "cancelled", "exception",
    }),
    "customer_approval_required": frozenset({
        "payment_pending", "paid", "supplier_confirmed", "unavailable",
        "cancelled", "exception",
    }),
    "payment_pending": frozenset({
        "paid", "cancelled", "exception", "unavailable",
    }),
    "paid": frozenset({
        "availability_check", "supplier_rfq", "supplier_confirmed",
        "customer_approval_required", "purchase_confirmed",
        "ready_for_delivery", "store_pickup_ready", "awaiting_receipt",
        "exception", "unavailable", "cancelled",
    }),
    "purchase_confirmed": frozenset({
        "awaiting_receipt", "ready_for_delivery", "exception", "cancelled",
    }),
    "awaiting_receipt": frozenset({
        "ready_for_delivery", "store_pickup_ready", "exception", "cancelled",
    }),
    "ready_for_delivery": frozenset({
        "shipping_created", "store_pickup_ready", "exception", "cancelled",
    }),
    "shipping_created": frozenset({
        "delivered", "completed", "exception",
    }),
    "delivered": frozenset({"completed", "exception"}),
    "store_pickup_ready": frozenset({"completed", "exception", "cancelled"}),
    "completed": frozenset(),
    "unavailable": frozenset({"exception", "cancelled"}),
    "cancelled": frozenset(),
    "exception": frozenset({
        "availability_check", "supplier_rfq", "payment_pending", "paid",
        "cancelled", "unavailable",
    }),
}

SHOPIFY_PAID_STATUSES = frozenset({
    "paid", "partially_paid", "partially_refunded",
})
