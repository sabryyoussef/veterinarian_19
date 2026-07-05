# -*- coding: utf-8 -*-
"""Smoke tests for LinkedIn connector models (no OAuth round-trip)."""

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLinkedinConnectorSmoke(TransactionCase):

    def test_create_account_and_redirect_uri(self):
        icp = self.env["ir.config_parameter"].sudo()
        icp.set_param("web.base.url", "https://odoo.example.com")

        acc = self.env["linkedin.account"].create(
            {
                "name": "Test LI",
                "client_id": "client-id",
                "client_secret": "secret",
            }
        )
        self.assertTrue(acc.redirect_uri)
        self.assertIn("linkedin_connector/callback", acc.redirect_uri)
        self.assertIn(acc.env.cr.dbname, acc.redirect_uri)

    def test_connected_false_without_tokens(self):
        acc = self.env["linkedin.account"].create(
            {
                "name": "Disconnected",
                "client_id": "x",
                "client_secret": "y",
            }
        )
        self.assertFalse(acc.connected)
