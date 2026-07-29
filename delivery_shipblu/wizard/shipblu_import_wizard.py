# -*- coding: utf-8 -*-
from odoo import _, fields, models

from odoo.addons.delivery_shipblu.services.import_service import ImportService


class ShipBluImportWizard(models.TransientModel):
    _name = "shipblu.import.wizard"
    _description = "Import ShipBlu Orders"

    backend_id = fields.Many2one(
        "shipblu.backend",
        required=True,
        default=lambda self: self.env["shipblu.backend"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        ),
    )
    sync_coverage = fields.Boolean(default=True)
    sync_aux = fields.Boolean(string="Import returns/exchanges/COD", default=True)
    result_message = fields.Text(readonly=True)

    def action_run(self):
        self.ensure_one()
        svc = ImportService(self.env)
        parts = []
        if self.sync_coverage:
            cov = svc.sync_coverage(self.backend_id)
            parts.append(_("Coverage g=%(g)s c=%(c)s z=%(z)s") % {"g": cov["governorates"], "c": cov["cities"], "z": cov["zones"]})
        imp = svc.import_delivery_orders(self.backend_id)
        parts.append(imp["message"])
        if self.sync_aux:
            aux = svc.import_aux_orders(self.backend_id)
            parts.append(_("Aux %s") % aux)
        self.result_message = "\n".join(parts)
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
