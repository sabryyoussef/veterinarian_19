# -*- coding: utf-8 -*-
"""Phase 3: unified Hub outbound API (flag-gated, bridge transport)."""
from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged, new_test_user


def _enable_unified(env, hub_instance=None):
    env["ir.config_parameter"].sudo().set_param(
        "whatsapp_hub.unified_outbound_enabled", "True"
    )
    if hub_instance:
        hub_instance.sudo().write({"unified_outbound_enabled": True})


@tagged("post_install", "-at_install", "whatsapp_hub")
class TestWhatsappHubUnifiedOutbound(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env,
            login="wa_hub_p3_manager",
            groups="whatsapp_hub.group_whatsapp_manager",
        )
        cls.Out = cls.env["whatsapp.outbound.message"]
        cls.Message = cls.env["whatsapp.message"]
        cls.partner = cls.env["res.partner"].create(
            {"name": "P3 Outbound Partner", "phone": "201007771111"}
        )
        cls.hub_inst = cls.env["whatsapp.instance"].create(
            {
                "name": "P3 Hub Inst",
                "api_url": "http://127.0.0.1:9",
                "api_key": "secret-should-not-leak",
                "instance_name": "p3-test-inst",
                "purpose": "other",
                "unified_outbound_enabled": False,
            }
        )

    def _mock_transport_ok(self, evo_id="P3EVOOK1"):
        return {
            "ok": True,
            "accepted": True,
            "provider_message_id": evo_id,
            "http_status": 200,
            "error": False,
            "temporary": False,
            "response_excerpt": '{"key":{"id":"%s"}}' % evo_id,
            "bridge_instance_id": 99,
            "transport": "evolution.instance",
        }

    def _mock_transport_fail(self, temporary=True):
        return {
            "ok": False,
            "accepted": False,
            "provider_message_id": False,
            "http_status": 500 if temporary else 400,
            "error": "HTTP 500" if temporary else "HTTP 400",
            "temporary": temporary,
            "response_excerpt": "fail",
            "bridge_instance_id": 99,
            "transport": "evolution.instance",
        }

    def test_disabled_flag_blocks_api(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "whatsapp_hub.unified_outbound_enabled", "False"
        )
        with self.assertRaises(UserError):
            self.Out.with_user(self.manager).service_send_message(
                {
                    "destination": "201007771111",
                    "body": "blocked",
                    "client_request_id": "p3-block-1",
                    "related_model": "res.partner",
                    "related_res_id": self.partner.id,
                }
            )

    def test_valid_text_creates_message_and_queue(self):
        _enable_unified(self.env, self.hub_inst)
        with patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text",
            return_value=self._mock_transport_ok(),
        ) as mocked:
            result = self.Out.with_user(self.manager).service_send_message(
                {
                    "destination": "201007771111",
                    "body": "Hello P3",
                    "client_request_id": "p3-create-1",
                    "related_model": "res.partner",
                    "related_res_id": self.partner.id,
                    "partner_id": self.partner.id,
                    "purpose": "crm",
                    "source_app": "hub",
                    "instance_id": self.hub_inst.id,
                    "send_now": True,
                }
            )
            mocked.assert_called_once()
        self.assertFalse(result["duplicate"])
        self.assertTrue(result["message_id"])
        self.assertTrue(result["outbound_id"])
        msg = self.Message.browse(result["message_id"])
        out = self.Out.browse(result["outbound_id"])
        self.assertEqual(msg.direction, "out")
        self.assertEqual(out.transport_mode, "unified_bridge")
        self.assertEqual(out.state, "sent")
        self.assertEqual(msg.evolution_message_id, "P3EVOOK1")
        self.assertEqual(msg.partner_id, self.partner)
        self.assertEqual(msg.purpose, "crm")

    def test_idempotent_replay_no_duplicate_transport(self):
        _enable_unified(self.env, self.hub_inst)
        payload = {
            "destination": "201007771112",
            "body": "Idempotent",
            "client_request_id": "p3-idem-1",
            "related_model": "res.partner",
            "related_res_id": self.partner.id,
            "instance_id": self.hub_inst.id,
            "purpose": "crm",
        }
        with patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text",
            return_value=self._mock_transport_ok(),
        ) as mocked:
            first = self.Out.with_user(self.manager).service_send_message(payload)
            second = self.Out.with_user(self.manager).service_send_message(payload)
            self.assertEqual(mocked.call_count, 1)
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["message_id"], second["message_id"])
        self.assertEqual(
            self.Message.search_count(
                [("client_request_id", "=", "p3-idem-1")]
            ),
            1,
        )
        self.assertEqual(
            self.Out.search_count([("client_request_id", "=", "p3-idem-1")]),
            1,
        )

    def test_different_client_request_new_message_same_conversation(self):
        _enable_unified(self.env, self.hub_inst)
        with patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text",
            side_effect=[
                self._mock_transport_ok("P3EVO_CONV_A"),
                self._mock_transport_ok("P3EVO_CONV_B"),
            ],
        ):
            a = self.Out.with_user(self.manager).service_send_message(
                {
                    "destination": "201007771113",
                    "body": "First",
                    "client_request_id": "p3-conv-a",
                    "related_model": "res.partner",
                    "related_res_id": self.partner.id,
                    "instance_id": self.hub_inst.id,
                    "purpose": "crm",
                }
            )
            b = self.Out.with_user(self.manager).service_send_message(
                {
                    "destination": "201007771113",
                    "body": "Second",
                    "client_request_id": "p3-conv-b",
                    "related_model": "res.partner",
                    "related_res_id": self.partner.id,
                    "instance_id": self.hub_inst.id,
                    "purpose": "crm",
                }
            )
        ma = self.Message.browse(a["message_id"])
        mb = self.Message.browse(b["message_id"])
        self.assertNotEqual(ma.id, mb.id)
        self.assertEqual(ma.conversation_id, mb.conversation_id)

    def test_instance_isolation(self):
        _enable_unified(self.env)
        inst_b = self.env["whatsapp.instance"].create(
            {
                "name": "P3 Hub Inst B",
                "api_url": "http://127.0.0.1:9",
                "api_key": "other",
                "instance_name": "p3-test-inst-b",
                "purpose": "other",
                "unified_outbound_enabled": True,
            }
        )
        self.hub_inst.unified_outbound_enabled = True
        with patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text",
            side_effect=[
                self._mock_transport_ok("P3EVO_ISO_A"),
                self._mock_transport_ok("P3EVO_ISO_B"),
            ],
        ):
            a = self.Out.with_user(self.manager).service_send_message(
                {
                    "destination": "201007771114",
                    "body": "Inst A",
                    "client_request_id": "p3-iso-a",
                    "related_model": "res.partner",
                    "related_res_id": 1,
                    "instance_id": self.hub_inst.id,
                    "purpose": "crm",
                }
            )
            b = self.Out.with_user(self.manager).service_send_message(
                {
                    "destination": "201007771114",
                    "body": "Inst B",
                    "client_request_id": "p3-iso-b",
                    "related_model": "res.partner",
                    "related_res_id": 1,
                    "instance_id": inst_b.id,
                    "purpose": "crm",
                }
            )
        ma = self.Message.browse(a["message_id"])
        mb = self.Message.browse(b["message_id"])
        self.assertNotEqual(ma.conversation_id, mb.conversation_id)

    def test_campaign_discuss_provenance(self):
        _enable_unified(self.env, self.hub_inst)
        with patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text",
            return_value=self._mock_transport_ok(),
        ):
            result = self.Out.with_user(self.manager).service_send_message(
                {
                    "destination": "201007771115",
                    "body": "Provenance",
                    "client_request_id": "p3-prov-1",
                    "related_model": "wa.campaign.line",
                    "related_res_id": 42,
                    "campaign_id": 7,
                    "campaign_line_id": 42,
                    "discuss_channel_id": 9,
                    "partner_id": self.partner.id,
                    "purpose": "campaign",
                    "source_app": "campaign",
                    "instance_id": self.hub_inst.id,
                }
            )
        msg = self.Message.browse(result["message_id"])
        self.assertEqual(msg.campaign_id, 7)
        self.assertEqual(msg.campaign_line_id, 42)
        self.assertEqual(msg.discuss_channel_id, 9)
        self.assertEqual(msg.source_app, "campaign")

    def test_failed_transport_updates_same_message(self):
        _enable_unified(self.env, self.hub_inst)
        with patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text",
            return_value=self._mock_transport_fail(temporary=False),
        ):
            result = self.Out.with_user(self.manager).service_send_message(
                {
                    "destination": "201007771116",
                    "body": "Fail me",
                    "client_request_id": "p3-fail-1",
                    "related_model": "res.partner",
                    "related_res_id": self.partner.id,
                    "instance_id": self.hub_inst.id,
                    "purpose": "crm",
                    "max_retries": 0,
                }
            )
        out = self.Out.browse(result["outbound_id"])
        msg = out.message_id
        self.assertEqual(out.state, "failed")
        self.assertEqual(msg.state, "failed")
        self.assertEqual(
            self.Message.search_count([("business_key", "=", out.business_key)]),
            1,
        )

    def test_retry_does_not_create_new_canonical_message(self):
        _enable_unified(self.env, self.hub_inst)
        with patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text",
            side_effect=[
                self._mock_transport_fail(temporary=True),
                self._mock_transport_ok("P3EVO_RETRY_OK"),
            ],
        ) as mocked:
            result = self.Out.with_user(self.manager).service_send_message(
                {
                    "destination": "201007771117",
                    "body": "Retry",
                    "client_request_id": "p3-retry-1",
                    "related_model": "res.partner",
                    "related_res_id": self.partner.id,
                    "instance_id": self.hub_inst.id,
                    "purpose": "crm",
                }
            )
            out = self.Out.browse(result["outbound_id"])
            msg_id = out.message_id.id
            self.assertEqual(out.state, "pending")
            out.action_send()
            self.assertEqual(mocked.call_count, 2)
        out.invalidate_recordset()
        self.assertEqual(out.state, "sent")
        self.assertEqual(out.message_id.id, msg_id)
        self.assertEqual(
            self.Message.search_count([("id", "=", msg_id)]),
            1,
        )

    def test_media_type_rejected(self):
        _enable_unified(self.env, self.hub_inst)
        with self.assertRaises(ValidationError):
            self.Out.with_user(self.manager).service_send_message(
                {
                    "destination": "201007771118",
                    "body": "x",
                    "message_type": "media",
                    "client_request_id": "p3-media-1",
                    "instance_id": self.hub_inst.id,
                }
            )

    def test_legacy_queue_outbound_unaffected_by_flag(self):
        """Clinic legacy API works even when unified flag is OFF."""
        self.env["ir.config_parameter"].sudo().set_param(
            "whatsapp_hub.unified_outbound_enabled", "False"
        )
        with patch(
            "odoo.addons.whatsapp_hub.models.whatsapp_outbound.requests.post"
        ) as mocked:
            class R:
                status_code = 200
                text = '{"key":{"id":"LEGACY1"}}'

                def json(self):
                    return {"key": {"id": "LEGACY1"}}

            mocked.return_value = R()
            result = self.Out.with_user(self.manager).service_queue_outbound(
                {
                    "destination": "201007771119",
                    "body": "Legacy clinic",
                    "purpose": "clinic",
                    "send_now": True,
                }
            )
            mocked.assert_called_once()
        self.assertEqual(result["api"], "service_queue_outbound")
        out = self.Out.browse(result["outbound_id"])
        self.assertEqual(out.transport_mode, "legacy_direct")
        self.assertEqual(out.state, "sent")
