# -*- coding: utf-8 -*-
from odoo import _, fields, models

from odoo.addons.delivery_shipblu.services.import_service import ImportService


class ShipBluBackendExt(models.Model):
    _inherit = "shipblu.backend"

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

    def cron_import_orders(self):
        for backend in self.search([("active", "=", True)]):
            ImportService(self.env).import_delivery_orders(backend)

    def cron_sync_tracking(self):
        for backend in self.search([("active", "=", True)]):
            ImportService(self.env).sync_tracking_batch(backend)
