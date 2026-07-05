# -*- coding: utf-8 -*-
"""
Tests for integration_bridge_core.

Workflow covered (no browser):
  - Token validation: valid active token → record returned
  - Token validation: inactive / expired / wrong-IP → False
  - Token uniqueness constraint (ValidationError on duplicate)
  - Token: generate_token creates a non-empty secret string
  - Outbound queue: process_pending_messages with mocked HTTP
  - Outbound queue: failed HTTP increments retry_count & sets next_retry_at
  - Outbound queue: successful HTTP marks status='sent'
  - Bridge log: record creation with expected fields
"""

import json
from unittest.mock import MagicMock, patch
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestIntegrationBridgeToken(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Token = cls.env["integration.bridge.token"].sudo()

    def _token(self, name="T1", token_val="secret-abc-123", platform="chatwoot", **kwargs):
        vals = {"name": name, "token": token_val, "platform": platform}
        vals.update(kwargs)
        return self.Token.create(vals)

    # ── basic validation ──────────────────────────────────────────────────────

    def test_validate_valid_token(self):
        t = self._token(token_val="valid-tok-001")
        result = self.Token.validate_token("valid-tok-001")
        self.assertTrue(result)
        self.assertEqual(result.id, t.id)

    def test_validate_returns_false_for_unknown_token(self):
        result = self.Token.validate_token("nonexistent-xyz")
        self.assertFalse(result)

    def test_validate_inactive_token_returns_false(self):
        self._token(token_val="inactive-tok", active=False)
        result = self.Token.validate_token("inactive-tok")
        self.assertFalse(result)

    def test_validate_empty_token_returns_false(self):
        result = self.Token.validate_token("")
        self.assertFalse(result)

    def test_validate_none_token_returns_false(self):
        result = self.Token.validate_token(None)
        self.assertFalse(result)

    # ── expiration ────────────────────────────────────────────────────────────

    def test_validate_expired_token_returns_false(self):
        past = fields.Datetime.now() - timedelta(hours=1)
        # expires_at constraint prevents creating expired tokens; use sudo write after creation
        t = self.Token.create(
            {
                "name": "Expiry Test",
                "token": "expired-tok-999",
                "platform": "n8n",
                "expires_at": fields.Datetime.now() + timedelta(hours=1),
            }
        )
        # Directly write to bypass constraint (test infrastructure need)
        self.env.cr.execute(
            "UPDATE integration_bridge_token SET expires_at = %s WHERE id = %s",
            (past, t.id),
        )
        t.invalidate_recordset()
        result = self.Token.validate_token("expired-tok-999")
        self.assertFalse(result)

    # ── IP whitelist ──────────────────────────────────────────────────────────

    def test_validate_allowed_ip(self):
        self._token(token_val="ip-tok-ok", allowed_ips="10.0.0.1,192.168.1.50")
        result = self.Token.validate_token("ip-tok-ok", remote_ip="192.168.1.50")
        self.assertTrue(result)

    def test_validate_blocked_ip_returns_false(self):
        self._token(token_val="ip-tok-bad", allowed_ips="10.0.0.1")
        result = self.Token.validate_token("ip-tok-bad", remote_ip="1.2.3.4")
        self.assertFalse(result)

    def test_validate_no_ip_restriction_any_ip_allowed(self):
        self._token(token_val="ip-tok-open", allowed_ips=False)
        result = self.Token.validate_token("ip-tok-open", remote_ip="8.8.8.8")
        self.assertTrue(result)

    # ── platform filter ───────────────────────────────────────────────────────

    def test_validate_platform_match(self):
        self._token(token_val="plat-tok-evo", platform="evolution")
        result = self.Token.validate_token("plat-tok-evo", platform="evolution")
        self.assertTrue(result)

    def test_validate_wrong_platform_returns_false(self):
        self._token(token_val="plat-tok-cw", platform="chatwoot")
        result = self.Token.validate_token("plat-tok-cw", platform="n8n")
        self.assertFalse(result)

    # ── uniqueness constraint ─────────────────────────────────────────────────

    def test_duplicate_token_raises_validation_error(self):
        self._token(token_val="uniq-tok-dup", name="First")
        with self.assertRaises(ValidationError):
            self._token(token_val="uniq-tok-dup", name="Second")

    # ── generate_token ────────────────────────────────────────────────────────

    def test_generate_token_produces_non_empty_string(self):
        tok = self.Token.generate_token()
        self.assertIsInstance(tok, str)
        self.assertTrue(len(tok) >= 20)

    def test_action_generate_token_writes_field(self):
        t = self._token(token_val="old-tok-value")
        old_val = t.token
        t.action_generate_token()
        self.assertNotEqual(t.token, old_val)

    # ── usage tracking ────────────────────────────────────────────────────────

    def test_validate_increments_usage_count(self):
        self._token(token_val="usage-tok")
        t = self.Token.search([("token", "=", "usage-tok")], limit=1)
        initial = t.usage_count
        self.Token.validate_token("usage-tok")
        t.invalidate_recordset()
        self.assertEqual(t.usage_count, initial + 1)


@tagged("post_install", "-at_install")
class TestIntegrationOutboundQueue(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Queue = cls.env["integration.outbound.queue"].sudo()
        cls.Log = cls.env["integration.bridge.log"].sudo()

    def _queue_item(self, name="Test Msg", status="pending", **kwargs):
        vals = {
            "name": name,
            "platform": "chatwoot",
            "endpoint_url": "http://mock.local/api",
            "payload": json.dumps({"key": "value"}),
            "status": status,
            "retry_count": 0,
            "max_retries": 3,
        }
        vals.update(kwargs)
        return self.Queue.create(vals)

    def _mock_response(self, ok=True, status_code=200, text='{"result": "ok"}'):
        m = MagicMock()
        m.ok = ok
        m.status_code = status_code
        m.text = text
        return m

    # ── successful send ───────────────────────────────────────────────────────

    def test_send_success_marks_sent(self):
        item = self._queue_item()
        with patch("requests.post", return_value=self._mock_response(ok=True)):
            result = item.send_message()
        self.assertTrue(result)
        self.assertEqual(item.status, "sent")
        self.assertIsNotNone(item.sent_at)

    # ── failed send ───────────────────────────────────────────────────────────

    def test_send_http_error_marks_failed_and_increments_retry(self):
        item = self._queue_item()
        with patch("requests.post", return_value=self._mock_response(ok=False, status_code=500)):
            result = item.send_message()
        self.assertFalse(result)
        self.assertEqual(item.status, "failed")
        self.assertEqual(item.retry_count, 1)
        self.assertIsNotNone(item.next_retry_at)

    def test_send_exception_marks_failed(self):
        item = self._queue_item()
        with patch("requests.post", side_effect=Exception("Network error")):
            result = item.send_message()
        self.assertFalse(result)
        self.assertEqual(item.status, "failed")
        self.assertIn("Network error", item.error_message)

    # ── process_pending_messages ──────────────────────────────────────────────

    def test_process_pending_messages_returns_stats(self):
        for i in range(3):
            self._queue_item(name=f"Pending {i}")
        with patch("requests.post", return_value=self._mock_response(ok=True)):
            stats = self.Queue.process_pending_messages(limit=10)
        self.assertIn("processed", stats)
        self.assertIn("sent", stats)
        self.assertIn("failed", stats)
        self.assertGreaterEqual(stats["sent"], 3)

    def test_process_pending_messages_no_items_returns_zeros(self):
        # Mark all existing pending as sent first to isolate
        self.Queue.search([("status", "=", "pending")]).write({"status": "sent"})
        stats = self.Queue.process_pending_messages()
        self.assertEqual(stats["processed"], 0)

    # ── bridge log creation ───────────────────────────────────────────────────

    def test_bridge_log_created_on_send(self):
        item = self._queue_item(name="Log Test")
        before = self.Log.search_count([])
        with patch("requests.post", return_value=self._mock_response(ok=True)):
            item.send_message()
        after = self.Log.search_count([])
        self.assertGreater(after, before)

    def test_bridge_log_fields(self):
        log = self.Log.create(
            {
                "name": "Test Log Entry",
                "direction": "outbound",
                "platform": "evolution",
                "endpoint": "http://test.local/api",
                "status": "success",
                "request_payload": '{"test": 1}',
                "response_payload": '{"ok": true}',
                "http_status": 200,
            }
        )
        self.assertEqual(log.direction, "outbound")
        self.assertEqual(log.platform, "evolution")
        self.assertEqual(log.status, "success")
        self.assertEqual(log.http_status, 200)
