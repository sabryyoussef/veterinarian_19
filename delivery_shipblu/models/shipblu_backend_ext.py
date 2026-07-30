# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError

from odoo.addons.delivery_shipblu.services.import_service import ImportService
from odoo.addons.petspot_shipblu_base.services.shipblu_client import ShipBluApiError


class ShipBluBackendExt(models.Model):
    _inherit = "shipblu.backend"

    # Merchant portal profile (synced from GET /v1/merchants/)
    merchant_status = fields.Char(readonly=True)
    merchant_van_or_bike = fields.Char(string="Pickup Mode (van/bike)", readonly=True)
    merchant_is_self_signup = fields.Boolean(readonly=True)
    merchant_store_phone = fields.Char(readonly=True)
    merchant_store_email = fields.Char(readonly=True)
    merchant_pickup_fees = fields.Float(readonly=True, digits=(16, 2))
    merchant_pickup_time = fields.Integer(string="Pickup Cutoff Code", readonly=True)
    merchant_wallet_balance = fields.Float(readonly=True, digits=(16, 2))
    merchant_cod_balance = fields.Float(readonly=True, digits=(16, 2))
    merchant_refunds_balance = fields.Float(readonly=True, digits=(16, 2))
    merchant_customer_balance = fields.Float(readonly=True, digits=(16, 2))
    merchant_transfer_days = fields.Char(readonly=True)
    merchant_store_line_1 = fields.Char(readonly=True)
    merchant_store_line_2 = fields.Char(readonly=True)
    merchant_store_zone_id = fields.Integer(readonly=True)
    last_merchant_sync_at = fields.Datetime(readonly=True)

    store_line_1_edit = fields.Char(string="Store Address Line 1")
    store_line_2_edit = fields.Char(string="Store Address Line 2")
    store_zone_id_edit = fields.Integer(string="Store Zone ID")
    store_what3words_edit = fields.Char(string="Store what3words", default="filled.by.odoo")

    def action_import_shipblu_orders(self):
        self.ensure_one()
        result = ImportService(self.env).import_delivery_orders(self)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("ShipBlu Import"),
                "message": result["message"],
                "type": "success",
                "sticky": False,
            },
        }

    def action_sync_tracking(self):
        self.ensure_one()
        result = ImportService(self.env).sync_tracking_batch(self)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("ShipBlu Tracking Sync"),
                "message": result["message"],
                "type": "success",
                "sticky": False,
            },
        }

    def action_sync_coverage(self):
        self.ensure_one()
        result = ImportService(self.env).sync_coverage(self)
        msg = _("Coverage synced — gov=%(g)s cities=%(c)s zones=%(z)s") % {
            "g": result["governorates"],
            "c": result["cities"],
            "z": result["zones"],
        }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": _("ShipBlu Coverage"), "message": msg, "type": "success", "sticky": False},
        }

    def action_import_aux_orders(self):
        self.ensure_one()
        result = ImportService(self.env).import_aux_orders(self)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("ShipBlu Aux Import"),
                "message": str(result),
                "type": "success",
                "sticky": False,
            },
        }

    def action_sync_merchant_profile(self):
        self.ensure_one()
        ImportService(self.env).sync_merchant_profile(self)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("ShipBlu Merchant"),
                "message": _("Synced merchant %(name)s — wallet %(w).2f EGP, pickup=%(p)s")
                % {
                    "name": self.merchant_name or "?",
                    "w": self.merchant_wallet_balance,
                    "p": self.merchant_van_or_bike or "none",
                },
                "type": "success",
                "sticky": False,
            },
        }

    def action_sync_portal_locations(self):
        self.ensure_one()
        result = ImportService(self.env).sync_portal_locations(self)
        msg = _("Locations — pickups=%(p)s returns=%(r)s hubs=%(h)s") % {
            "p": result["pickups"],
            "r": result["return_points"],
            "h": result["warehouses"],
        }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": _("ShipBlu Locations"), "message": msg, "type": "success", "sticky": False},
        }

    def action_push_store_address(self):
        self.ensure_one()
        self.assert_write_allowed("update merchant store address")
        if not self.merchant_id:
            raise UserError(_("Sync merchant profile first (missing merchant id)."))
        line_1 = (self.store_line_1_edit or self.merchant_store_line_1 or "").strip()
        line_2 = (self.store_line_2_edit or self.merchant_store_line_2 or "EG").strip()
        zone = int(self.store_zone_id_edit or self.merchant_store_zone_id or self.default_zone_id or 0)
        if not line_1 or not zone:
            raise UserError(_("Store line 1 and zone are required."))
        payload = {
            "address": {
                "line_1": line_1[:200],
                "line_2": line_2[:200],
                "what3words": (self.store_what3words_edit or "filled.by.odoo")[:80],
                "zone": zone,
            }
        }
        try:
            self.get_client().patch_merchant(self.merchant_id, payload)
        except ShipBluApiError as exc:
            raise UserError(str(exc)) from exc
        ImportService(self.env).sync_merchant_profile(self)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("ShipBlu Store Address"),
                "message": _("Store address updated on ShipBlu."),
                "type": "success",
                "sticky": False,
            },
        }

    def cron_import_orders(self):
        for backend in self.search([("active", "=", True)]):
            ImportService(self.env).import_delivery_orders(backend)

    def cron_sync_tracking(self):
        for backend in self.search([("active", "=", True)]):
            ImportService(self.env).sync_tracking_batch(backend)
