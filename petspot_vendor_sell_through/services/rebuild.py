# -*- coding: utf-8 -*-
"""Rebuild receipt layers for vendor bills and recompute sell-through metrics."""

from odoo import fields
from odoo.tools import float_compare, float_is_zero, float_round

from .uom_util import convert_qty


def _safe_ctx():
    return {
        "mail_notrack": True,
        "tracking_disable": True,
        "mail_create_nolog": True,
        "mail_create_nosubscribe": True,
    }


def rebuild_bill_layers(env, bill):
    """Create/update receipt layers for a posted vendor bill. Idempotent."""
    bill.ensure_one()
    if bill.move_type not in ("in_invoice", "in_refund") or bill.state != "posted":
        return env["petspot.vendor.sell.through.layer"]

    Layer = env["petspot.vendor.sell.through.layer"].with_context(**_safe_ctx())
    Allocation = env["petspot.vendor.sell.through.allocation"].with_context(**_safe_ctx())
    existing = Layer.search([("vendor_bill_id", "=", bill.id)])
    # Preserve approved/estimated legacy layers; remove system-managed ones then recreate.
    # Allocations RESTRICT layer delete — clear system-layer allocations first.
    system = existing.filtered(lambda l: l.source_kind == "receipt")
    if system:
        Allocation.search([("layer_id", "in", system.ids)]).unlink()
        system.unlink()

    created = Layer
    for line in bill.invoice_line_ids.filtered(lambda l: l.display_type not in ("line_section", "line_note") and l.product_id and l.product_id.is_storable):
        created |= _layers_for_bill_line(env, bill, line)
    return created


def _layers_for_bill_line(env, bill, line):
    Layer = env["petspot.vendor.sell.through.layer"].with_context(**_safe_ctx())
    product = line.product_id
    base_uom = product.uom_id
    purchase_uom = line.product_uom_id or base_uom
    billed_base = convert_qty(purchase_uom, line.quantity, base_uom, raise_if_failure=False)
    if billed_base is None:
        # Blocked UoM — create a marker layer with zero qty for visibility
        return Layer.create(
            {
                "company_id": bill.company_id.id,
                "vendor_id": bill.partner_id.id,
                "vendor_bill_id": bill.id,
                "vendor_bill_line_id": line.id,
                "purchase_order_id": line.purchase_line_id.order_id.id if line.purchase_line_id else False,
                "purchase_line_id": line.purchase_line_id.id if line.purchase_line_id else False,
                "product_id": product.id,
                "purchase_uom_id": purchase_uom.id,
                "base_uom_id": base_uom.id,
                "received_qty_base": 0.0,
                "unit_cost_base": 0.0,
                "unit_cost_purchase": line.price_unit,
                "currency_id": bill.currency_id.id,
                "tax_ratio": _tax_ratio(line),
                "confidence": "blocked_uom",
                "source_kind": "receipt",
                "name": "Blocked UoM: %s" % product.display_name,
            }
        )

    unit_cost_purchase = line.price_unit
    # Cost per base UoM: purchase cost / conversion factor
    factor = convert_qty(purchase_uom, 1.0, base_uom, raise_if_failure=False) or 1.0
    unit_cost_base = unit_cost_purchase / factor if factor else 0.0
    tax_ratio = _tax_ratio(line)

    pol = line.purchase_line_id
    if not pol:
        # No PO link — cannot create receipt-backed layers
        return Layer

    # Done incoming move lines for this PO line
    MoveLine = env["stock.move.line"]
    mls = MoveLine.search(
        [
            ("move_id.purchase_line_id", "=", pol.id),
            ("state", "=", "done"),
            ("move_id.location_dest_id.usage", "=", "internal"),
            ("move_id.location_id.usage", "=", "supplier"),
        ],
        order="date asc, id asc",
    )

    remaining = billed_base
    # Qty already layered on other bills for same receipt move lines
    created = Layer
    for ml in mls:
        if float_is_zero(remaining, precision_rounding=base_uom.rounding):
            break
        ml_base = convert_qty(ml.product_uom_id, ml.quantity, base_uom, raise_if_failure=False)
        if ml_base is None:
            continue
        # Supplier returns against this incoming move
        returned = _supplier_return_qty_base(env, ml, base_uom)
        available_receipt = ml_base - returned
        already = sum(
            Layer.search(
                [
                    ("incoming_move_line_id", "=", ml.id),
                    ("vendor_bill_id", "!=", bill.id),
                    ("source_kind", "=", "receipt"),
                ]
            ).mapped("received_qty_base")
        )
        free = available_receipt - already
        if float_compare(free, 0.0, precision_rounding=base_uom.rounding) <= 0:
            continue
        take = min(remaining, free)
        confidence = "exact_lot" if ml.lot_id else "exact_fifo"
        created |= Layer.create(
            {
                "company_id": bill.company_id.id,
                "vendor_id": bill.partner_id.id,
                "vendor_bill_id": bill.id,
                "vendor_bill_line_id": line.id,
                "purchase_order_id": pol.order_id.id,
                "purchase_line_id": pol.id,
                "incoming_move_id": ml.move_id.id,
                "incoming_move_line_id": ml.id,
                "product_id": product.id,
                "lot_id": ml.lot_id.id if ml.lot_id else False,
                "purchase_uom_id": purchase_uom.id,
                "base_uom_id": base_uom.id,
                "received_qty_base": take,
                "supplier_return_qty_base": 0.0,
                "unit_cost_base": unit_cost_base,
                "unit_cost_purchase": unit_cost_purchase,
                "currency_id": bill.currency_id.id,
                "tax_ratio": tax_ratio,
                "confidence": confidence,
                "source_kind": "receipt",
                "receipt_date": ml.date or fields.Datetime.now(),
                "name": "%s / %s" % (bill.name, product.default_code or product.display_name),
            }
        )
        remaining -= take

    # If billed more than linked receipts, remaining stays unlayered (unallocated on bill metrics)
    return created


def _tax_ratio(line):
    """Proportional tax per untaxed amount for this line."""
    if float_is_zero(line.price_subtotal, precision_digits=6):
        return 0.0
    tax_amount = line.price_total - line.price_subtotal
    return tax_amount / line.price_subtotal if line.price_subtotal else 0.0


def _supplier_return_qty_base(env, incoming_ml, base_uom):
    """Sum done supplier-return quantities linked to the same purchase line / lot."""
    MoveLine = env["stock.move.line"]
    domain = [
        ("state", "=", "done"),
        ("move_id.location_id.usage", "=", "internal"),
        ("move_id.location_dest_id.usage", "=", "supplier"),
        ("product_id", "=", incoming_ml.product_id.id),
        ("move_id.purchase_line_id", "=", incoming_ml.move_id.purchase_line_id.id),
    ]
    if incoming_ml.lot_id:
        domain.append(("lot_id", "=", incoming_ml.lot_id.id))
    total = 0.0
    for ml in MoveLine.search(domain):
        q = convert_qty(ml.product_uom_id, ml.quantity, base_uom, raise_if_failure=False)
        if q is not None:
            total += q
    return total


def recompute_bill_metrics(env, bill):
    """Refresh stored sell-through metrics on bill and lines. No payments, no notifications."""
    bill.ensure_one()
    if bill.move_type not in ("in_invoice", "in_refund"):
        return
    Allocation = env["petspot.vendor.sell.through.allocation"]
    Layer = env["petspot.vendor.sell.through.layer"]
    from .uom_util import PAYABLE_STATUSES

    total_eligible = 0.0
    total_unallocated = 0.0
    for line in bill.invoice_line_ids.filtered(lambda l: l.display_type not in ("line_section", "line_note") and l.product_id):
        layers = Layer.search([("vendor_bill_line_id", "=", line.id)])
        allocs = Allocation.search([("vendor_bill_line_id", "=", line.id), ("active", "=", True)])
        sold = sum(allocs.filtered(lambda a: a.status in PAYABLE_STATUSES or a.status == "estimated_legacy").mapped("qty_base"))
        sold_payable = sum(allocs.filtered(lambda a: a.status in PAYABLE_STATUSES).mapped("qty_base"))
        returned = sum(allocs.filtered(lambda a: a.is_return).mapped("qty_base"))
        # Net sold for display = sold - returns (returns stored as positive qty with is_return)
        net_sold = sold_payable  # payable allocations already net after return reversals
        # Recalc from layers' remaining tracking
        received = sum(layers.mapped("received_qty_base"))
        billed_base = convert_qty(line.product_uom_id or line.product_id.uom_id, line.quantity, line.product_id.uom_id, raise_if_failure=False)
        if billed_base is None:
            line.write(
                {
                    "vst_billed_qty": line.quantity,
                    "vst_received_qty": 0.0,
                    "vst_sold_qty": 0.0,
                    "vst_return_qty": 0.0,
                    "vst_net_sold_qty": 0.0,
                    "vst_unsold_qty": line.quantity,
                    "vst_unit_cost": line.price_unit,
                    "vst_sold_untaxed": 0.0,
                    "vst_sold_tax": 0.0,
                    "vst_sold_gross": 0.0,
                    "vst_tracking_confidence": "blocked_uom",
                    "vst_source_receipts": "",
                    "vst_source_sales": "",
                }
            )
            continue

        # Eligible monetary from payable allocations
        untaxed = 0.0
        tax = 0.0
        for a in allocs.filtered(lambda a: a.status in PAYABLE_STATUSES and not a.is_return):
            untaxed += a.qty_base * a.layer_id.unit_cost_base
            tax += a.qty_base * a.layer_id.unit_cost_base * a.layer_id.tax_ratio
        for a in allocs.filtered(lambda a: a.status in PAYABLE_STATUSES and a.is_return):
            untaxed -= a.qty_base * a.layer_id.unit_cost_base
            tax -= a.qty_base * a.layer_id.unit_cost_base * a.layer_id.tax_ratio

        currency = bill.currency_id
        untaxed = currency.round(untaxed)
        tax = currency.round(tax)
        gross = currency.round(untaxed + tax)

        # Confidence rollup
        statuses = set(allocs.mapped("status")) | set(layers.mapped("confidence"))
        if "blocked_uom" in statuses:
            conf = "blocked_uom"
        elif statuses & {"exact_lot", "exact_fifo", "approved_legacy", "approved_invoice"}:
            if "exact_lot" in statuses:
                conf = "exact_lot"
            elif "exact_fifo" in statuses:
                conf = "exact_fifo"
            elif "approved_invoice" in statuses:
                conf = "approved_invoice"
            else:
                conf = "approved_legacy"
        elif "estimated_legacy" in statuses:
            conf = "estimated_legacy"
        elif not allocs and layers:
            conf = layers[0].confidence
        else:
            conf = "unallocated"

        receipts = ", ".join(sorted({l.incoming_move_id.reference or l.incoming_move_id.picking_id.name or "" for l in layers if l.incoming_move_id}))
        sales = ", ".join(
            sorted(
                {
                    a.outgoing_move_id.reference
                    or a.outgoing_picking_id.name
                    or (a.customer_invoice_id.name if a.customer_invoice_id else "")
                    or a.evidence_ref
                    or ""
                    for a in allocs
                    if not a.is_return
                }
            )
        )

        allocated_sold = sum(allocs.filtered(lambda a: not a.is_return).mapped("qty_base")) - sum(
            allocs.filtered(lambda a: a.is_return).mapped("qty_base")
        )
        unsold = max(0.0, received - allocated_sold) if received else max(0.0, billed_base - allocated_sold)
        unallocated_gap = max(0.0, billed_base - received)

        line.write(
            {
                "vst_billed_qty": line.quantity,
                "vst_received_qty": convert_qty(line.product_id.uom_id, received, line.product_uom_id or line.product_id.uom_id, raise_if_failure=False) or 0.0,
                "vst_sold_qty": convert_qty(line.product_id.uom_id, allocated_sold, line.product_uom_id or line.product_id.uom_id, raise_if_failure=False) or 0.0,
                "vst_return_qty": convert_qty(line.product_id.uom_id, returned, line.product_uom_id or line.product_id.uom_id, raise_if_failure=False) or 0.0,
                "vst_net_sold_qty": convert_qty(line.product_id.uom_id, max(0.0, allocated_sold), line.product_uom_id or line.product_id.uom_id, raise_if_failure=False) or 0.0,
                "vst_unsold_qty": convert_qty(line.product_id.uom_id, unsold, line.product_uom_id or line.product_id.uom_id, raise_if_failure=False) or 0.0,
                "vst_unit_cost": line.price_unit,
                "vst_sold_untaxed": untaxed,
                "vst_sold_tax": tax,
                "vst_sold_gross": gross,
                "vst_tracking_confidence": conf,
                "vst_source_receipts": receipts[:500],
                "vst_source_sales": sales[:500],
            }
        )
        total_eligible += gross
        total_unallocated += unallocated_gap

    already_paid = bill.amount_total - bill.amount_residual
    eligible = bill.currency_id.round(total_eligible)
    suggested = min(bill.amount_residual, max(0.0, eligible - already_paid))
    suggested = bill.currency_id.round(suggested)

    bill.write(
        {
            "vst_total_bill": bill.amount_total,
            "vst_eligible_amount": eligible,
            "vst_already_paid": bill.currency_id.round(already_paid),
            "vst_suggested_payment": suggested,
            "vst_bill_residual": bill.amount_residual,
            "vst_unallocated_qty": total_unallocated,
            "vst_last_recalculation": fields.Datetime.now(),
        }
    )
