# -*- coding: utf-8 -*-
"""Smoke tests for Gmail connector models (no Google API calls)."""

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMailGmailSmoke(TransactionCase):

    def test_create_gmail_account_defaults(self):
        acc = self.env["mail.gmail.account"].create({"name": "Smoke Mailbox"})
        self.assertEqual(acc.state, "draft")
        self.assertTrue(acc.company_id)
        self.assertTrue(acc.user_id)

    def test_gmail_scopes_default_contains_mail(self):
        acc = self.env["mail.gmail.account"].sudo().create({"name": "Scopes"})
        scopes = acc.sudo().scopes or ""
        self.assertIn("gmail", scopes.lower())
