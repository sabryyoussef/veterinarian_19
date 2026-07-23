# -*- coding: utf-8 -*-
"""Optional HTTP-stack intake tests (supplementary).

**Regression coverage for intake logic** (normalize → validate → ``process_intake``) lives in
``test_inbound_service.py`` using :class:`~odoo.tests.common.TransactionCase` and runs in the
default CI / PowerShell runner without extra env vars.

These :class:`~odoo.tests.common.HttpCase` tests are **skipped by default** because they hit the
real HTTP stack with a different cursor than the test transaction; token routing can be flaky in a
multi-database ``dbfilter`` setup even with ``X-Odoo-Database`` and committed fixtures.

To attempt them anyway (may still fail depending on environment)::

    set LEAD_ENGINE_RUN_HTTP_TESTS=1
    odoo-bin ... -d YOUR_DB --test-tags /lead_engine_inbound:TestLeadEngineInboundHttp

Manual verification: POST ``/lead_engine/v1/intake`` with ``Authorization: Bearer <inbound_api_token>``.
"""

import json
import os
import unittest

from odoo import api
from odoo.tests import tagged
from odoo.tests.common import HttpCase


@unittest.skipUnless(
    os.environ.get("LEAD_ENGINE_RUN_HTTP_TESTS") == "1",
    "Set LEAD_ENGINE_RUN_HTTP_TESTS=1 to run (HttpCase + multi-DB is environment-sensitive); "
    "validate intake via API client or manual UI instead.",
)
@tagged("post_install", "-at_install", "-standard")
class TestLeadEngineInboundHttp(HttpCase):
    """HTTP intake needs a RW cursor; HttpCase test mode defaults to read-only."""

    readonly_enabled = False

    def setUp(self):
        super().setUp()
        self._lead_engine_db_name = self.registry.db_name

    def url_open(self, url, data=None, files=None, timeout=12, headers=None, json=None, params=None, allow_redirects=True, cookies=None, method=None):
        """Ensure the worker binds to this DB (needed when odoo.conf dbfilter matches multiple DBs)."""
        hdrs = dict(headers or {})
        hdrs.setdefault("X-Odoo-Database", self._lead_engine_db_name)
        return super().url_open(
            url,
            data=data,
            files=files,
            timeout=timeout,
            headers=hdrs,
            json=json,
            params=params,
            allow_redirects=allow_redirects,
            cookies=cookies,
            method=method,
        )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Source = cls.env["lead.engine.source"].sudo()
        cls.Log = cls.env["lead.engine.intake.log"].sudo()
        cls.Lead = cls.env["crm.lead"].sudo()
        # HttpCase uses the real HTTP stack; it only sees committed data. Use a real cursor (not cls.cr).
        with cls.registry.cursor() as cr:
            env = api.Environment(cr, api.SUPERUSER_ID, {})
            Source = env["lead.engine.source"].sudo()
            Source.search([("code", "=", "HTTP_INBOUND_TEST")]).unlink()
            Source.create(
                {
                    "name": "HTTP Inbound Test",
                    "code": "HTTP_INBOUND_TEST",
                    "channel": "api",
                    "company_id": env.company.id,
                    "inbound_api_token": "test-secret-token-123",
                }
            )
            cr.commit()

    def test_intake_success(self):
        payload = json.dumps(
            {
                "external_ref": "http-001",
                "name": "API Lead",
                "email_from": "api@example.com",
            }
        )
        res = self.url_open(
            "/lead_engine/v1/intake",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test-secret-token-123",
            },
        )
        self.assertEqual(res.status_code, 200, res.text)
        data = json.loads(res.text)
        self.assertTrue(data.get("ok"))
        self.assertEqual(data["result"]["state"], "success")
        self.assertTrue(data["result"]["intake_log_id"])
        lead = self.Lead.browse(data["result"]["lead_id"])
        self.assertTrue(lead.exists())
        self.assertEqual(lead.external_ref, "http-001")

    def test_intake_rejected(self):
        payload = json.dumps({"external_ref": "bad"})
        res = self.url_open(
            "/lead_engine/v1/intake",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test-secret-token-123",
            },
        )
        self.assertEqual(res.status_code, 400)
        data = json.loads(res.text)
        self.assertFalse(data.get("ok"))
        self.assertEqual(data["error"]["code"], "rejected")

    def test_intake_unauthorized(self):
        # No Bearer → SessionExpiredException → redirect to login (not JSON 401) unless redirects are off.
        res = self.url_open(
            "/lead_engine/v1/intake",
            data="{}",
            headers={"Content-Type": "application/json"},
            allow_redirects=False,
        )
        self.assertIn(
            res.status_code,
            (302, 303, 401),
            "Expected auth failure redirect or 401, got %s" % res.status_code,
        )

    def test_intake_idempotent_same_external_ref(self):
        """Second POST with same external_ref updates the same lead (upsert); created=False."""
        body = {
            "external_ref": "idem-http",
            "name": "First",
            "email_from": "idem@example.com",
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer test-secret-token-123",
        }
        r1 = self.url_open("/lead_engine/v1/intake", data=json.dumps(body), headers=headers)
        self.assertEqual(r1.status_code, 200)
        d1 = json.loads(r1.text)
        lid = d1["result"]["lead_id"]
        r2 = self.url_open(
            "/lead_engine/v1/intake",
            data=json.dumps(
                {
                    "external_ref": "idem-http",
                    "name": "Second name",
                    "email_from": "idem@example.com",
                }
            ),
            headers=headers,
        )
        self.assertEqual(r2.status_code, 200, r2.text)
        d2 = json.loads(r2.text)
        self.assertTrue(d2["ok"])
        self.assertFalse(d2["result"]["created"])
        self.assertEqual(d2["result"]["lead_id"], lid)
        lead = self.Lead.browse(lid)
        self.assertEqual(lead.name, "Second name")
