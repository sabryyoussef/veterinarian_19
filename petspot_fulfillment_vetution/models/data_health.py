# -*- coding: utf-8 -*-
"""Vetution data-health dashboard — stored point-in-time snapshots.

Read-only diagnostics only; never writes commercial data. The scheduled
snapshot cron is shipped disabled (active=False) — a human must enable it.
"""

from __future__ import annotations

from odoo import api, fields, models


class PetspotVetutionDataHealth(models.Model):
    _name = "petspot.vetution.data.health"
    _description = "Vetution Data Health Snapshot"
    _order = "id desc"

    name = fields.Char(required=True, default="Health Snapshot")
    snapshot_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)

    commercial_sync_age_hours = fields.Float(
        help="Age (hours) of the most recent Vetution commercial sync across all offers."
    )
    shadow_stale_count = fields.Integer(help="Active shadow assessments currently state=stale.")
    circuit_breaker_state = fields.Selection(
        [("closed", "Closed (healthy)"), ("open", "Open (refresh disabled)")],
        default="closed",
        required=True,
    )
    circuit_breaker_open_until = fields.Datetime()
    allowlist_count = fields.Integer(help="Active automation-allowlist rows.")
    mapping_pending_count = fields.Integer(help="Pending mapping-review rows.")
    last_refresh_failures = fields.Integer(help="Consecutive on-demand refresh failures.")
    note = fields.Text()
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )

    @api.model
    def take_snapshot(self, company=None):
        """Compute and store one health snapshot. Safe to call any time —
        purely read-only aggregation, no commercial side effects.
        """
        company = company or self.env.company
        ICP = self.env["ir.config_parameter"].sudo()

        Offer = self.env["vetution.supplier.offer"] if "vetution.supplier.offer" in self.env else None
        sync_age_hours = 0.0
        if Offer is not None:
            offers = Offer.search(
                [("last_commercial_sync_at", "!=", False)], order="last_commercial_sync_at desc", limit=1
            )
            if offers:
                ts = offers.last_commercial_sync_at
                sync_age_hours = round(
                    (fields.Datetime.now() - ts).total_seconds() / 3600.0, 2
                )

        Assessment = self.env["petspot.vetution.shadow.assessment"]
        shadow_stale_count = Assessment.search_count(
            [("active", "=", True), ("state", "=", "stale")]
        )

        open_until_raw = ICP.get_param("petspot_fulfillment_vetution.circuit_open_until", "")
        breaker_state = "closed"
        open_until = False
        if open_until_raw:
            try:
                open_until = fields.Datetime.to_datetime(open_until_raw)
            except Exception:  # noqa: BLE001
                open_until = False
            if open_until and open_until > fields.Datetime.now():
                breaker_state = "open"

        allowlist_count = self.env["petspot.vetution.automation.allowlist"].search_count(
            [("active", "=", True)]
        )
        mapping_pending_count = self.env["petspot.vetution.mapping.review"].search_count(
            [("state", "=", "pending")]
        )
        last_refresh_failures = int(
            ICP.get_param("petspot_fulfillment_vetution.refresh_fail_count", "0") or 0
        )

        return self.create(
            {
                "name": f"Health/{fields.Datetime.now()}",
                "snapshot_at": fields.Datetime.now(),
                "commercial_sync_age_hours": sync_age_hours,
                "shadow_stale_count": shadow_stale_count,
                "circuit_breaker_state": breaker_state,
                "circuit_breaker_open_until": open_until or False,
                "allowlist_count": allowlist_count,
                "mapping_pending_count": mapping_pending_count,
                "last_refresh_failures": last_refresh_failures,
                "company_id": company.id,
            }
        )

    def action_take_snapshot_now(self):
        return self.take_snapshot().id and True

    @api.model
    def cron_take_snapshot(self):
        """Disabled-by-default cron entry point."""
        self.take_snapshot()
        return True
