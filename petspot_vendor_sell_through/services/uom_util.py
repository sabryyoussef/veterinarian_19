# -*- coding: utf-8 -*-
from odoo.exceptions import UserError


DEFAULT_INVOICE_CUTOFF = "2026-08-01"


def convert_qty(from_uom, qty, to_uom, raise_if_failure=True):
    """Convert qty using configured Odoo UoM factors only.

    Odoo 19 ``_compute_quantity`` converts any two UoMs via absolute factors even when
    they do not share a reference tree. Sell-through requires a proven common reference;
    otherwise raise ``BLOCKED_UOM_INCONSISTENCY``.
    """
    if not from_uom or not to_uom:
        if raise_if_failure:
            raise UserError("BLOCKED_UOM_INCONSISTENCY: Missing UoM for sell-through conversion.")
        return None
    if from_uom == to_uom:
        return qty
    # Ensure parent_path is populated for newly created UoMs
    if not from_uom.parent_path or not to_uom.parent_path:
        from_uom.flush_recordset(["parent_path", "relative_uom_id", "relative_factor", "factor"])
        to_uom.flush_recordset(["parent_path", "relative_uom_id", "relative_factor", "factor"])
    has_common = True
    if hasattr(from_uom, "_has_common_reference"):
        try:
            has_common = from_uom._has_common_reference(to_uom)
        except Exception:
            has_common = from_uom == to_uom
    else:
        # Fallback: same relative root
        def _root(u):
            cur = u
            while cur.relative_uom_id:
                cur = cur.relative_uom_id
            return cur

        has_common = _root(from_uom) == _root(to_uom)

    if not has_common:
        if raise_if_failure:
            raise UserError(
                "BLOCKED_UOM_INCONSISTENCY: Cannot convert from %s to %s "
                "(no common UoM reference tree)."
                % (from_uom.display_name, to_uom.display_name)
            )
        return None
    try:
        return from_uom._compute_quantity(qty, to_uom, round=False, raise_if_failure=True)
    except Exception:
        if raise_if_failure:
            raise UserError(
                "BLOCKED_UOM_INCONSISTENCY: Blocked UoM conversion from %s to %s. "
                "Configure relative UoMs before allocating."
                % (from_uom.display_name, to_uom.display_name)
            )
        return None


PAYABLE_STATUSES = frozenset({"exact_lot", "exact_fifo", "approved_legacy", "approved_invoice"})
