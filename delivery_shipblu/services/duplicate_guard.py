# -*- coding: utf-8 -*-
"""Duplicate shipment guard across ShipBlu / Bosta / Egypt Post markers."""

from __future__ import annotations

from odoo import _
from odoo.exceptions import UserError


class DuplicateGuard:
    def __init__(self, env):
        self.env = env

    def assert_can_create_shipblu(self, picking, allow_manager_override=False):
        picking.ensure_one()
        conflicts = []
        if picking.carrier_tracking_ref:
            conflicts.append(_("Picking already has tracking %s") % picking.carrier_tracking_ref)
        if getattr(picking, "shipblu_order_id", False):
            conflicts.append(_("Picking already linked to ShipBlu order %s") % picking.shipblu_order_id)
        if getattr(picking, "bosta_delivery_id", False):
            conflicts.append(_("Picking already has Bosta delivery %s") % picking.bosta_delivery_id)
        # Other ShipBlu shipment on same picking/SO
        Shipment = self.env["shipblu.shipment"].sudo()
        if Shipment.search([("picking_id", "=", picking.id), ("shipblu_order_id", "!=", False)], limit=1):
            conflicts.append(_("A ShipBlu shipment already exists for this picking"))
        if picking.sale_id:
            other = Shipment.search(
                [
                    ("sale_order_id", "=", picking.sale_id.id),
                    ("shipblu_order_id", "!=", False),
                    ("picking_id", "!=", picking.id),
                ],
                limit=1,
            )
            if other:
                conflicts.append(_("Sale order already has ShipBlu shipment %s") % other.name)
            # Bosta shipment model if installed
            if "bosta.shipment" in self.env:
                bosta = self.env["bosta.shipment"].sudo().search(
                    [("sale_order_id", "=", picking.sale_id.id), ("bosta_delivery_id", "!=", False)],
                    limit=1,
                )
                if bosta:
                    conflicts.append(_("Sale order already has Bosta shipment %s") % bosta.name)
        if conflicts:
            msg = _("ShipBlu create blocked — other provider/ownership conflict:\n- ") + "\n- ".join(
                conflicts
            )
            if allow_manager_override and self.env.user.has_group(
                "petspot_shipblu_base.group_shipblu_manager"
            ):
                # Manager must pass context key explicitly
                if self.env.context.get("shipblu_force_create"):
                    return True
            raise UserError(msg)
        return True
