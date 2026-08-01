# -*- coding: utf-8 -*-
"""Invoice-derived commercial sell-through allocation (deduped vs stock)."""

from odoo import fields
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero

from .uom_util import PAYABLE_STATUSES, convert_qty, DEFAULT_INVOICE_CUTOFF
from .rebuild import _safe_ctx, recompute_bill_metrics, _tax_ratio


REASON_WITHOUT_DELIVERY = "POSTED_INVOICE_WITHOUT_DONE_CUSTOMER_DELIVERY"
REASON_PARTIAL_RESIDUAL = "POSTED_INVOICE_PARTIAL_DELIVERY_RESIDUAL"
BLOCKED_UOM = "BLOCKED_UOM_INCONSISTENCY"
BLOCKED_SETTLED = "BLOCKED_SETTLED_REFUND_REQUIRES_MANUAL"


def _sys_env(env):
    ctx = dict(env.context)
    ctx.update(_safe_ctx())
    return env(context=ctx, su=True)


def get_cutoff_date(env):
    raw = env["ir.config_parameter"].sudo().get_param(
        "petspot_vendor_sell_through.invoice_commercial_cutoff",
        DEFAULT_INVOICE_CUTOFF,
    )
    return fields.Date.to_date(raw)


def _source_key_for_invoice_line(invoice_line):
    return "inv_line:%s:product:%s" % (invoice_line.id, invoice_line.product_id.id)


def _sale_line_for_invoice_line(invoice_line):
    if "sale_line_ids" in invoice_line._fields and invoice_line.sale_line_ids:
        return invoice_line.sale_line_ids[:1]
    return invoice_line.env["sale.order.line"]


def _done_customer_moves_for_sale_line(env, sale_line, product):
    if not sale_line:
        return env["stock.move"]
    return env["stock.move"].search(
        [
            ("sale_line_id", "=", sale_line.id),
            ("product_id", "=", product.id),
            ("state", "=", "done"),
            ("location_id.usage", "=", "internal"),
            ("location_dest_id.usage", "=", "customer"),
        ]
    )


def _stock_counted_qty_base(env, product, company, sale_line, invoice_line, moves):
    """Qty already counted by the stock allocator for the same commercial transaction."""
    Allocation = env["petspot.vendor.sell.through.allocation"]
    base_uom = product.uom_id
    total = 0.0
    if moves:
        allocs = Allocation.search(
            [
                ("outgoing_move_id", "in", moves.ids),
                ("product_id", "=", product.id),
                ("company_id", "=", company.id),
                ("source_kind", "=", "system"),
                ("active", "=", True),
                ("is_return", "=", False),
            ]
        )
        total += sum(allocs.mapped("qty_base"))
        returns = Allocation.search(
            [
                ("outgoing_move_id", "in", moves.ids),
                ("product_id", "=", product.id),
                ("company_id", "=", company.id),
                ("source_kind", "=", "system"),
                ("active", "=", True),
                ("is_return", "=", True),
            ]
        )
        total -= sum(returns.mapped("qty_base"))
        return max(0.0, total)

    # Fallback relational: SO line → system allocs on moves with that sale_line
    if sale_line:
        move_domain = [
            ("sale_line_id", "=", sale_line.id),
            ("product_id", "=", product.id),
            ("state", "=", "done"),
            ("location_dest_id.usage", "=", "customer"),
        ]
        linked_moves = env["stock.move"].search(move_domain)
        if linked_moves:
            return _stock_counted_qty_base(env, product, company, sale_line, invoice_line, linked_moves)

    return 0.0


def _closed_corrective_loop_ids(env, company):
    """Return (excluded_invoice_ids, excluded_refund_ids) for corrective pairs.

    When an out_invoice reverses an out_refund (bookkeeping correction), both the
    corrective invoice and that refund form a closed zero loop and must not affect
    commercial sell-through. The original commercial invoice remains authoritative.
    """
    correctives = env["account.move"].search(
        [
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
            ("company_id", "=", company.id),
            ("reversed_entry_id", "!=", False),
        ]
    )
    excluded_inv = set()
    excluded_ref = set()
    for inv in correctives:
        refund = inv.reversed_entry_id
        if refund and refund.move_type == "out_refund" and refund.state == "posted":
            excluded_inv.add(inv.id)
            excluded_ref.add(refund.id)
    return excluded_inv, excluded_ref


def _refund_qty_base_for_invoice_line(env, invoice_line, product, excluded_refund_ids=None):
    """Net posted credit-note qty reversing this invoice line (base UoM)."""
    excluded_refund_ids = excluded_refund_ids or set()
    base_uom = product.uom_id
    refund_qty = 0.0
    refund_lines = env["account.move.line"]
    invoice = invoice_line.move_id

    refunds = env["account.move"].search(
        [
            ("move_type", "=", "out_refund"),
            ("state", "=", "posted"),
            ("company_id", "=", invoice.company_id.id),
            ("reversed_entry_id", "=", invoice.id),
        ]
    )
    if excluded_refund_ids:
        refunds = refunds.filtered(lambda r: r.id not in excluded_refund_ids)
    for refund in refunds:
        for rl in refund.invoice_line_ids.filtered(
            lambda l: l.product_id == product and l.display_type not in ("line_section", "line_note")
        ):
            q = convert_qty(rl.product_uom_id or base_uom, rl.quantity, base_uom, raise_if_failure=False)
            if q is None:
                raise UserError("%s: cannot convert refund UoM for %s" % (BLOCKED_UOM, product.display_name))
            refund_qty += q
            refund_lines |= rl

    if "reversed_invoice_line_id" in env["account.move.line"]._fields:
        extra_domain = [
            ("reversed_invoice_line_id", "=", invoice_line.id),
            ("move_id.state", "=", "posted"),
            ("move_id.move_type", "=", "out_refund"),
            ("product_id", "=", product.id),
        ]
        if excluded_refund_ids:
            extra_domain.append(("move_id", "not in", list(excluded_refund_ids)))
        extra = env["account.move.line"].search(extra_domain)
        for rl in extra - refund_lines:
            q = convert_qty(rl.product_uom_id or base_uom, rl.quantity, base_uom, raise_if_failure=False)
            if q is None:
                raise UserError("%s: cannot convert refund UoM for %s" % (BLOCKED_UOM, product.display_name))
            refund_qty += q
            refund_lines |= rl

    return refund_qty, refund_lines


def discover_invoice_candidates(env, product, company, cutoff_date=None):
    """Yield candidate dicts for posted customer invoice lines of ``product``."""
    cutoff = cutoff_date or get_cutoff_date(env)
    MoveLine = env["account.move.line"]
    excluded_inv, excluded_ref = _closed_corrective_loop_ids(env, company)
    domain = [
        ("product_id", "=", product.id),
        ("move_id.move_type", "=", "out_invoice"),
        ("move_id.state", "=", "posted"),
        ("move_id.company_id", "=", company.id),
        ("move_id.invoice_date", "<=", cutoff),
        ("display_type", "not in", ("line_section", "line_note")),
        ("quantity", ">", 0),
    ]
    if excluded_inv:
        domain.append(("move_id", "not in", list(excluded_inv)))
    lines = MoveLine.search(domain, order="date asc, id asc")
    base_uom = product.uom_id
    results = []
    for line in lines:
        qty_doc = line.quantity
        uom = line.product_uom_id or base_uom
        qty_base = convert_qty(uom, qty_doc, base_uom, raise_if_failure=False)
        if qty_base is None:
            results.append(
                {
                    "blocked": BLOCKED_UOM,
                    "invoice_line": line,
                    "product": product,
                }
            )
            continue
        refund_base, refund_lines = _refund_qty_base_for_invoice_line(
            env, line, product, excluded_refund_ids=excluded_ref
        )
        net_commercial = max(0.0, qty_base - refund_base)
        sale_line = _sale_line_for_invoice_line(line)
        moves = _done_customer_moves_for_sale_line(env, sale_line, product)
        stock_counted = _stock_counted_qty_base(env, product, company, sale_line, line, moves)
        # Cap stock counted at net commercial for this line
        stock_counted = min(stock_counted, net_commercial)
        invoice_only = max(0.0, net_commercial - stock_counted)
        reason = REASON_PARTIAL_RESIDUAL if stock_counted > 0 else REASON_WITHOUT_DELIVERY
        results.append(
            {
                "blocked": False,
                "invoice_line": line,
                "invoice": line.move_id,
                "product": product,
                "qty_original": qty_doc,
                "uom_original": uom,
                "qty_base": qty_base,
                "qty_refunded_base": refund_base,
                "refund_lines": refund_lines,
                "net_commercial": net_commercial,
                "stock_counted": stock_counted,
                "invoice_only": invoice_only,
                "sale_line": sale_line,
                "moves": moves,
                "reason": reason,
                "invoice_date": line.move_id.invoice_date,
                "source_key": _source_key_for_invoice_line(line),
                "cutoff": cutoff,
            }
        )
    return results


def _eligible_receipt_layers(env, product, company):
    Layer = _sys_env(env)["petspot.vendor.sell.through.layer"]
    return Layer.search(
        [
            ("product_id", "=", product.id),
            ("company_id", "=", company.id),
            ("source_kind", "=", "receipt"),
            ("confidence", "in", list(PAYABLE_STATUSES | {"exact_lot", "exact_fifo"})),
        ],
        order="receipt_date asc, incoming_move_line_id asc, id asc",
    )


def _upsert_commercial_source(env, cand, dry_run=False):
    Source = _sys_env(env)["petspot.vendor.sell.through.commercial.source"]
    existing = Source.search([("source_key", "=", cand["source_key"])], limit=1)
    vals = {
        "company_id": cand["invoice"].company_id.id,
        "product_id": cand["product"].id,
        "customer_invoice_id": cand["invoice"].id,
        "customer_invoice_line_id": cand["invoice_line"].id,
        "refund_line_ids": [(6, 0, cand["refund_lines"].ids)],
        "sale_order_line_id": cand["sale_line"].id if cand["sale_line"] else False,
        "stock_move_ids": [(6, 0, cand["moves"].ids)],
        "qty_original": cand["qty_original"],
        "uom_original_id": cand["uom_original"].id,
        "qty_base": cand["qty_base"],
        "qty_stock_counted_base": cand["stock_counted"],
        "qty_invoice_only_base": cand["invoice_only"],
        "qty_refunded_base": cand["qty_refunded_base"],
        "invoice_date": cand["invoice_date"],
        "cutoff_date": cand["cutoff"],
        "source_key": cand["source_key"],
        "reason": cand["reason"],
        "currency_id": cand["invoice"].currency_id.id,
        "state": "zero" if float_is_zero(cand["invoice_only"], precision_digits=6) else "draft",
    }
    if dry_run:
        # Read-only proposal: return existing or a non-persisted NewId record
        if existing:
            return existing
        return Source.new(vals)

    if existing:
        existing.write(vals)
        return existing
    return Source.create(vals)


def _allocate_source_to_layers(env, source, qty_base, dry_run=False):
    """Allocate invoice-only qty onto oldest eligible receipt layers. Returns (allocated_qty, amount, bills)."""
    if float_is_zero(qty_base, precision_digits=6):
        return 0.0, 0.0, env["account.move"]

    product = source.product_id
    company = source.company_id
    base_uom = product.uom_id
    layers = _eligible_receipt_layers(env, product, company)
    Allocation = _sys_env(env)["petspot.vendor.sell.through.allocation"]
    remaining = qty_base
    allocated = 0.0
    amount = 0.0
    bills = env["account.move"]

    # Remove prior invoice allocations for this source (idempotent rebuild)
    prior = Allocation.search([("commercial_source_id", "=", source.id)])
    prior_layers = prior.mapped("layer_id")
    if prior and not dry_run:
        prior.unlink()
        if prior_layers:
            prior_layers._recompute_allocated()
            layers = _eligible_receipt_layers(env, product, company)
    if not dry_run:
        source.write(
            {
                "qty_bill_uom": 0.0,
                "vendor_bill_id": False,
                "vendor_bill_line_id": False,
                "supplier_id": False,
                "eligible_amount": 0.0,
            }
        )

    for layer in layers:
        if float_is_zero(remaining, precision_rounding=base_uom.rounding):
            break
        free = layer.remaining_qty_base
        if float_compare(free, 0.0, precision_rounding=base_uom.rounding) <= 0:
            continue
        take = min(remaining, free)
        bill_line = layer.vendor_bill_line_id
        bill_uom = bill_line.product_uom_id or base_uom
        qty_bill = convert_qty(base_uom, take, bill_uom, raise_if_failure=False)
        if qty_bill is None:
            raise UserError(
                "%s: cannot convert %s from %s to bill UoM %s"
                % (BLOCKED_UOM, product.display_name, base_uom.display_name, bill_uom.display_name)
            )
        line_amount = take * layer.unit_cost_base * (1.0 + (layer.tax_ratio or 0.0))
        if dry_run:
            allocated += take
            amount += line_amount
            remaining -= take
            bills |= layer.vendor_bill_id
            continue

        Allocation.create(
            {
                "company_id": company.id,
                "layer_id": layer.id,
                "product_id": product.id,
                "vendor_bill_id": layer.vendor_bill_id.id,
                "vendor_bill_line_id": bill_line.id,
                "qty_base": take,
                "status": "approved_invoice",
                "source_kind": "invoice",
                "is_return": False,
                "evidence_ref": source.customer_invoice_id.name,
                "reason": source.reason,
                "approved_by_id": env.user.id,
                "approved_date": fields.Datetime.now(),
                "commercial_source_id": source.id,
                "customer_invoice_id": source.customer_invoice_id.id,
                "customer_invoice_line_id": source.customer_invoice_line_id.id,
                "sale_order_line_id": source.sale_order_line_id.id if source.sale_order_line_id else False,
                "source_key": "%s:layer:%s" % (source.source_key, layer.id),
            }
        )
        layer._recompute_allocated()
        source.write(
            {
                "supplier_id": layer.vendor_id.id,
                "vendor_bill_id": layer.vendor_bill_id.id,
                "vendor_bill_line_id": bill_line.id,
                "bill_uom_id": bill_uom.id,
                "qty_bill_uom": (source.qty_bill_uom or 0.0) + qty_bill,
            }
        )
        allocated += take
        amount += line_amount
        remaining -= take
        bills |= layer.vendor_bill_id

    return allocated, amount, bills


def allocate_invoice_commercial_for_product(env, product, company, cutoff_date=None, dry_run=False):
    """Discover + allocate invoice-only commercial qty for one product. Idempotent."""
    if not product or not product.is_storable:
        return {"sources": [], "allocated_qty_base": 0.0, "eligible_amount": 0.0, "blocked": []}

    candidates = discover_invoice_candidates(env, product, company, cutoff_date=cutoff_date)
    report = {"sources": [], "allocated_qty_base": 0.0, "eligible_amount": 0.0, "blocked": []}
    bills_touched = env["account.move"]
    seen_keys = set()

    # Drop stale sources for this product (e.g. corrective invoices now excluded)
    if not dry_run:
        Source = _sys_env(env)["petspot.vendor.sell.through.commercial.source"]
        Allocation = _sys_env(env)["petspot.vendor.sell.through.allocation"]
        active_keys = {c["source_key"] for c in candidates if not c.get("blocked")}
        stale = Source.search(
            [
                ("product_id", "=", product.id),
                ("company_id", "=", company.id),
                ("source_key", "not in", list(active_keys) or [""]),
            ]
        )
        if stale:
            stale_allocs = Allocation.search([("commercial_source_id", "in", stale.ids)])
            layers = stale_allocs.mapped("layer_id")
            bills_touched |= stale_allocs.mapped("vendor_bill_id")
            stale_allocs.unlink()
            if layers:
                layers._recompute_allocated()
            stale.write({"state": "reversed", "qty_invoice_only_base": 0.0, "eligible_amount": 0.0, "active": False})

    for cand in candidates:
        if cand.get("blocked"):
            report["blocked"].append(
                {
                    "invoice_line_id": cand["invoice_line"].id,
                    "reason": cand["blocked"],
                    "product_id": product.id,
                }
            )
            continue
        source = _upsert_commercial_source(env, cand, dry_run=dry_run)
        qty = cand["invoice_only"]
        if float_is_zero(qty, precision_digits=6):
            if not dry_run:
                # Clear stale allocations when refunds wiped eligibility
                Allocation = _sys_env(env)["petspot.vendor.sell.through.allocation"]
                stale = Allocation.search([("commercial_source_id", "=", source.id)])
                layers = stale.mapped("layer_id")
                stale.unlink()
                if layers:
                    layers._recompute_allocated()
                source.write({"state": "zero", "eligible_amount": 0.0, "qty_bill_uom": 0.0})
            report["sources"].append({"source_id": source.id, "qty": 0.0, "key": source.source_key})
            continue

        allocated, amount, bills = _allocate_source_to_layers(env, source, qty, dry_run=dry_run)
        currency = cand["invoice"].currency_id
        amount = currency.round(amount) if currency else amount
        if not dry_run:
            source.write(
                {
                    "state": "applied" if allocated > 0 else "zero",
                    "eligible_amount": amount,
                    "qty_invoice_only_base": qty,
                }
            )
        report["sources"].append(
            {
                "source_id": source.id if source.id else False,
                "source_key": cand["source_key"],
                "invoice": cand["invoice"].name,
                "invoice_line_id": cand["invoice_line"].id,
                "qty_invoice_only_base": qty,
                "qty_stock_counted_base": cand["stock_counted"],
                "qty_refunded_base": cand["qty_refunded_base"],
                "allocated_qty_base": allocated,
                "eligible_amount": amount,
                "reason": cand["reason"],
            }
        )
        report["allocated_qty_base"] += allocated
        report["eligible_amount"] += amount
        bills_touched |= bills

    if not dry_run:
        for bill in bills_touched:
            recompute_bill_metrics(env, bill)
    return report


def allocate_invoice_commercial_for_bill(env, bill, cutoff_date=None, dry_run=False):
    """Run invoice commercial allocation for all storable products on a vendor bill."""
    bill.ensure_one()
    products = bill.invoice_line_ids.mapped("product_id").filtered(lambda p: p.is_storable)
    combined = {"sources": [], "allocated_qty_base": 0.0, "eligible_amount": 0.0, "blocked": []}
    for product in products:
        part = allocate_invoice_commercial_for_product(
            env, product, bill.company_id, cutoff_date=cutoff_date, dry_run=dry_run
        )
        combined["sources"].extend(part["sources"])
        combined["allocated_qty_base"] += part["allocated_qty_base"]
        combined["eligible_amount"] += part["eligible_amount"]
        combined["blocked"].extend(part["blocked"])
    if not dry_run:
        recompute_bill_metrics(env, bill)
    return combined


def backfill_company(env, company, cutoff_date=None, dry_run=True, product_ids=None):
    """Company-wide invoice commercial backfill (default dry-run)."""
    Product = env["product.product"]
    if product_ids:
        products = Product.browse(product_ids).exists().filtered(lambda p: p.is_storable)
    else:
        # Products that appear on posted vendor bills
        bill_lines = env["account.move.line"].search(
            [
                ("move_id.move_type", "=", "in_invoice"),
                ("move_id.state", "=", "posted"),
                ("move_id.company_id", "=", company.id),
                ("product_id", "!=", False),
            ]
        )
        products = bill_lines.mapped("product_id").filtered(lambda p: p.is_storable)

    combined = {
        "dry_run": dry_run,
        "cutoff": str(cutoff_date or get_cutoff_date(env)),
        "sources": [],
        "allocated_qty_base": 0.0,
        "eligible_amount": 0.0,
        "blocked": [],
        "by_product": {},
    }
    for product in products:
        part = allocate_invoice_commercial_for_product(
            env, product, company, cutoff_date=cutoff_date, dry_run=dry_run
        )
        combined["sources"].extend(part["sources"])
        combined["allocated_qty_base"] += part["allocated_qty_base"]
        combined["eligible_amount"] += part["eligible_amount"]
        combined["blocked"].extend(part["blocked"])
        combined["by_product"][product.id] = {
            "code": product.default_code,
            "name": product.display_name,
            "allocated_qty_base": part["allocated_qty_base"],
            "eligible_amount": part["eligible_amount"],
            "sources": part["sources"],
        }
        if part["blocked"]:
            raise UserError(
                "%s for product %s (invoice line(s) %s)"
                % (
                    BLOCKED_UOM,
                    product.display_name,
                    ", ".join(str(b["invoice_line_id"]) for b in part["blocked"]),
                )
            )
    return combined
