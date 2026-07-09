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
        ICP = self.env["ir.config_parameter"].sudo()
        only_remote_id = int(ICP.get_param("social_media_connector.single_remote_account_id", "0") or 0)
        remote_pages = fetch_remote_facebook_pages(self.env)
        if only_remote_id:
            remote_pages = [p for p in remote_pages if p.get("id") == only_remote_id]
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
        stale = self.browse()
        if only_remote_id:
            stale = self.search([("remote_account_id", "!=", only_remote_id)])
        elif seen_ids:
            stale = self.search([("remote_account_id", "not in", list(seen_ids))])
        if stale:
            keep = self.search([("remote_account_id", "=", only_remote_id)], limit=1) if only_remote_id else self.browse()
            if keep and len(keep) == 1:
                self.env["social.media.post"].sudo().search(
                    [("page_id", "in", stale.ids)]
                ).write({"page_id": keep.id})
            stale.unlink()
        return len(remote_pages)
