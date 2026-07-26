# -*- coding: utf-8 -*-
"""System-admin commercial sync wizard."""

from odoo import fields, models
from odoo.exceptions import AccessError, UserError


class VetutionCommercialSyncWizard(models.TransientModel):
    _name = "vetution.commercial.sync.wizard"
    _description = "Vetution Commercial Sync Wizard"

    connection_id = fields.Many2one(
        "vetution.connection",
        required=True,
        default=lambda self: self.env["vetution.connection"].search(
            [("active", "=", True)], limit=1
        ),
    )
    dry_run = fields.Boolean(
        string="Dry Run",
        help="Parse and report without writing offers or supplierinfo.",
    )
    confirm_full_sync = fields.Boolean(
        string="I confirm full commercial sync",
        help="Required before running a full catalog commercial sync.",
    )
    slug_text = fields.Text(
        string="Slugs (one per line)",
        help="Optional list of product slugs for selected sync.",
    )
    last_log_id = fields.Many2one("vetution.sync.log", readonly=True)
    result_message = fields.Text(readonly=True)

    def _check_admin(self):
        if not self.env.user.has_group("base.group_system"):
            raise AccessError("Only System administrators can run Vetution commercial sync.")

    def action_test_connection(self):
        self._check_admin()
        self.ensure_one()
        self.env["vetution.commercial.sync"].assert_authentication(self.connection_id)
        self.result_message = "Authentication assertion passed."
        return self._reopen()

    def action_login_refresh(self):
        self._check_admin()
        self.ensure_one()
        self.env["vetution.commercial.sync"].login(self.connection_id, force=True)
        self.result_message = "Token refreshed."
        return self._reopen()

    def action_sync_pilot(self):
        self._check_admin()
        self.ensure_one()
        log = self.env["vetution.commercial.sync"].sync_pilot(
            self.connection_id, dry_run=self.dry_run
        )
        self.last_log_id = log.id
        self.result_message = (
            f"Pilot done ({log.state}). products={log.products_processed} "
            f"created={log.offers_created} updated={log.offers_updated} "
            f"vendors+={log.vendor_offers_created} conflicts={log.conflicts} "
            f"duplicates={log.duplicate_ids}"
        )
        return self._reopen()

    def action_sync_selected(self):
        self._check_admin()
        self.ensure_one()
        slugs = [s.strip() for s in (self.slug_text or "").splitlines() if s.strip()]
        if not slugs:
            raise UserError("Provide at least one slug.")
        log = self.env["vetution.commercial.sync"].sync_slugs(
            self.connection_id, slugs, sync_type="selected", dry_run=self.dry_run
        )
        self.last_log_id = log.id
        self.result_message = f"Selected sync done ({log.state}). products={log.products_processed}"
        return self._reopen()

    def action_sync_full(self):
        self._check_admin()
        self.ensure_one()
        if not self.confirm_full_sync:
            raise UserError(
                "Full commercial sync requires explicit confirmation "
                "(check 'I confirm full commercial sync')."
            )
        log = self.env["vetution.commercial.sync"].sync_full_commercial(
            self.connection_id, dry_run=self.dry_run
        )
        self.last_log_id = log.id
        self.result_message = (
            f"Full sync done ({log.state}). pages={log.pages_successful}/{log.pages_requested} "
            f"products={log.products_processed}"
        )
        return self._reopen()

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }

    def action_open_log(self):
        self.ensure_one()
        if not self.last_log_id:
            raise UserError("No log yet.")
        return {
            "type": "ir.actions.act_window",
            "res_model": "vetution.sync.log",
            "view_mode": "form",
            "res_id": self.last_log_id.id,
        }
