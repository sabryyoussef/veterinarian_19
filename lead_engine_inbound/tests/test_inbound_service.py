# -*- coding: utf-8 -*-
"""
TransactionCase tests for lead_engine_inbound (no HTTP stack required).

Workflow covered (no browser):
  - normalize_payload: valid payload returns structured dict
  - normalize_payload: invalid le_channel raises UserError
  - normalize_payload: invalid type raises UserError
  - normalize_payload: invalid utm block raises UserError
  - validate_business_payload: missing external_ref raises UserError
  - validate_business_payload: missing name/contact_name/email raises UserError
  - resolve_source_from_token: valid token returns source
  - resolve_source_from_token: invalid token returns empty recordset
  - process_intake: full flow creates lead, log, calls pipeline
  - process_intake: duplicate external_ref returns existing lead (upsert)
  - process_intake: missing external_ref returns rejected response (ok=False)
"""

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestInboundNormalizePayload(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Svc = cls.env["lead.engine.inbound.service"]

    # ── valid payload ─────────────────────────────────────────────────────────

    def test_normalize_valid_payload(self):
        result = self.Svc.normalize_payload(
            {
                "external_ref": "norm-001",
                "name": "Test Lead",
                "email_from": "test@example.com",
                "le_channel": "api",
            }
        )
        self.assertEqual(result["meta"]["external_ref"], "norm-001")
        self.assertEqual(result["lead"]["name"], "Test Lead")
        self.assertEqual(result["lead"]["email_from"], "test@example.com")
        self.assertEqual(result["meta"]["le_channel"], "api")

    def test_normalize_strips_external_ref(self):
        result = self.Svc.normalize_payload({"external_ref": "  spaced-ref  "})
        self.assertEqual(result["meta"]["external_ref"], "spaced-ref")

    def test_normalize_utm_block_parsed(self):
        result = self.Svc.normalize_payload(
            {
                "external_ref": "utm-001",
                "name": "UTM Lead",
                "utm": {"campaign_id": 5, "medium_id": 3},
            }
        )
        self.assertEqual(result["utm"]["campaign_id"], 5)
        self.assertEqual(result["utm"]["medium_id"], 3)

    def test_normalize_missing_external_ref_gives_false(self):
        result = self.Svc.normalize_payload({"name": "No Ref"})
        self.assertFalse(result["meta"]["external_ref"])

    def test_normalize_unknown_lead_fields_ignored(self):
        result = self.Svc.normalize_payload(
            {
                "external_ref": "ignore-001",
                "name": "OK",
                "unknown_field": "should be ignored",
            }
        )
        self.assertNotIn("unknown_field", result["lead"])

    # ── invalid inputs raise UserError ───────────────────────────────────────

    def test_normalize_invalid_channel_raises(self):
        with self.assertRaises(UserError):
            self.Svc.normalize_payload(
                {"external_ref": "x", "name": "y", "le_channel": "invalid_channel_xyz"}
            )

    def test_normalize_invalid_type_raises(self):
        with self.assertRaises(UserError):
            self.Svc.normalize_payload(
                {"external_ref": "x", "name": "y", "type": "unknown_type"}
            )

    def test_normalize_non_dict_raises(self):
        with self.assertRaises(UserError):
            self.Svc.normalize_payload("not a dict")

    def test_normalize_invalid_utm_non_dict_raises(self):
        with self.assertRaises(UserError):
            self.Svc.normalize_payload(
                {"external_ref": "x", "name": "y", "utm": "not-a-dict"}
            )

    def test_normalize_utm_non_int_raises(self):
        with self.assertRaises(UserError):
            self.Svc.normalize_payload(
                {"external_ref": "x", "name": "y", "utm": {"campaign_id": "abc"}}
            )


@tagged("post_install", "-at_install")
class TestInboundValidateBusinessPayload(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Svc = cls.env["lead.engine.inbound.service"]

    def _normalized(self, external_ref="ref-001", **lead_kwargs):
        lead = {"name": "Test Lead"}
        lead.update(lead_kwargs)
        return {
            "lead": lead,
            "utm": {},
            "meta": {"external_ref": external_ref, "le_channel": "api"},
        }

    def test_valid_payload_passes(self):
        self.Svc.validate_business_payload(self._normalized())

    def test_missing_external_ref_raises(self):
        norm = self._normalized(external_ref=False)
        with self.assertRaises(UserError):
            self.Svc.validate_business_payload(norm)

    def test_missing_name_and_email_raises(self):
        norm = self._normalized()
        norm["lead"] = {}  # no name, contact_name, or email_from
        with self.assertRaises(UserError):
            self.Svc.validate_business_payload(norm)

    def test_contact_name_alone_passes(self):
        norm = self._normalized()
        norm["lead"] = {"contact_name": "Jane"}
        self.Svc.validate_business_payload(norm)

    def test_email_alone_passes(self):
        norm = self._normalized()
        norm["lead"] = {"email_from": "jane@example.com"}
        self.Svc.validate_business_payload(norm)


@tagged("post_install", "-at_install")
class TestInboundTokenResolution(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Source = cls.env["lead.engine.source"]
        cls.Svc = cls.env["lead.engine.inbound.service"]
        cls.company = cls.env.company
        cls.source = cls.Source.create(
            {
                "name": "Token Source",
                "code": "TOK_SRC",
                "channel": "api",
                "company_id": cls.company.id,
                "inbound_api_token": "inbound-secret-token-abc",
            }
        )

    def test_resolve_valid_token(self):
        result = self.Svc.resolve_source_from_token("inbound-secret-token-abc")
        self.assertTrue(result)
        self.assertEqual(result.id, self.source.id)

    def test_resolve_invalid_token_returns_empty(self):
        result = self.Svc.resolve_source_from_token("wrong-token")
        self.assertFalse(result)

    def test_resolve_empty_token_returns_empty(self):
        result = self.Svc.resolve_source_from_token("")
        self.assertFalse(result)

    def test_resolve_none_token_returns_empty(self):
        result = self.Svc.resolve_source_from_token(None)
        self.assertFalse(result)


@tagged("post_install", "-at_install")
class TestInboundProcessIntake(TransactionCase):
    """End-to-end process_intake via service layer (no HTTP)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Source = cls.env["lead.engine.source"]
        cls.Svc = cls.env["lead.engine.inbound.service"]
        cls.Lead = cls.env["crm.lead"]
        cls.Log = cls.env["lead.engine.intake.log"]
        cls.company = cls.env.company
        cls.source = cls.Source.create(
            {
                "name": "Process Source",
                "code": "PROC_SRC",
                "channel": "api",
                "company_id": cls.company.id,
                "inbound_api_token": "proc-token-secret",
            }
        )

    # ── happy path ────────────────────────────────────────────────────────────

    def test_process_intake_creates_lead(self):
        payload = {"external_ref": "intake-001", "name": "New Lead"}
        result = self.Svc.process_intake(self.source, payload, '{"external_ref":"intake-001"}')
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["state"], "success")
        self.assertTrue(result["result"]["lead_id"])
        self.assertTrue(result["result"]["created"])

    def test_process_intake_creates_intake_log(self):
        payload = {"external_ref": "intake-002", "name": "Log Lead"}
        before = self.Log.search_count([])
        self.Svc.process_intake(self.source, payload, '{}')
        after = self.Log.search_count([])
        self.assertGreater(after, before)

    def test_process_intake_upserts_existing_lead(self):
        """Second call with same external_ref updates the existing lead."""
        payload1 = {"external_ref": "intake-upsert", "name": "First Name"}
        r1 = self.Svc.process_intake(self.source, payload1, '{}')
        lead_id = r1["result"]["lead_id"]

        payload2 = {"external_ref": "intake-upsert", "name": "Updated Name"}
        r2 = self.Svc.process_intake(self.source, payload2, '{}')

        self.assertTrue(r2["ok"])
        self.assertEqual(r2["result"]["lead_id"], lead_id)
        self.assertFalse(r2["result"]["created"])
        lead = self.Lead.browse(lead_id)
        self.assertEqual(lead.name, "Updated Name")

    # ── rejection ─────────────────────────────────────────────────────────────

    def test_process_intake_rejects_missing_external_ref(self):
        payload = {"name": "No Ref Lead"}  # missing external_ref
        result = self.Svc.process_intake(self.source, payload, '{}')
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "rejected")

    def test_process_intake_rejects_missing_name_fields(self):
        payload = {"external_ref": "no-name-001"}  # no name/contact_name/email_from
        result = self.Svc.process_intake(self.source, payload, '{}')
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "rejected")

    # ── qualification fields set after intake ─────────────────────────────────

    def test_process_intake_sets_source_and_channel(self):
        payload = {"external_ref": "src-ch-001", "name": "Source Check"}
        result = self.Svc.process_intake(self.source, payload, '{}')
        lead = self.Lead.browse(result["result"]["lead_id"])
        self.assertEqual(lead.lead_engine_source_id.id, self.source.id)
        self.assertEqual(lead.le_channel, "api")
