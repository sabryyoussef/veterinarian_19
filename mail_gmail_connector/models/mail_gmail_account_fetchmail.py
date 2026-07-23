# -*- coding: utf-8 -*-
"""Related proxies to fetchmail.server — loaded after fetchmail_server_ext so setup order is valid."""

from odoo import fields, models


class MailGmailAccountFetchmail(models.Model):
    _inherit = "mail.gmail.account"

    # Editable proxies (stored on fetchmail.server); defined here so fetchmail.server
    # already has gmail_imap_* fields when this related path is resolved (Odoo 19).
    gmail_imap_fetch_scope = fields.Selection(
        related="incoming_mail_server_id.gmail_imap_fetch_scope",
        readonly=False,
        related_sudo=True,
    )
    gmail_allow_inbox_all = fields.Boolean(
        related="incoming_mail_server_id.gmail_allow_inbox_all",
        readonly=False,
        related_sudo=True,
    )
