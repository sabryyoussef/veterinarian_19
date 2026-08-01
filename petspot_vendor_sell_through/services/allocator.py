# -*- coding: utf-8 -*-
"""Allocate completed outgoing sales to receipt layers (lot or FIFO)."""

from odoo.tools import float_compare, float_is_zero

from .uom_util import convert_qty, PAYABLE_STATUSES
from .rebuild import _safe_ctx, recompute_bill_metrics


def _sys_env(env):
    """System mutations for VST rows — never call from viewer read paths.

    Odoo 19: Environment has no .with_context(); pass context via env(...).
    """
    ctx = dict(env.context)
    ctx.update(_safe_ctx())
    return env(context=ctx, su=True)


def allocate_outgoing_move(env, move):
    """Allocate a done customer/POS outgoing move to layers. Idempotent."""
    move.ensure_one()
    if move.state != "done":
        return
    if not _is_customer_or_pos_sale(move):
        return
    if move.location_id.usage != "internal" or move.location_dest_id.usage not in ("customer", "production"):
        if not _is_pos_move(move):
            return

    Allocation = _sys_env(env)["petspot.vendor.sell.through.allocation"]
    prior = Allocation.with_context(active_test=False).search(
        [
            ("outgoing_move_id", "=", move.id),
            ("source_kind", "=", "system"),
        ]
    )
    returns = Allocation.with_context(active_test=False).search(
        [("reverses_allocation_id", "in", prior.ids)]
    )
    layers_to_refresh = (prior | returns).mapped("layer_id")
    # Supersede: deactivate rather than unlink when possible (preserves audit ids if reactivated);
    # hard-unlink inactive duplicates of the same move to keep invariants simple.
    returns.unlink()
    prior.unlink()
    if layers_to_refresh:
        layers_to_refresh._recompute_allocated()

    bills_touched = env["account.move"]
    for ml in move.move_line_ids:
        bills_touched |= _allocate_move_line(env, move, ml)

    for bill in bills_touched:
        recompute_bill_metrics(env, bill)


def _is_pos_move(move):
    picking = move.picking_id
    return bool(picking) and "pos_order_id" in picking._fields and bool(picking.pos_order_id)


def _is_customer_or_pos_sale(move):
    if move.location_dest_id.usage == "customer":
        return True
    if _is_pos_move(move):
        return True
    return False


def _allocate_move_line(env, move, ml):
    product = ml.product_id
    if not product or not product.is_storable:
        return env["account.move"]
    base_uom = product.uom_id
    qty = convert_qty(ml.product_uom_id, ml.quantity, base_uom, raise_if_failure=False)
    if qty is None or float_is_zero(qty, precision_rounding=base_uom.rounding):
        return env["account.move"]

    Layer = _sys_env(env)["petspot.vendor.sell.through.layer"]
    Allocation = _sys_env(env)["petspot.vendor.sell.through.allocation"]

    domain = [
        ("product_id", "=", product.id),
        ("company_id", "=", move.company_id.id),
        ("source_kind", "=", "receipt"),
        ("confidence", "in", list(PAYABLE_STATUSES | {"exact_lot", "exact_fifo"})),
    ]
    if ml.lot_id:
        domain.append(("lot_id", "=", ml.lot_id.id))
        status = "exact_lot"
    else:
        domain.append(("lot_id", "=", False))
        status = "exact_fifo"

    layers = Layer.search(domain, order="receipt_date asc, incoming_move_line_id asc, id asc")
    if layers:
        layers.lock_for_update()
    remaining = qty
    bills = env["account.move"]
    for layer in layers:
        if float_is_zero(remaining, precision_rounding=base_uom.rounding):
            break
        free = layer.remaining_qty_base
        if float_compare(free, 0.0, precision_rounding=base_uom.rounding) <= 0:
            continue
        take = min(remaining, free)
        already_ml = sum(
            Allocation.search(
                [
                    ("outgoing_move_line_id", "=", ml.id),
                    ("active", "=", True),
                    ("is_return", "=", False),
                ]
            ).mapped("qty_base")
        )
        room = qty - already_ml
        if float_compare(room, 0.0, precision_rounding=base_uom.rounding) <= 0:
            break
        take = min(take, room)
        Allocation.create(
            {
                "layer_id": layer.id,
                "company_id": move.company_id.id,
                "product_id": product.id,
                "vendor_bill_id": layer.vendor_bill_id.id,
                "vendor_bill_line_id": layer.vendor_bill_line_id.id,
                "outgoing_move_id": move.id,
                "outgoing_move_line_id": ml.id,
                "outgoing_picking_id": move.picking_id.id if move.picking_id else False,
                "lot_id": ml.lot_id.id if ml.lot_id else False,
                "qty_base": take,
                "status": status,
                "source_kind": "system",
                "is_return": False,
            }
        )
        layer._recompute_allocated()
        bills |= layer.vendor_bill_id
        remaining -= take

    return bills


def reverse_customer_return(env, return_move):
    """Customer return: reverse original source allocations (not unrelated negative FIFO)."""
    return_move.ensure_one()
    if return_move.state != "done":
        return
    if return_move.location_id.usage != "customer" or return_move.location_dest_id.usage != "internal":
        return

    Allocation = _sys_env(env)["petspot.vendor.sell.through.allocation"]
    bills = env["account.move"]
    prior_returns = Allocation.with_context(active_test=False).search(
        [
            ("outgoing_move_id", "=", return_move.id),
            ("source_kind", "=", "system"),
            ("is_return", "=", True),
        ]
    )
    layers_to_refresh = prior_returns.mapped("layer_id")
    prior_returns.unlink()
    if layers_to_refresh:
        layers_to_refresh._recompute_allocated()
    for ml in return_move.move_line_ids:
        product = ml.product_id
        if not product:
            continue
        base_uom = product.uom_id
        qty = convert_qty(ml.product_uom_id, ml.quantity, base_uom, raise_if_failure=False)
        if qty is None or float_is_zero(qty, precision_rounding=base_uom.rounding):
            continue
        domain = [
            ("product_id", "=", product.id),
            ("active", "=", True),
            ("is_return", "=", False),
            ("status", "in", list(PAYABLE_STATUSES)),
            ("company_id", "=", return_move.company_id.id),
        ]
        if ml.lot_id:
            domain.append(("lot_id", "=", ml.lot_id.id))
        originals = Allocation.search(domain, order="id desc")
        if originals:
            originals.lock_for_update()
        remaining = qty
        for orig in originals:
            if float_is_zero(remaining, precision_rounding=base_uom.rounding):
                break
            already_rev = sum(
                Allocation.search(
                    [
                        ("reverses_allocation_id", "=", orig.id),
                        ("active", "=", True),
                    ]
                ).mapped("qty_base")
            )
            free = orig.qty_base - already_rev
            if float_compare(free, 0.0, precision_rounding=base_uom.rounding) <= 0:
                continue
            take = min(remaining, free)
            Allocation.create(
                {
                    "layer_id": orig.layer_id.id,
                    "company_id": return_move.company_id.id,
                    "product_id": product.id,
                    "vendor_bill_id": orig.vendor_bill_id.id,
                    "vendor_bill_line_id": orig.vendor_bill_line_id.id,
                    "outgoing_move_id": return_move.id,
                    "outgoing_move_line_id": ml.id,
                    "outgoing_picking_id": return_move.picking_id.id if return_move.picking_id else False,
                    "lot_id": ml.lot_id.id if ml.lot_id else False,
                    "qty_base": take,
                    "status": orig.status,
                    "source_kind": "system",
                    "is_return": True,
                    "reverses_allocation_id": orig.id,
                }
            )
            orig.layer_id._recompute_allocated()
            bills |= orig.vendor_bill_id
            remaining -= take

    for bill in bills:
        recompute_bill_metrics(env, bill)


def rebuild_product_allocations(env, product, company):
    """Full re-allocate done outgoing moves for a product (idempotent rebuild)."""
    Move = env["stock.move"]
    moves = Move.search(
        [
            ("product_id", "=", product.id),
            ("company_id", "=", company.id),
            ("state", "=", "done"),
            ("location_id.usage", "=", "internal"),
            ("location_dest_id.usage", "=", "customer"),
        ],
        order="date asc, id asc",
    )
    if "pos_order_id" in env["stock.picking"]._fields:
        pos_moves = Move.search(
            [
                ("product_id", "=", product.id),
                ("company_id", "=", company.id),
                ("state", "=", "done"),
                ("picking_id.pos_order_id", "!=", False),
            ],
            order="date asc, id asc",
        )
        moves |= pos_moves
    for move in moves:
        allocate_outgoing_move(env, move)

    return_moves = Move.search(
        [
            ("product_id", "=", product.id),
            ("company_id", "=", company.id),
            ("state", "=", "done"),
            ("location_id.usage", "=", "customer"),
            ("location_dest_id.usage", "=", "internal"),
        ],
        order="date asc, id asc",
    )
    for move in return_moves:
        reverse_customer_return(env, move)


def full_rebuild_bill(env, bill, system_event=False):
    """Rebuild layers then re-allocate related product outgoings, then metrics.

    Destructive system-row changes run via sudo inside rebuild/allocate.
    Callers that are user actions must enforce Inventory allocation manager ACL first.
    """
    from .rebuild import rebuild_bill_layers

    if not system_event:
        # Defense in depth for non-system callers
        if not env.su and not env.user.has_group("petspot_vendor_sell_through.group_vst_allocation_manager"):
            from odoo.exceptions import AccessError

            raise AccessError("Only Inventory allocation managers may rebuild sell-through allocations.")

    rebuild_bill_layers(env, bill)
    products = bill.invoice_line_ids.mapped("product_id").filtered(lambda p: p.is_storable)
    for product in products:
        rebuild_product_allocations(env, product, bill.company_id)
    # Invoice-derived commercial residual (after stock), capped by receipt remaining
    from .invoice_commercial import allocate_invoice_commercial_for_bill

    allocate_invoice_commercial_for_bill(env, bill, dry_run=False)
    recompute_bill_metrics(env, bill)
