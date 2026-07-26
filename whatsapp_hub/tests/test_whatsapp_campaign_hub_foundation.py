# -*- coding: utf-8 -*-
"""Phase 5A: Campaign Hub foundation — identity, flags, shadow, quarantine stub."""
from odoo.tests import tagged, new_test_user
from odoo.tests.common import TransactionCase
from odoo import fields

from odoo.addons.whatsapp_hub.models.whatsapp_message import campaign_business_key


@tagged("post_install", "-at_install", "whatsapp_hub", "whatsapp_p5a_campaign")
class TestWhatsappCampaignHubFoundation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ICP = cls.env["ir.config_parameter"].sudo()
        cls.Routing = cls.env["whatsapp.campaign.hub.routing"]
        cls.Out = cls.env["whatsapp.outbound.message"]
        cls.hub_inst = cls.env["whatsapp.instance"].sudo().create(
            {
                "name": "P5A Campaign Inst",
                "api_url": "http://127.0.0.1:9",
                "api_key": "p5a-key",
                "instance_name": "p5a_camp_inst_%s"
                % fields.Datetime.now().strftime("%H%M%S%f"),
                "purpose": "other",
                "unified_outbound_enabled": True,
                "campaign_cutover_enabled": True,
            }
        )
        # Prefer this instance for resolve_hub_instance fallback
        cls.env["whatsapp.instance"].sudo().search(
            [("is_default", "=", True)]
        ).write({"is_default": False})
        cls.hub_inst.is_default = True
        # Keep Campaign cutover OFF by default (P5A production posture).
        cls.ICP.set_param("whatsapp_hub.campaign_cutover_enabled", "False")
        cls.ICP.set_param("whatsapp_hub.campaign_hub_allowed_campaign_ids", "")
        cls.Campaign = cls.env["wa.campaign"].sudo()
        cls.Line = cls.env["wa.campaign.line"].sudo()
        cls.partner = cls.env["res.partner"].sudo().create(
            {"name": "P5A Partner", "phone": "201009990088"}
        )

    def _make_campaign(self, mode="legacy", with_attachment=False):
        camp = self.Campaign.create(
            {
                "name": "P5A Test Campaign",
                "message": "Hello {name}",
                "target_model": "res.partner",
                "partner_ids": [(6, 0, [self.partner.id])],
                "send_mode": "immediate",
                "wa_outbound_mode": mode,
            }
        )
        if with_attachment:
            att = self.env["ir.attachment"].sudo().create(
                {
                    "name": "p5a.txt",
                    "datas": "dGVzdA==",
                    "res_model": "wa.campaign",
                    "res_id": camp.id,
                }
            )
            camp.attachment_ids = [(6, 0, [att.id])]
        camp.action_generate_lines()
        return camp

    def test_campaign_business_key_format(self):
        self.assertEqual(campaign_business_key(7, 42), "campaign:7:42")

    def test_default_mode_legacy(self):
        camp = self._make_campaign()
        self.assertEqual(camp.wa_outbound_mode, "legacy")

    def test_text_eligible_blocks_attachments(self):
        camp = self._make_campaign(with_attachment=True)
        ok, err = self.Routing.text_eligible(camp)
        self.assertFalse(ok)
        self.assertIn("attachment", err.lower())

    def test_hub_prerequisites_fail_closed_without_flags(self):
        camp = self._make_campaign(mode="hub")
        ok, err = self.Routing.hub_cutover_prerequisites(camp)
        self.assertFalse(ok)
        self.assertTrue(err)

    def test_hub_prerequisites_require_allowlist(self):
        camp = self._make_campaign(mode="hub")
        self.ICP.set_param("whatsapp_hub.unified_outbound_enabled", "True")
        self.ICP.set_param("whatsapp_hub.campaign_cutover_enabled", "True")
        self.ICP.set_param("whatsapp_hub.unified_outbound_purposes", "discuss,campaign")
        self.ICP.set_param("whatsapp_hub.campaign_hub_allowed_campaign_ids", "")
        ok, err = self.Routing.hub_cutover_prerequisites(camp)
        self.assertFalse(ok)
        self.assertIn("fail-closed", err.lower())

    def test_hub_prerequisites_ok_when_configured(self):
        camp = self._make_campaign(mode="hub")
        self.ICP.set_param("whatsapp_hub.unified_outbound_enabled", "True")
        self.ICP.set_param("whatsapp_hub.campaign_cutover_enabled", "True")
        self.ICP.set_param("whatsapp_hub.unified_outbound_purposes", "discuss,campaign")
        self.ICP.set_param(
            "whatsapp_hub.campaign_hub_allowed_campaign_ids", str(camp.id)
        )
        ok, err = self.Routing.hub_cutover_prerequisites(camp)
        self.assertTrue(ok, err)

    def test_build_candidate_does_not_create_outbound(self):
        camp = self._make_campaign(mode="shadow")
        line = camp.campaign_line_ids[:1]
        before = self.Out.sudo().search_count([])
        preview = self.Routing.service_preview_campaign_hub(camp, line)
        after = self.Out.sudo().search_count([])
        self.assertTrue(preview["eligible"])
        self.assertEqual(
            preview["candidate"]["business_key"],
            campaign_business_key(camp.id, line.id),
        )
        self.assertEqual(preview["candidate"]["priority"], 3)
        self.assertEqual(before, after)
        self.assertFalse(
            self.env["whatsapp.message"]
            .sudo()
            .search([("business_key", "=", preview["candidate"]["business_key"])])
        )

    def test_shadow_record_from_preview(self):
        camp = self._make_campaign(mode="shadow")
        line = camp.campaign_line_ids[:1]
        preview = self.Routing.build_hub_candidate(camp, line, body="hi")
        rec = self.env["whatsapp.campaign.shadow"].record_from_preview(
            campaign=camp, line=line, preview=preview, notes="p5a"
        )
        self.assertEqual(rec.campaign_id, camp.id)
        self.assertEqual(rec.campaign_line_id, line.id)
        self.assertEqual(
            rec.candidate_business_key, campaign_business_key(camp.id, line.id)
        )

    def test_quarantine_campaign_cancels_pending_only(self):
        camp = self._make_campaign(mode="hub")
        line = camp.campaign_line_ids[:1]
        biz = campaign_business_key(camp.id, line.id)
        job = self.Out.sudo().create(
            {
                "name": "P5A quarantine",
                "state": "pending",
                "transport_mode": "unified_bridge",
                "destination": line.phone,
                "body": "x",
                "message_type": "text",
                "purpose": "campaign",
                "source_app": "campaign",
                "business_key": biz,
                "client_request_id": biz,
                "campaign_id": camp.id,
                "campaign_line_id": line.id,
                "instance_id": self.hub_inst.id,
            }
        )
        # Discuss-looking job must not be touched
        discuss_biz = f"discuss:5:p5a-{job.id}"
        discuss_job = self.Out.sudo().create(
            {
                "name": "P5A discuss protect",
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
        manager = new_test_user(
            self.env,
            login="p5a_hub_mgr_%s" % camp.id,
            groups="whatsapp_hub.group_whatsapp_manager,base.group_system",
        )
        result = self.Out.with_user(manager).service_quarantine_campaign(
            camp.id, reason="p5a test"
        )
        self.assertEqual(result["cancelled"], 1)
        self.assertEqual(job.state, "cancelled")
        self.assertEqual(discuss_job.state, "pending")

    def test_process_queue_still_legacy_default(self):
        """P5A must not route Start through Hub when mode=legacy (flags off)."""
        camp = self._make_campaign(mode="legacy")
        # Mark no pending after skip — ensure helper never auto-sends
        ok, _ = camp._wa_hub_cutover_prerequisites()
        self.assertFalse(ok)
        # Source still imports _send_via_evolution in processor
        import inspect
        from odoo.addons.evolution_whatsapp_chat.models import wa_campaign as mod

        src = inspect.getsource(mod.WhatsAppCampaign._process_campaign_queue_legacy)
        self.assertIn("_send_via_evolution", src)
        self.assertNotIn("service_send_message", src)
        self.assertNotIn("service_queue_outbound", src)
        hub_src = inspect.getsource(mod.WhatsAppCampaign._process_campaign_queue_hub)
        self.assertNotIn("_send_via_evolution(", hub_src)
        self.assertNotIn("integration.outbound.queue", hub_src)
