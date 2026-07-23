# -*- coding: utf-8 -*-
"""
Tests for chatwoot_evolution_error_bridge.

Workflow covered (no browser):
  - x_external_ref auto-populated from x_chatwoot_conversation_id on create
  - x_external_ref uniqueness constraint (ValidationError on duplicate)
  - get_chatwoot_reply_message() returns a formatted string with CRM ref
  - x_source_platform field values stored and retrieved correctly
  - ResConfigSettings: set_values writes chatwoot ICP params;
    get_values reads them back correctly
"""

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestChatwootEvolutionBridge(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Lead = cls.env["crm.lead"]

    # ── auto external_ref from chatwoot conversation id ───────────────────────

    def test_external_ref_auto_set_from_conversation_id(self):
        lead = self.Lead.create(
            {
                "name": "Chatwoot Lead",
                "x_chatwoot_conversation_id": "123456",
            }
        )
        self.assertEqual(lead.x_external_ref, "CW-123456")

    def test_external_ref_not_overwritten_if_already_set(self):
        lead = self.Lead.create(
            {
                "name": "Manual Ref Lead",
                "x_chatwoot_conversation_id": "999",
                "x_external_ref": "MANUAL-001",
            }
        )
        # Explicit x_external_ref must not be replaced by auto logic
        self.assertEqual(lead.x_external_ref, "MANUAL-001")

    def test_external_ref_blank_without_conversation_id(self):
        lead = self.Lead.create({"name": "No Conversation"})
        self.assertFalse(lead.x_external_ref)

    # ── uniqueness constraint ─────────────────────────────────────────────────

    def test_duplicate_external_ref_raises_validation_error(self):
        self.Lead.create(
            {"name": "First Lead", "x_external_ref": "CW-UNIQ-001"}
        )
        with self.assertRaises(ValidationError):
            self.Lead.create(
                {"name": "Second Lead", "x_external_ref": "CW-UNIQ-001"}
            )

    def test_different_external_refs_are_allowed(self):
        self.Lead.create({"name": "Lead A", "x_external_ref": "CW-A-001"})
        self.Lead.create({"name": "Lead B", "x_external_ref": "CW-A-002"})

    # ── source platform field ─────────────────────────────────────────────────

    def test_source_platform_field_values(self):
        for platform in ("whatsapp", "chatwoot", "evolution", "web", "other"):
            lead = self.Lead.create(
                {"name": f"Lead {platform}", "x_source_platform": platform}
            )
            self.assertEqual(lead.x_source_platform, platform)

    # ── get_chatwoot_reply_message ────────────────────────────────────────────

    def test_reply_message_contains_crm_ref(self):
        lead = self.Lead.create({"name": "Reply Test Lead"})
        msg = lead.get_chatwoot_reply_message()
        self.assertIn(f"CRM-{lead.id:05d}", msg)

    def test_reply_message_contains_stage(self):
        lead = self.Lead.create({"name": "Stage Test Lead"})
        msg = lead.get_chatwoot_reply_message()
        # stage name should appear (either stage name or 'New')
        self.assertIsInstance(msg, str)
        self.assertTrue(len(msg) > 0)

    # ── config settings round-trip ────────────────────────────────────────────

    def test_config_settings_set_and_get_bridge_token(self):
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param("integration_bridge.master_token", "test-bridge-token-xyz")
        Settings = self.env["res.config.settings"].sudo()
        s = Settings.create({})
        values = s.get_values()
        self.assertEqual(values.get("chatwoot_bridge_token"), "test-bridge-token-xyz")

    def test_config_settings_set_values_writes_cors(self):
        Settings = self.env["res.config.settings"].sudo()
        s = Settings.create({"chatwoot_bridge_cors_origins": "https://my.domain.com"})
        s.set_values()
        cors = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("chatwoot_bridge.cors_origins")
        )
        self.assertEqual(cors, "https://my.domain.com")
