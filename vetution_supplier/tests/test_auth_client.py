# -*- coding: utf-8 -*-

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import VetutionSupplierCommon


@tagged("post_install", "-at_install", "vetution_supplier")
class TestAuthClient(VetutionSupplierCommon):
    def test_login_success_stores_token_masked(self):
        token = "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOjIxNDMsImV4cCI6MTc5NTU0ODgzNX0.sig"
        responses = [
            (
                200,
                {
                    "access_token": token,
                    "token_type": "bearer",
                    "expires_in": 0,
                    "user": {"id": 2143, "is_accepted": 1},
                },
            )
        ]
        with patch.object(
            type(self.connection), "_get_password", return_value="secret-password"
        ), self._patch_http(responses):
            got = self.Sync.login(self.connection, force=True)
        self.assertEqual(got, token)
        self.connection.invalidate_recordset()
        self.assertEqual(self.connection.state, "connected")
        self.assertTrue(self.connection.account_is_accepted)
        display = self.connection.access_token or ""
        self.assertTrue(display.startswith("***"))
        self.assertNotIn(token, display)
        self.assertNotIn("eyJhbGciOiJIUzI1NiJ9", display)
        stored = self.connection._get_stored_token()
        self.assertEqual(stored, token)

    def test_bad_credentials(self):
        responses = [(403, {"success": False, "error": ["Wrong Credentials"]})]
        with patch.object(
            type(self.connection), "_get_password", return_value="wrong"
        ), self._patch_http(responses):
            with self.assertRaises(UserError) as ctx:
                self.Sync.login(self.connection, force=True)
        self.assertIn("login failed", str(ctx.exception).lower())

    def test_silent_degradation_aborts_without_write(self):
        token = "Bearer aaa.bbb.ccc"
        self.connection._store_token(token)
        self.connection.write({"account_is_accepted": True, "state": "connected"})

        zeroed = {
            "id": 1,
            "slug": "x",
            "name": "X",
            "show_price": False,
            "prices": [
                {
                    "A": {
                        "vetution": {
                            "drug_size_id": 999001,
                            "price": 0,
                            "user_price": 0,
                            "show": 1,
                            "qty": 0,
                            "out_of_stock": 0,
                            "expire_date": None,
                        },
                        "vendors": [],
                    }
                }
            ],
        }

        def http(connection, method, path, body=None, token=None, timeout=40):
            if path.startswith("/carts"):
                return 200, {"data": [], "cart_total_price": 0}
            if "drugs" in path:
                return 200, {
                    "success": True,
                    "data": {"data": [zeroed], "meta": {"last_page": 1}},
                }
            return 200, {}

        before = self.Offer.search_count([])
        with self._patch_http(http):
            with self.assertRaises(UserError) as ctx:
                self.Sync.sync_full_commercial(
                    self.connection, dry_run=False, max_pages=1
                )
        after = self.Offer.search_count([])
        self.assertEqual(before, after)
        self.assertIn("degradation", str(ctx.exception).lower())

    def test_relogin_after_401_on_carts(self):
        token_old = "Bearer old.token.sig"
        token_new = "Bearer new.token.sig"
        self.connection._store_token(token_old)
        self.connection.write({"account_is_accepted": True})
        calls = {"n": 0}

        def http(connection, method, path, body=None, token=None, timeout=40):
            calls["n"] += 1
            if path.startswith("/carts") and token == token_old:
                return 401, {"success": False, "data": "Unauthorized"}
            if path.startswith("/user/login"):
                return 200, {
                    "access_token": token_new,
                    "user": {"id": 2143, "is_accepted": 1},
                }
            if path.startswith("/carts"):
                return 200, {"data": []}
            return 200, {}

        with patch.object(
            type(self.connection), "_get_password", return_value="secret"
        ), self._patch_http(http):
            got = self.Sync.assert_authentication(self.connection)
        self.assertEqual(got, token_new)

    def test_password_absent_from_logs(self):
        from odoo.addons.vetution_supplier.models.vetution_commercial_sync import (
            _sanitize_for_log,
        )

        messy = "Authorization Bearer eyJhbGciOiJIUzI1NiJ9.abc.def failed"
        clean = _sanitize_for_log(messy)
        self.assertNotIn("eyJhbGciOiJIUzI1NiJ9", clean)
        self.assertIn("Bearer ***", clean)
