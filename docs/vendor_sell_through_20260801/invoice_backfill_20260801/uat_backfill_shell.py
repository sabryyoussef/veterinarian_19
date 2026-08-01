# -*- coding: utf-8 -*-
"""UAT backfill on Production-shaped clone. Ends with rollback only if DRY fails; apply commits."""
import json
from datetime import datetime

LOGDIR = "/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/docs/vendor_sell_through_20260801/invoice_backfill_20260801"
APPROVED = {
    "APOQ-16": 60.0,
    "VAC-VP8": 3.0,
    "SHP-82-82": 3.0,
}

def _codes(env):
    Product = env["product.product"].with_context(active_test=False)
    out = {}
    for code in list(APPROVED) + ["SIMT-2.5-5", "SIMT-20-40", "REVC-45", "APOQ-3.6"]:
        p = Product.search([("default_code", "=", code)], limit=1)
        if p:
            out[code] = p
    # name matches for loose bill products
    for name, key in [
        ("tenizol", "tenizol"),
        ("Evatri", "evatri"),
        ("flomarbidine", "flomarbidine"),
        ("aquadent", "aquadent"),
        ("Nobivac Rabies", "nobivac_rabies"),
        ("Nobivac DHPPi", "nobivac_dhppi"),
        ("Prednicortex", "prednicortex"),
        ("Pyoderm", "pyoderm"),
        ("Cortavance", "cortavance"),
        ("MULTIBOOST", "multiboost"),
        ("salmon max", "salmon_max"),
        ("vetoplex", "vetoplex"),
        ("aurizon", "aurizon"),
    ]:
        p = Product.search([("name", "ilike", name)], limit=1)
        if p:
            out[key] = p
    return out


def snap_bills(env):
    bills = env["account.move"].search([("move_type", "=", "in_invoice"), ("state", "=", "posted")])
    rows = []
    for b in bills:
        rows.append(
            {
                "id": b.id,
                "name": b.name,
                "partner": b.partner_id.display_name,
                "eligible": b.vst_eligible_amount,
                "suggested": b.vst_suggested_payment,
                "residual": b.amount_residual,
                "allocs": [
                    {
                        "product": a.product_id.default_code or a.product_id.display_name,
                        "qty_base": a.qty_base,
                        "source_kind": a.source_kind,
                        "status": a.status,
                        "invoice": a.customer_invoice_id.name if a.customer_invoice_id else False,
                    }
                    for a in b.vst_allocation_ids.filtered(lambda a: a.active and not a.is_return)
                ],
            }
        )
    return rows


# BEFORE
before = snap_bills(env)
open(LOGDIR + "/08_before_bills.json", "w").write(json.dumps(before, indent=2, default=str))

# Ensure layers exist via rebuild first (stock-only state)
from odoo.addons.petspot_vendor_sell_through.services.allocator import full_rebuild_bill
from odoo.addons.petspot_vendor_sell_through.services.invoice_commercial import (
    backfill_company,
    allocate_invoice_commercial_for_bill,
)

company = env.company
bills = env["account.move"].search([("move_type", "=", "in_invoice"), ("state", "=", "posted")])
for bill in bills:
    full_rebuild_bill(env, bill, system_event=True)

after_rebuild_zero = snap_bills(env)
open(LOGDIR + "/08_after_stock_rebuild.json", "w").write(json.dumps(after_rebuild_zero, indent=2, default=str))

# DRY RUN
dry = backfill_company(env, company, dry_run=True)
open(LOGDIR + "/08_dry_run.json", "w").write(json.dumps(dry, indent=2, default=str))
env.cr.rollback()
print("DRY_RUN_OK", dry.get("allocated_qty_base"), dry.get("eligible_amount"), "sources", len(dry.get("sources") or []))

# Re-open after rollback — need fresh env state; in shell same txn rolled back
# APPLY
for bill in env["account.move"].search([("move_type", "=", "in_invoice"), ("state", "=", "posted")]):
    full_rebuild_bill(env, bill, system_event=True)
applied = backfill_company(env, company, dry_run=False)
open(LOGDIR + "/08_applied.json", "w").write(json.dumps(applied, indent=2, default=str))

# Rebuild x3 drift
snaps = []
for i in range(3):
    for bill in env["account.move"].search([("move_type", "=", "in_invoice"), ("state", "=", "posted")]):
        full_rebuild_bill(env, bill, system_event=True)
    bills_snap = snap_bills(env)
    snaps.append(
        {
            "i": i,
            "eligible_sum": sum(b["eligible"] or 0 for b in bills_snap),
            "alloc_count": sum(len(b["allocs"]) for b in bills_snap),
            "invoice_alloc_qty": sum(
                a["qty_base"]
                for b in bills_snap
                for a in b["allocs"]
                if a["source_kind"] == "invoice"
            ),
        }
    )
open(LOGDIR + "/08_rebuild_x3.json", "w").write(json.dumps(snaps, indent=2))
open(LOGDIR + "/08_after_bills.json", "w").write(json.dumps(snap_bills(env), indent=2, default=str))

# Per-product verification
codes = _codes(env)
per_product = {}
Allocation = env["petspot.vendor.sell.through.allocation"]
Source = env["petspot.vendor.sell.through.commercial.source"]
for code, expected in APPROVED.items():
    p = codes.get(code)
    if not p:
        per_product[code] = {"missing_product": True}
        continue
    inv_alloc = Allocation.search(
        [("product_id", "=", p.id), ("source_kind", "=", "invoice"), ("active", "=", True), ("is_return", "=", False)]
    )
    sys_alloc = Allocation.search(
        [("product_id", "=", p.id), ("source_kind", "=", "system"), ("active", "=", True), ("is_return", "=", False)]
    )
    src = Source.search([("product_id", "=", p.id)])
    per_product[code] = {
        "product_id": p.id,
        "approved": expected,
        "invoice_only_allocated": sum(inv_alloc.mapped("qty_base")),
        "stock_allocated": sum(sys_alloc.mapped("qty_base")),
        "source_invoice_only_sum": sum(src.mapped("qty_invoice_only_base")),
        "source_stock_counted_sum": sum(src.mapped("qty_stock_counted_base")),
        "source_refunded_sum": sum(src.mapped("qty_refunded_base")),
        "match_approved": abs(sum(inv_alloc.mapped("qty_base")) - expected) < 0.01
        or abs(sum(src.mapped("qty_invoice_only_base")) - expected) < 0.01,
    }

# exclusions
for code in ("SIMT-2.5-5", "SIMT-20-40", "REVC-45", "APOQ-3.6"):
    p = codes.get(code)
    if not p:
        continue
    inv_q = sum(
        Allocation.search(
            [("product_id", "=", p.id), ("source_kind", "=", "invoice"), ("active", "=", True)]
        ).mapped("qty_base")
    )
    per_product[code] = {"product_id": p.id, "invoice_allocated": inv_q, "must_be_zero_on_bill_product": code != "APOQ-3.6"}

open(LOGDIR + "/08_per_product.json", "w").write(json.dumps(per_product, indent=2, default=str))

# Source duplicate check
keys = Source.search([]).mapped("source_key")
dup = len(keys) - len(set(keys))
open(LOGDIR + "/08_source_keys.json", "w").write(
    json.dumps({"count": len(keys), "unique": len(set(keys)), "duplicates": dup}, indent=2)
)

# Payment wizard preview (no post)
from odoo.addons.petspot_vendor_sell_through.services.multi_payment import bill_payment_cap, validate_bill_selection

pay_bills = env["account.move"].search(
    [("move_type", "=", "in_invoice"), ("state", "=", "posted"), ("amount_residual", ">", 0)]
).filtered(lambda b: bill_payment_cap(b) > 0)
preview = []
for b in pay_bills:
    preview.append(
        {
            "bill": b.name,
            "partner": b.partner_id.display_name,
            "eligible": b.vst_eligible_amount,
            "cap": bill_payment_cap(b),
            "residual": b.amount_residual,
        }
    )
open(LOGDIR + "/08_payment_preview.json", "w").write(json.dumps(preview, indent=2, default=str))

env.cr.commit()
print("APPLIED_OK")
print("REBUILD_SNAPS", snaps)
print("PER_PRODUCT", json.dumps(per_product, indent=2))
print("DUP_SOURCES", dup)
print("PAY_PREVIEW_BILLS", len(preview))
