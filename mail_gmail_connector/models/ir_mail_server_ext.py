# -*- coding: utf-8 -*-
from odoo import fields, models


class IrMailServerGmailConnector(models.Model):
    """Extend ir.mail_server with a back-link to the Gmail Connector account
    that provisioned it, so token refresh uses per-account client credentials
    instead of the system-wide google_gmail_client_id/secret."""

    _inherit = "ir.mail_server"

    gmail_connector_account_id = fields.Many2one(
        "mail.gmail.account",
        string="Gmail Connector Account",
        ondelete="set null",
        copy=False,
    )

    def _fetch_gmail_access_token(self, refresh_token):
        self.ensure_one()
        if self.gmail_connector_account_id:
            return self.gmail_connector_account_id.sudo()._gmail_fetch_access_token_direct(
                refresh_token
            )
        return super()._fetch_gmail_access_token(refresh_token)
