# -*- coding: utf-8 -*-
"""Sync log for Vetution commercial synchronization runs."""

from odoo import fields, models


class VetutionSyncLog(models.Model):
    _name = "vetution.sync.log"
    _description = "Vetution Commercial Sync Log"
    _order = "id desc"

    name = fields.Char(required=True, default="Commercial Sync")
    connection_id = fields.Many2one("vetution.connection", required=True, ondelete="cascade", index=True)
    sync_type = fields.Selection(
        [
            ("auth_test", "Auth Test"),
            ("login", "Login"),
            ("pilot", "Pilot Sample"),
            ("selected", "Selected Products"),
            ("full_commercial", "Full Commercial"),
            ("reconciliation", "Reconciliation"),
            ("retry", "Retry"),
            ("dry_run", "Dry Run"),
        ],
        required=True,
        index=True,
    )
    state = fields.Selection(
        [
            ("running", "Running"),
            ("done", "Done"),
            ("failed", "Failed"),
            ("aborted_auth", "Aborted (Auth)"),
        ],
        default="running",
        required=True,
        index=True,
    )
    started_at = fields.Datetime(default=fields.Datetime.now)
    ended_at = fields.Datetime()
    duration_seconds = fields.Float()
    dry_run = fields.Boolean()

    pages_requested = fields.Integer()
    pages_successful = fields.Integer()
    pages_failed = fields.Integer()
    products_processed = fields.Integer()
    offers_created = fields.Integer()
    offers_updated = fields.Integer()
    offers_unchanged = fields.Integer()
    vendor_offers_created = fields.Integer()
    vendor_offers_updated = fields.Integer()
    missing_variant_mappings = fields.Integer()
    duplicate_ids = fields.Integer()
    invalid_prices = fields.Integer()
    invalid_expiry = fields.Integer()
    conflicts = fields.Integer()
    authentication_failures = fields.Integer()
    supplierinfo_created = fields.Integer()
    supplierinfo_updated = fields.Integer()
    supplierinfo_deactivated = fields.Integer()

    error_summary = fields.Text()
    detail_json = fields.Text(
        help="Sanitized metrics / quarantine payloads. Never contains tokens or passwords.",
    )
    note = fields.Text()
