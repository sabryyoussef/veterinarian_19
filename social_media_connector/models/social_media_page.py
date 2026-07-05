# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .social_media_remote import fetch_remote_facebook_pages


class SocialMediaPage(models.Model):
    _name = "social.media.page"
    _description = "Remote Facebook Page (cached from Odoo Online)"
    _order = "name"

    name = fields.Char(required=True)
    remote_account_id = fields.Integer(required=True, index=True)
    facebook_page_id = fields.Char(string="Facebook Page ID")
    has_token = fields.Boolean(default=False)
    is_disconnected = fields.Boolean(
        string="Disconnected on Remote",
        default=False,
        help="True when Odoo Online reports the Facebook link is broken (reconnect required).",
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "remote_account_id_unique",
            "unique(remote_account_id)",
            "This remote Facebook page is already synced.",
        ),
    ]

    @api.model
    def sync_from_remote(self):
        """Fetch social.account records from remote Odoo and upsert local pages."""
        remote_pages = fetch_remote_facebook_pages(self.env)
        seen_ids = set()
        for row in remote_pages:
            remote_id = row["id"]
            seen_ids.add(remote_id)
            vals = {
                "name": row.get("name") or f"Page {remote_id}",
                "remote_account_id": remote_id,
                "facebook_page_id": row.get("facebook_account_id") or False,
                "has_token": bool(row.get("facebook_access_token")),
                "is_disconnected": bool(row.get("is_media_disconnected")),
                "active": True,
            }
            existing = self.search([("remote_account_id", "=", remote_id)], limit=1)
            if existing:
                existing.write(vals)
            else:
                self.create(vals)
        stale = self.search([("remote_account_id", "not in", list(seen_ids))]) if seen_ids else self.browse()
        if stale:
            stale.write({"active": False})
        return len(remote_pages)
