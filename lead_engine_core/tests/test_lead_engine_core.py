# -*- coding: utf-8 -*-
"""
Tests for lead_engine_core.

Workflow covered (no browser):
  - LeadEngineSource.get_by_code() finds active source by code + company
  - LeadEngineSource.get_by_code() returns empty when inactive / wrong company
  - Source code+company unique constraint (IntegrityError via Constraint)
  - LeadEngineIntakeService.create_intake_log() creates log with expected fields
  - create_intake_log() truncates oversized payloads
  - create_intake_log() uses source.channel as default channel
  - intake log status/processing_stage lifecycle fields
"""

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLeadEngineSource(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Source = cls.env["lead.engine.source"]
        cls.company = cls.env.company

    def _source(self, code="SRC_TEST", channel="api", **kwargs):
        vals = {
            "name": f"Source {code}",
            "code": code,
            "channel": channel,
            "company_id": self.company.id,
        }
        vals.update(kwargs)
        return self.Source.create(vals)

    # ── get_by_code ───────────────────────────────────────────────────────────

    def test_get_by_code_finds_active_source(self):
        src = self._source(code="GBC_ACTIVE")
        result = self.Source.get_by_code("GBC_ACTIVE")
        self.assertEqual(result.id, src.id)

    def test_get_by_code_returns_empty_for_unknown_code(self):
        result = self.Source.get_by_code("DOES_NOT_EXIST_XYZ")
        self.assertFalse(result)

    def test_get_by_code_skips_inactive_source(self):
        self._source(code="GBC_INACTIVE", active=False)
        result = self.Source.get_by_code("GBC_INACTIVE")
        self.assertFalse(result)

    def test_get_by_code_respects_company(self):
        other_company = self.env["res.company"].create({"name": "Other Co"})
        self._source(code="GBC_COMP", company_id=other_company.id)
        # Searching in current company should not find the other-company source
        result = self.Source.get_by_code("GBC_COMP", company_id=self.company.id)
        self.assertFalse(result)

    # ── unique constraint ──────────────────────────────────────────────────────

    def test_duplicate_code_same_company_raises(self):
        self._source(code="UNIQ_CODE")
        with self.assertRaises(Exception):
            self._source(code="UNIQ_CODE")

    def test_same_code_different_company_is_allowed(self):
        other_company = self.env["res.company"].create({"name": "Co2 for Core Test"})
        self._source(code="SHARED_CODE")
        self._source(code="SHARED_CODE", company_id=other_company.id)

    # ── channel values ────────────────────────────────────────────────────────

    def test_source_channel_values(self):
        for ch in ("api", "webhook", "form", "email", "ads", "import", "other"):
            src = self._source(code=f"CH_{ch.upper()}", channel=ch)
            self.assertEqual(src.channel, ch)


@tagged("post_install", "-at_install")
class TestLeadEngineIntakeService(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Source = cls.env["lead.engine.source"]
        cls.Intake = cls.env["lead.engine.intake.service"]
        cls.company = cls.env.company
        cls.source = cls.Source.create(
            {
                "name": "Intake Test Source",
                "code": "INTAKE_SVC_TST",
                "channel": "api",
                "company_id": cls.company.id,
            }
        )

    # ── basic log creation ─────────────────────────────────────────────────────

    def test_create_intake_log_returns_record(self):
        log = self.Intake.create_intake_log(
            self.source,
            external_ref="ext-001",
            payload_raw='{"name": "Test"}',
        )
        self.assertTrue(log.id)

    def test_create_intake_log_fields(self):
        log = self.Intake.create_intake_log(
            self.source,
            channel="webhook",
            external_ref="ext-002",
            payload_raw='{"data": 1}',
        )
        self.assertEqual(log.source_id.id, self.source.id)
        self.assertEqual(log.channel, "webhook")
        self.assertEqual(log.external_ref, "ext-002")
        self.assertEqual(log.status, "pending")
        self.assertEqual(log.processing_stage, "received")

    def test_create_intake_log_uses_source_channel_as_default(self):
        log = self.Intake.create_intake_log(self.source, external_ref="ext-003")
        self.assertEqual(log.channel, "api")  # source.channel

    # ── payload truncation ────────────────────────────────────────────────────

    def test_payload_truncated_when_over_limit(self):
        """Payloads exceeding the configured limit must be truncated."""
        big_payload = "x" * 70_000
        log = self.Intake.create_intake_log(
            self.source,
            external_ref="ext-trunc",
            payload_raw=big_payload,
        )
        self.assertIn("[truncated]", log.payload_raw)
        self.assertLess(len(log.payload_raw), 70_000)

    def test_payload_not_truncated_when_under_limit(self):
        small_payload = '{"name": "Small"}'
        log = self.Intake.create_intake_log(
            self.source,
            external_ref="ext-small",
            payload_raw=small_payload,
        )
        self.assertNotIn("[truncated]", log.payload_raw)
        self.assertEqual(log.payload_raw, small_payload)

    # ── request_uuid ──────────────────────────────────────────────────────────

    def test_request_uuid_stored(self):
        log = self.Intake.create_intake_log(
            self.source,
            external_ref="ext-uuid",
            request_uuid="my-custom-uuid-123",
        )
        self.assertEqual(log.request_uuid, "my-custom-uuid-123")
