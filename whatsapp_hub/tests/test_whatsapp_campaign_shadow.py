# -*- coding: utf-8 -*-
"""Phase 5C: Controlled Campaign Shadow — observational only (never Hub-send)."""
from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.whatsapp_hub.models.whatsapp_message import campaign_business_key


@tagged("post_install", "-at_install", "whatsapp_hub", "whatsapp_p5c_campaign")
class TestWhatsappCampaignShadow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ICP = cls.env["ir.config_parameter"].sudo()
        cls.Routing = cls.env["whatsapp.campaign.hub.routing"]
        cls.Shadow = cls.env["whatsapp.campaign.shadow"].sudo()
        cls.Out = cls.env["whatsapp.outbound.message"].sudo()
        cls.Message = cls.env["whatsapp.message"].sudo()
        cls.Campaign = cls.env["wa.campaign"].sudo()
        cls.env["whatsapp.instance"].sudo().search([("is_default", "=", True)]).write(
            {"is_default": False}
        )
        cls.hub_inst = cls.env["whatsapp.instance"].sudo().create(
            {
                "name": "P5C Camp Inst",
                "api_url": "http://127.0.0.1:9",
                "api_key": "p5c-key",
                "instance_name": "p5c_camp_%s"
                % fields.Datetime.now().strftime("%H%M%S%f"),
                "purpose": "other",
                "is_default": True,
                "unified_outbound_enabled": True,
                "campaign_cutover_enabled": False,
            }
        )
        cls.partner = cls.env["res.partner"].sudo().create(
            {"name": "P5C Partner", "phone": "201008881122"}
        )
        # Production-safe: Campaign Hub OFF
        cls.ICP.set_param("whatsapp_hub.campaign_cutover_enabled", "False")
        cls.ICP.set_param("whatsapp_hub.campaign_hub_allowed_campaign_ids", "")
        cls.ICP.set_param("whatsapp_hub.unified_outbound_purposes", "discuss")

    def _fake_send(self, env, phone, text, **kwargs):
        """Simulate legacy immediate send + wa.message.log (mirror may follow)."""
        from odoo.addons.evolution_whatsapp_chat.models.discuss_channel import (
            _create_wa_log,
        )

        wa_id = "P5C-LEGACY-%s" % (kwargs.get("campaign_line_id") or "x")
        _create_wa_log(
            env,
            phone,
            text,
            wa_id,
            partner_id=kwargs.get("partner_id"),
            lead_id=kwargs.get("lead_id"),
            campaign_id=kwargs.get("campaign_id"),
            campaign_line_id=kwargs.get("campaign_line_id"),
            send_origin="legacy",
        )
        return True, {"ok": True}, wa_id

    def _make_campaign(
        self, mode="shadow", n_lines=1, send_mode="immediate", with_attachment=False
    ):
        partners = self.partner
        if n_lines > 1:
            extras = []
            for i in range(n_lines - 1):
                extras.append(
                    self.env["res.partner"]
                    .sudo()
                    .create(
                        {
                            "name": "P5C P%d" % i,
                            "phone": "20100888%04d" % (3000 + i),
                        }
                    )
                )
            partners = self.partner | self.env["res.partner"].browse(
                [p.id for p in extras]
            )
        camp = self.Campaign.create(
            {
                "name": "P5C %s" % mode,
                "message": "Campaign Shadow Evidence {name}",
                "target_model": "res.partner",
                "partner_ids": [(6, 0, partners.ids)],
                "send_mode": send_mode,
                "wa_outbound_mode": mode,
                "check_duplicates": False,
                "delay_between": 0,
            }
        )
        if with_attachment:
            att = self.env["ir.attachment"].sudo().create(
                {
                    "name": "p5c.txt",
                    "datas": "dGVzdA==",
                    "res_model": "wa.campaign",
                    "res_id": camp.id,
                }
            )
            camp.attachment_ids = [(6, 0, [att.id])]
        camp.action_generate_lines()
        return camp

    def test_01_shadow_route_when_mode_shadow(self):
        camp = self._make_campaign(mode="shadow")
        decision = self.Routing.resolve_outbound_route(camp)
        self.assertEqual(decision["route"], "shadow")
        self.assertTrue(decision["ok"])

    def test_02_03_04_shadow_ignores_hub_gates(self):
        camp = self._make_campaign(mode="shadow")
        self.ICP.set_param("whatsapp_hub.campaign_cutover_enabled", "False")
        self.ICP.set_param("whatsapp_hub.campaign_hub_allowed_campaign_ids", "")
        self.ICP.set_param("whatsapp_hub.unified_outbound_purposes", "discuss")
        self.hub_inst.campaign_cutover_enabled = False
        decision = self.Routing.resolve_outbound_route(camp)
        self.assertEqual(decision["route"], "shadow")
        ok_hub, _ = self.Routing.hub_cutover_prerequisites(camp)
        self.assertFalse(ok_hub)
        # Shadow eligibility does not require hub gates
        ok_sh, err = self.Routing.shadow_eligible(camp)
        self.assertTrue(ok_sh, err)

    def test_05_06_preview_creates_zero_hub_records(self):
        camp = self._make_campaign(mode="shadow")
        line = camp.campaign_line_ids[:1]
        msg_before = self.Message.search_count([])
        out_before = self.Out.search_count([("purpose", "=", "campaign")])
        preview = self.Routing.service_preview_campaign_line(camp, line)
        self.assertTrue(preview["eligible"])
        cand = preview["candidate"]
        self.assertEqual(cand["business_key"], campaign_business_key(camp.id, line.id))
        self.assertEqual(cand["purpose"], "campaign")
        self.assertEqual(cand["source_app"], "campaign")
        self.assertEqual(cand["priority"], 3)
        self.assertEqual(self.Message.search_count([]), msg_before)
        self.assertEqual(
            self.Out.search_count([("purpose", "=", "campaign")]), out_before
        )
        self.assertFalse(
            self.Message.search([("business_key", "=", cand["business_key"])])
        )

    def test_07_08_09_immediate_shadow_once_evidence_matched(self):
        camp = self._make_campaign(mode="shadow", send_mode="immediate")
        out_before = self.Out.search_count([("purpose", "=", "campaign")])
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel._send_via_evolution",
            side_effect=self._fake_send,
        ) as evo, patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text"
        ) as hub, patch(
            "odoo.addons.whatsapp_hub.models.whatsapp_outbound.WhatsappOutboundMessage.service_send_message"
        ) as svc_send, patch(
            "odoo.addons.whatsapp_hub.models.whatsapp_outbound.WhatsappOutboundMessage.service_enqueue_message"
        ) as svc_enq:
            camp.action_start_campaign()
            self.assertEqual(evo.call_count, 1)
            hub.assert_not_called()
            svc_send.assert_not_called()
            svc_enq.assert_not_called()
        line = camp.campaign_line_ids[:1]
        self.assertEqual(line.status, "sent")
        self.assertFalse(line.hub_outbound_id)
        self.assertEqual(
            self.Out.search_count([("purpose", "=", "campaign")]), out_before
        )
        shadow = self.Shadow.search([("campaign_line_id", "=", line.id)], limit=1)
        self.assertTrue(shadow)
        self.assertEqual(shadow.classification, "matched")
        self.assertEqual(shadow.legacy_transport, "immediate")
        self.assertTrue(shadow.legacy_send_completed)
        self.assertTrue(shadow.wa_message_log_id)
        self.assertTrue(shadow.legacy_provider_message_id)

    def test_10_destination_mismatch(self):
        camp = self._make_campaign(mode="shadow")
        line = camp.campaign_line_ids[:1]
        preview = self.Routing.service_preview_campaign_line(camp, line)
        log = self.env["wa.message.log"].sudo().create(
            {
                "phone": "201099999999",
                "direction": "out",
                "message_text": line.message or camp.message,
                "wa_message_id": "MISMATCH-DEST",
                "delivery_status": "sent",
                "campaign_id": camp.id,
                "campaign_line_id": line.id,
                "send_origin": "legacy",
            }
        )
        rec = self.Shadow.classify_and_record(
            campaign=camp,
            line=line,
            preview=preview,
            legacy_transport="immediate",
            wa_log=log,
            legacy_send_ok=True,
        )
        self.assertEqual(rec.classification, "destination_mismatch")

    def test_11_instance_mismatch(self):
        camp = self._make_campaign(mode="shadow")
        line = camp.campaign_line_ids[:1]
        preview = self.Routing.service_preview_campaign_line(camp, line)
        digits = "".join(c for c in (line.phone or "") if c.isdigit())
        remote = "%s@s.whatsapp.net" % digits
        conv = self.env["whatsapp.conversation"].sudo().create(
            {
                "name": "P5C inst mismatch",
                "conversation_type": "dm",
                "remote_jid": remote,
                "purpose": "campaign",
                "instance_id": self.hub_inst.id,
                "instance_reference": self.hub_inst.instance_name,
                "identity_key": "p5c-inst-%s" % line.id,
            }
        )
        msg = self.Message.create(
            {
                "direction": "out",
                "state": "sent",
                "body": preview["candidate"].get("body") or "x",
                "business_key": "walog:p5c-inst-%s" % line.id,
                "client_request_id": "walog:p5c-inst-%s" % line.id,
                "remote_jid": remote,
                "purpose": "campaign",
                "source_app": "campaign",
                "instance_reference": "totally_other_instance",
                "conversation_id": conv.id,
                "dedupe_key": "p5c-inst-%s" % line.id,
            }
        )
        rec = self.Shadow.classify_and_record(
            campaign=camp,
            line=line,
            preview=preview,
            legacy_transport="immediate",
            mirrored_message=msg,
            legacy_send_ok=True,
        )
        self.assertEqual(rec.classification, "instance_mismatch")

    def test_12_body_mismatch(self):
        camp = self._make_campaign(mode="shadow")
        line = camp.campaign_line_ids[:1]
        preview = self.Routing.service_preview_campaign_line(
            camp, line, body="Campaign Shadow Evidence EXPECTED"
        )
        log = self.env["wa.message.log"].sudo().create(
            {
                "phone": line.phone,
                "direction": "out",
                "message_text": "TOTALLY DIFFERENT BODY",
                "wa_message_id": "MISMATCH-BODY",
                "delivery_status": "sent",
                "campaign_id": camp.id,
                "campaign_line_id": line.id,
                "send_origin": "legacy",
            }
        )
        rec = self.Shadow.classify_and_record(
            campaign=camp,
            line=line,
            preview=preview,
            legacy_transport="immediate",
            wa_log=log,
            legacy_send_ok=True,
        )
        self.assertEqual(rec.classification, "body_mismatch")

    def test_13_attachments_no_hub_transport(self):
        camp = self._make_campaign(mode="shadow", with_attachment=True)
        out_before = self.Out.search_count([("purpose", "=", "campaign")])
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel._send_via_evolution",
            side_effect=self._fake_send,
        ) as evo, patch(
            "odoo.addons.evolution_whatsapp_chat.models.whatsapp_bulk_wizard._send_media_evolution",
            return_value=True,
        ), patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text"
        ) as hub:
            camp.action_start_campaign()
            evo.assert_called()
            hub.assert_not_called()
        self.assertEqual(
            self.Out.search_count([("purpose", "=", "campaign")]), out_before
        )
        shadow = self.Shadow.search(
            [("campaign_id", "=", camp.id)], order="id desc", limit=1
        )
        self.assertTrue(shadow)
        self.assertEqual(shadow.classification, "has_attachments")

    def test_14_15_queue_mode_limited_evidence(self):
        camp = self._make_campaign(mode="shadow", send_mode="queue")
        Queue = self.env["integration.outbound.queue"].sudo()
        q_before = Queue.search_count([])
        out_before = self.Out.search_count([("purpose", "=", "campaign")])
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel._send_via_evolution"
        ) as evo, patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel._evo_config",
            return_value={
                "url": "http://127.0.0.1:9",
                "key": "k",
                "instance": "p5c",
                "instance_path": "p5c",
            },
        ), patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text"
        ) as hub:
            camp.action_start_campaign()
            evo.assert_not_called()
            hub.assert_not_called()
        self.assertEqual(
            self.Out.search_count([("purpose", "=", "campaign")]), out_before
        )
        line = camp.campaign_line_ids[:1]
        self.assertEqual(line.status, "sent")
        self.assertTrue(line.queue_id)
        self.assertGreater(Queue.search_count([]), q_before)
        shadow = self.Shadow.search([("campaign_line_id", "=", line.id)], limit=1)
        self.assertTrue(shadow)
        self.assertEqual(shadow.classification, "legacy_queue_limited_evidence")
        self.assertEqual(shadow.legacy_transport, "bridge_queue")
        self.assertTrue(shadow.legacy_queue_id)

    def test_16_replay_guard_no_duplicate_send(self):
        camp = self._make_campaign(mode="shadow", send_mode="immediate")
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel._send_via_evolution",
            side_effect=self._fake_send,
        ) as evo:
            camp.action_start_campaign()
            self.assertEqual(evo.call_count, 1)
        # Force line back to pending to simulate accidental reprocess
        line = camp.campaign_line_ids[:1]
        line.write({"status": "pending"})
        camp.write({"state": "running"})
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel._send_via_evolution",
            side_effect=self._fake_send,
        ) as evo2:
            camp._process_campaign_queue()
            evo2.assert_not_called()
        shadows = self.Shadow.search([("campaign_line_id", "=", line.id)])
        self.assertTrue(shadows.filtered(lambda s: s.classification == "replay_skipped"))

    def test_17_legacy_mode_unchanged(self):
        camp = self._make_campaign(mode="legacy", send_mode="immediate")
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel._send_via_evolution",
            return_value=(True, {"ok": True}, "LEGACY-P5C"),
        ) as evo, patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text"
        ) as hub:
            camp.action_start_campaign()
            evo.assert_called()
            hub.assert_not_called()
        self.assertFalse(
            self.Shadow.search([("campaign_id", "=", camp.id)])
        )

    def test_18_hub_branch_unchanged(self):
        camp = self._make_campaign(mode="hub")
        self.ICP.set_param("whatsapp_hub.unified_outbound_enabled", "True")
        self.ICP.set_param("whatsapp_hub.campaign_cutover_enabled", "True")
        self.ICP.set_param("whatsapp_hub.unified_outbound_purposes", "discuss,campaign")
        self.ICP.set_param(
            "whatsapp_hub.campaign_hub_allowed_campaign_ids", str(camp.id)
        )
        self.hub_inst.write(
            {"unified_outbound_enabled": True, "campaign_cutover_enabled": True}
        )
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel._send_via_evolution"
        ) as evo:
            camp._process_campaign_queue()
            evo.assert_not_called()
        line = camp.campaign_line_ids[:1]
        self.assertEqual(line.status, "pending")
        self.assertTrue(line.hub_outbound_id)
        # Restore Production-like purposes after this test
        self.ICP.set_param("whatsapp_hub.unified_outbound_purposes", "discuss")
        self.ICP.set_param("whatsapp_hub.campaign_cutover_enabled", "False")
        self.ICP.set_param("whatsapp_hub.campaign_hub_allowed_campaign_ids", "")

    def test_19_discuss_routing_untouched(self):
        """Discuss channel mode field exists; Campaign shadow does not mutate it."""
        Channel = self.env["discuss.channel"].sudo()
        ch = Channel.create(
            {
                "name": "P5C Discuss Guard",
                "wa_phone": "201001112233",
                "wa_outbound_mode": "hub",
            }
        )
        mode_before = ch.wa_outbound_mode
        camp = self._make_campaign(mode="shadow")
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel._send_via_evolution",
            side_effect=self._fake_send,
        ):
            camp.action_start_campaign()
        ch.invalidate_recordset()
        self.assertEqual(ch.wa_outbound_mode, mode_before)

    def test_20_quarantine_isolation(self):
        camp = self._make_campaign(mode="shadow")
        line = camp.campaign_line_ids[:1]
        discuss_biz = "discuss:5:p5c-iso-%s" % line.id
        discuss_job = self.Out.create(
            {
                "name": "P5C discuss protect",
                "state": "pending",
                "transport_mode": "unified_bridge",
                "destination": "201000000001",
                "body": "d",
                "message_type": "text",
                "purpose": "discuss",
                "source_app": "discuss",
                "business_key": discuss_biz,
                "client_request_id": discuss_biz,
                "discuss_channel_id": 5,
                "instance_id": self.hub_inst.id,
            }
        )
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel._send_via_evolution",
            side_effect=self._fake_send,
        ):
            camp.action_start_campaign()
        discuss_job.invalidate_recordset()
        self.assertEqual(discuss_job.state, "pending")
        self.assertEqual(discuss_job.purpose, "discuss")
