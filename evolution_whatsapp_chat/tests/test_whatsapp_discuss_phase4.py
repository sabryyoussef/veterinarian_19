# -*- coding: utf-8 -*-
"""Phase 4: Discuss shadow mode + flagged Hub cutover."""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged, new_test_user


def _enable_discuss_hub(env, hub_instance=None, allowed_channel_ids=None):
    ICP = env["ir.config_parameter"].sudo()
    ICP.set_param("whatsapp_hub.unified_outbound_enabled", "True")
    ICP.set_param("whatsapp_hub.discuss_cutover_enabled", "True")
    if allowed_channel_ids is not None:
        ICP.set_param(
            "whatsapp_hub.discuss_hub_allowed_channel_ids",
            ",".join(str(i) for i in allowed_channel_ids),
        )
    if hub_instance:
        hub_instance.sudo().write(
            {
                "unified_outbound_enabled": True,
                "discuss_cutover_enabled": True,
            }
        )


def _disable_all_flags(env, hub_instance=None):
    ICP = env["ir.config_parameter"].sudo()
    ICP.set_param("whatsapp_hub.unified_outbound_enabled", "False")
    ICP.set_param("whatsapp_hub.discuss_cutover_enabled", "False")
    ICP.set_param("whatsapp_hub.discuss_hub_allowed_channel_ids", "")
    if hub_instance:
        hub_instance.sudo().write(
            {
                "unified_outbound_enabled": False,
                "discuss_cutover_enabled": False,
            }
        )


@tagged("post_install", "-at_install", "whatsapp_hub", "whatsapp_discuss_p4")
class TestWhatsappDiscussPhase4(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if "wa.message.log" not in cls.env:
            cls._skip_suite = True
            return
        cls._skip_suite = False
        cls.user = new_test_user(
            cls.env,
            login="wa_discuss_p4_user",
            groups="base.group_user,whatsapp_hub.group_whatsapp_manager",
        )
        cls.partner = cls.env["res.partner"].create(
            {"name": "P4 Discuss Partner", "phone": "201008881111"}
        )
        # Avoid unique default conflicts on shared test DBs
        existing_default = cls.env["whatsapp.instance"].sudo().search(
            [("is_default", "=", True)]
        )
        existing_default.write({"is_default": False})
        cls.hub_inst = cls.env["whatsapp.instance"].create(
            {
                "name": "P4 Hub Inst",
                "api_url": "http://127.0.0.1:9",
                "api_key": "secret-p4",
                "instance_name": "p4-test-inst",
                "purpose": "other",
                "is_default": True,
                "unified_outbound_enabled": False,
                "discuss_cutover_enabled": False,
            }
        )
        # Align Evolution default name used by Discuss helpers
        cls.env["ir.config_parameter"].sudo().set_param(
            "integration_bridge.evolution_instance", "p4-test-inst"
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "integration_bridge.evolution_url", "http://127.0.0.1:9"
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "integration_bridge.evolution_key", "test-key"
        )
        cls.channel = cls.env["discuss.channel"].sudo().create(
            {
                "name": "WA P4 Partner",
                "channel_type": "group",
                "wa_phone": "201008881111",
                "wa_partner_id": cls.partner.id,
                "wa_outbound_mode": "legacy",
            }
        )
        cls.channel.sudo().add_members(
            [cls.partner.id, cls.user.partner_id.id]
        )
        _disable_all_flags(cls.env, cls.hub_inst)

    def setUp(self):
        super().setUp()
        if getattr(self, "_skip_suite", False):
            self.skipTest("evolution_whatsapp_chat not installed")
        self.channel.wa_outbound_mode = "legacy"
        _disable_all_flags(self.env, self.hub_inst)

    def _mock_evo_ok(self, evo_id="P4LEGEVO1"):
        class Resp:
            ok = True
            status_code = 200
            text = '{"key":{"id":"%s"}}' % evo_id

            def json(self):
                return {"key": {"id": evo_id}}

        return Resp()

    def _mock_transport_ok(self, evo_id="P4HUBEVO1"):
        return {
            "ok": True,
            "accepted": True,
            "provider_message_id": evo_id,
            "http_status": 200,
            "error": False,
            "temporary": False,
            "response_excerpt": '{"key":{"id":"%s"}}' % evo_id,
            "bridge_instance_id": 1,
            "transport": "evolution.instance",
        }

    def _mock_transport_fail(self):
        return {
            "ok": False,
            "accepted": False,
            "provider_message_id": False,
            "http_status": 500,
            "error": "HTTP 500",
            "temporary": True,
            "response_excerpt": "fail",
            "bridge_instance_id": 1,
            "transport": "evolution.instance",
        }

    def _post_as_user(self, body="Hello P4"):
        return self.channel.with_user(self.user).message_post(
            body=f"<p>{body}</p>",
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
            author_id=self.user.partner_id.id,
        )

    # ── Flags OFF = legacy unchanged ──────────────────────────────────────────

    def test_20_flags_off_legacy_behavior(self):
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel.requests.post",
            return_value=self._mock_evo_ok("LEGACYOFF1"),
        ) as evo, patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text"
        ) as hub_t:
            msg = self._post_as_user("legacy baseline")
            self.assertEqual(evo.call_count, 1)
            hub_t.assert_not_called()
            logs = self.env["wa.message.log"].search(
                [("channel_id", "=", self.channel.id), ("mail_message_id", "=", msg.id)]
            )
            self.assertEqual(len(logs), 1)
            hub_msgs = self.env["whatsapp.message"].search(
                [("wa_message_log_id", "=", logs.id)]
            )
            self.assertEqual(len(hub_msgs), 1)
            outs = self.env["whatsapp.outbound.message"].search(
                [("transport_mode", "=", "unified_bridge"), ("discuss_channel_id", "=", self.channel.id)]
            )
            self.assertFalse(outs)

    # ── Shadow ────────────────────────────────────────────────────────────────

    def test_01_shadow_one_legacy_zero_hub_transport(self):
        self.channel.wa_outbound_mode = "shadow"
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel.requests.post",
            return_value=self._mock_evo_ok("SHADOW1"),
        ) as evo, patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text"
        ) as hub_t:
            msg = self._post_as_user("shadow text")
            self.assertEqual(evo.call_count, 1)
            hub_t.assert_not_called()
            outs = self.env["whatsapp.outbound.message"].search(
                [("discuss_channel_id", "=", self.channel.id)]
            )
            self.assertFalse(outs)
            shadows = self.env["whatsapp.discuss.shadow"].search(
                [("mail_message_id", "=", msg.id)]
            )
            self.assertEqual(len(shadows), 1)
            self.assertTrue(shadows.candidate_business_key.startswith("discuss:"))
            logs = self.env["wa.message.log"].search(
                [("mail_message_id", "=", msg.id)]
            )
            self.assertEqual(len(logs), 1)
            mirrored = self.env["whatsapp.message"].search(
                [("wa_message_log_id", "=", logs.id)]
            )
            self.assertEqual(len(mirrored), 1)
            self.assertEqual(shadows.mirrored_message_id, mirrored)
            self.assertEqual(mirrored.purpose, "discuss")

    def test_06_shadow_mismatch_does_not_block_legacy(self):
        self.channel.wa_outbound_mode = "shadow"
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel.requests.post",
            return_value=self._mock_evo_ok("SHADOWMIS"),
        ) as evo, patch(
            "odoo.addons.whatsapp_hub.models.whatsapp_outbound.WhatsappOutboundMessage.service_preview_send_message",
            return_value={
                "ok": False,
                "eligible": False,
                "classification": "invalid_destination",
                "errors": ["forced preview fail"],
                "candidate": {},
            },
        ):
            msg = self._post_as_user("shadow mismatch")
            self.assertEqual(evo.call_count, 1)
            shadows = self.env["whatsapp.discuss.shadow"].search(
                [("mail_message_id", "=", msg.id)]
            )
            self.assertEqual(len(shadows), 1)
            self.assertFalse(shadows.eligible)

    def test_07_replay_same_mail_message_no_extra_mirror(self):
        """Mirror is keyed by wa.log; re-sending creates a new mail.message."""
        self.channel.wa_outbound_mode = "legacy"
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel.requests.post",
            return_value=self._mock_evo_ok("REPLAY1"),
        ):
            msg = self._post_as_user("once")
        log = self.env["wa.message.log"].search(
            [("mail_message_id", "=", msg.id)], limit=1
        )
        hub1 = self.env["whatsapp.message"].search(
            [("wa_message_log_id", "=", log.id)]
        )
        self.assertEqual(len(hub1), 1)
        # Re-mirror same log must not duplicate
        self.env["whatsapp.hub.compat"].mirror_wa_message_log(log)
        hub2 = self.env["whatsapp.message"].search(
            [("wa_message_log_id", "=", log.id)]
        )
        self.assertEqual(len(hub2), 1)

    # ── Hub mode ──────────────────────────────────────────────────────────────

    def test_08_hub_zero_legacy_one_transport(self):
        _enable_discuss_hub(
            self.env, self.hub_inst, allowed_channel_ids=[self.channel.id]
        )
        self.channel.wa_outbound_mode = "hub"
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel.requests.post"
        ) as evo, patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text",
            return_value=self._mock_transport_ok("HUB1"),
        ) as hub_t:
            msg = self._post_as_user("hub text")
            evo.assert_not_called()
            self.assertEqual(hub_t.call_count, 1)
            biz = f"discuss:{self.channel.id}:{msg.id}"
            hub_msgs = self.env["whatsapp.message"].search(
                [("business_key", "=", biz)]
            )
            self.assertEqual(len(hub_msgs), 1)
            outs = self.env["whatsapp.outbound.message"].search(
                [("business_key", "=", biz)]
            )
            self.assertEqual(len(outs), 1)
            logs = self.env["wa.message.log"].search(
                [("mail_message_id", "=", msg.id), ("send_origin", "=", "hub_unified")]
            )
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs.hub_message_id, hub_msgs)
            # Mirror must not create a second Hub message
            all_for_channel = self.env["whatsapp.message"].search(
                [("discuss_channel_id", "=", self.channel.id), ("body", "ilike", "hub text")]
            )
            self.assertEqual(len(all_for_channel), 1)

    def test_13_hub_idempotent_replay(self):
        _enable_discuss_hub(
            self.env, self.hub_inst, allowed_channel_ids=[self.channel.id]
        )
        self.channel.wa_outbound_mode = "hub"
        with patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text",
            return_value=self._mock_transport_ok("HUBIDEM"),
        ) as hub_t:
            msg = self._post_as_user("idempotent")
            biz = f"discuss:{self.channel.id}:{msg.id}"
            Out = self.env["whatsapp.outbound.message"]
            r2 = Out.sudo().service_send_message(
                {
                    "destination": self.channel.wa_phone,
                    "body": "idempotent",
                    "business_key": biz,
                    "client_request_id": biz,
                    "purpose": "discuss",
                    "source_app": "discuss",
                    "related_model": "mail.message",
                    "related_res_id": msg.id,
                    "discuss_channel_id": self.channel.id,
                    "instance_id": self.hub_inst.id,
                    "send_now": True,
                }
            )
            self.assertTrue(r2.get("duplicate"))
            self.assertEqual(hub_t.call_count, 1)

    def test_14_15_second_message_same_conversation(self):
        _enable_discuss_hub(
            self.env, self.hub_inst, allowed_channel_ids=[self.channel.id]
        )
        self.channel.wa_outbound_mode = "hub"
        with patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text",
            return_value=self._mock_transport_ok("HUBA"),
        ):
            m1 = self._post_as_user("first")
        with patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text",
            return_value=self._mock_transport_ok("HUBB"),
        ):
            m2 = self._post_as_user("second")
        h1 = self.env["whatsapp.message"].search(
            [("business_key", "=", f"discuss:{self.channel.id}:{m1.id}")]
        )
        h2 = self.env["whatsapp.message"].search(
            [("business_key", "=", f"discuss:{self.channel.id}:{m2.id}")]
        )
        self.assertEqual(len(h1), 1)
        self.assertEqual(len(h2), 1)
        self.assertNotEqual(h1.id, h2.id)
        self.assertEqual(h1.conversation_id, h2.conversation_id)
        self.assertEqual(h1.partner_id, self.partner)
        self.assertEqual(h1.discuss_channel_id, self.channel.id)

    def test_18_post_admission_no_legacy_fallback(self):
        _enable_discuss_hub(
            self.env, self.hub_inst, allowed_channel_ids=[self.channel.id]
        )
        self.channel.wa_outbound_mode = "hub"
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel.requests.post"
        ) as evo, patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text",
            return_value=self._mock_transport_fail(),
        ):
            self._post_as_user("will fail")
            evo.assert_not_called()
            outs = self.env["whatsapp.outbound.message"].search(
                [
                    ("discuss_channel_id", "=", self.channel.id),
                    ("state", "in", ("failed", "pending")),
                ]
            )
            self.assertTrue(outs)
            # Temporary failures stay pending for Hub retry (not legacy).
            self.assertTrue(all(o.transport_mode == "unified_bridge" for o in outs))

    def test_19_unsupported_attachment_hub(self):
        _enable_discuss_hub(
            self.env, self.hub_inst, allowed_channel_ids=[self.channel.id]
        )
        self.channel.wa_outbound_mode = "hub"
        Att = self.env["ir.attachment"].create(
            {
                "name": "doc.txt",
                "datas": b"dGVzdA==",
                "res_model": "discuss.channel",
                "res_id": self.channel.id,
            }
        )
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel.requests.post"
        ) as evo, patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text"
        ) as hub_t:
            self.channel.with_user(self.user).message_post(
                body="<p>with file</p>",
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
                author_id=self.user.partner_id.id,
                attachment_ids=[Att.id],
            )
            evo.assert_not_called()
            hub_t.assert_not_called()

    def test_hub_mode_flags_off_fails_without_legacy(self):
        self.channel.wa_outbound_mode = "hub"
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel.requests.post"
        ) as evo, patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text"
        ) as hub_t:
            self._post_as_user("blocked hub")
            evo.assert_not_called()
            hub_t.assert_not_called()

    def test_21_campaign_still_uses_legacy(self):
        """Campaign path still imports _send_via_evolution — not Discuss wrapper."""
        from odoo.addons.evolution_whatsapp_chat.models.discuss_channel import (
            _send_via_evolution,
        )

        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel.requests.post",
            return_value=self._mock_evo_ok("CAMP1"),
        ) as evo, patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text"
        ) as hub_t:
            ok, _resp, wid = _send_via_evolution(
                self.env,
                "201008881111",
                "campaign regression",
                campaign_id=False,
            )
            self.assertTrue(ok)
            self.assertEqual(evo.call_count, 1)
            hub_t.assert_not_called()
            self.assertTrue(wid)

    # ── E1 allowlist hardening ────────────────────────────────────────────────

    def test_e1_allowlist_channel_allowed(self):
        _enable_discuss_hub(
            self.env, self.hub_inst, allowed_channel_ids=[self.channel.id]
        )
        self.channel.wa_outbound_mode = "hub"
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel.requests.post"
        ) as evo, patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text",
            return_value=self._mock_transport_ok("E1ALLOW"),
        ) as hub_t:
            self._post_as_user("allowlist ok")
            evo.assert_not_called()
            self.assertEqual(hub_t.call_count, 1)

    def test_e1_hub_mode_not_in_allowlist_blocked(self):
        other = self.env["discuss.channel"].sudo().create(
            {
                "name": "WA P4 Other",
                "channel_type": "group",
                "wa_phone": "201008882222",
                "wa_outbound_mode": "hub",
            }
        )
        _enable_discuss_hub(
            self.env, self.hub_inst, allowed_channel_ids=[other.id]
        )
        self.channel.wa_outbound_mode = "hub"
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel.requests.post"
        ) as evo, patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text"
        ) as hub_t:
            self._post_as_user("not allowlisted")
            evo.assert_not_called()
            hub_t.assert_not_called()
            outs = self.env["whatsapp.outbound.message"].search(
                [("discuss_channel_id", "=", self.channel.id)]
            )
            self.assertFalse(outs)

    def test_e1_empty_allowlist_fail_closed(self):
        _enable_discuss_hub(self.env, self.hub_inst, allowed_channel_ids=[])
        self.env["ir.config_parameter"].sudo().set_param(
            "whatsapp_hub.discuss_hub_allowed_channel_ids", ""
        )
        self.channel.wa_outbound_mode = "hub"
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel.requests.post"
        ) as evo, patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text"
        ) as hub_t:
            self._post_as_user("empty allowlist")
            evo.assert_not_called()
            hub_t.assert_not_called()

    def test_e1_shadow_ignores_allowlist(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "whatsapp_hub.discuss_hub_allowed_channel_ids", "99999"
        )
        self.channel.wa_outbound_mode = "shadow"
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel.requests.post",
            return_value=self._mock_evo_ok("E1SHAD"),
        ) as evo, patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text"
        ) as hub_t:
            self._post_as_user("shadow ignore allowlist")
            self.assertEqual(evo.call_count, 1)
            hub_t.assert_not_called()

    def test_e1_legacy_ignores_hub_activation(self):
        _enable_discuss_hub(
            self.env, self.hub_inst, allowed_channel_ids=[self.channel.id]
        )
        self.channel.wa_outbound_mode = "legacy"
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel.requests.post",
            return_value=self._mock_evo_ok("E1LEG"),
        ) as evo, patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text"
        ) as hub_t:
            self._post_as_user("legacy ignore flags")
            self.assertEqual(evo.call_count, 1)
            hub_t.assert_not_called()
