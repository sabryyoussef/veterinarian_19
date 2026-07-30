# -*- coding: utf-8 -*-
"""Rate-limited on-demand commercial refresh lock (TEST)."""

from __future__ import annotations

from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class PetspotVetutionRefreshLock(models.Model):
    _name = "petspot.vetution.refresh.lock"
    _description = "Vetution On-Demand Refresh Lock"
    _order = "id desc"

    connection_id = fields.Many2one(
        "vetution.connection", required=True, ondelete="cascade", index=True
    )
    drug_slug = fields.Char(required=True, index=True)
    locked_until = fields.Datetime(required=True, index=True)
    locked_by_uid = fields.Many2one("res.users")
    inquiry_id = fields.Many2one("petspot.availability.inquiry", ondelete="set null")
    state = fields.Selection(
        [("locked", "Locked"), ("done", "Done"), ("failed", "Failed")],
        default="locked",
        required=True,
    )
    last_error = fields.Char()

    _sql_constraints = [
        (
            "petspot_vetution_refresh_lock_uniq",
            "unique(connection_id, drug_slug)",
            "A refresh lock already exists for this connection/slug.",
        ),
    ]

    @api.model
    def try_acquire(self, connection, slug, inquiry=None, lock_seconds=120):
        """Acquire lock for slug. Returns (acquired: bool, lock_record_or_existing)."""
        connection.ensure_one()
        slug = (slug or "").strip()
        if not slug:
            raise UserError("Cannot refresh without drug slug.")
        now = fields.Datetime.now()
        # Serialize concurrent acquirers for this pair
        self.env.cr.execute(
            "SELECT id FROM petspot_vetution_refresh_lock "
            "WHERE connection_id=%s AND drug_slug=%s FOR UPDATE",
            (connection.id, slug),
        )
        existing = self.search(
            [("connection_id", "=", connection.id), ("drug_slug", "=", slug)],
            limit=1,
        )
        if existing:
            if existing.state == "locked" and existing.locked_until and existing.locked_until > now:
                return False, existing
            existing.unlink()
            self.env.flush_all()
        lock = self.create(
            {
                "connection_id": connection.id,
                "drug_slug": slug,
                "locked_until": now + timedelta(seconds=max(int(lock_seconds or 120), 30)),
                "locked_by_uid": self.env.uid,
                "inquiry_id": inquiry.id if inquiry else False,
                "state": "locked",
            }
        )
        return True, lock

    def release(self, success=True, error=False):
        for rec in self:
            rec.write(
                {
                    "state": "done" if success else "failed",
                    "last_error": (str(error)[:250] if error else False),
                    "locked_until": fields.Datetime.now(),
                }
            )
