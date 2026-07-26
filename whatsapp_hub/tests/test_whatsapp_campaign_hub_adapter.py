# -*- coding: utf-8 -*-
"""Phase 5B: Campaign Hub adapter branch tests."""
from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged, new_test_user
from odoo.tests.common import TransactionCase

from odoo.addons.whatsapp_hub.models.whatsapp_message import campaign_business_key


@tagged("post_install", "-at_install", "whatsapp_hub", "whatsapp_p5b_campaign")
class TestWhatsappCampaignHubAdapter(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ICP = cls.env["ir.config_parameter"].sudo()
        cls.Routing = cls.env["whatsapp.campaign.hub.routing"]
        cls.Out = cls.env["whatsapp.outbound.message"].sudo()
        cls.Message = cls.env["whatsapp.message"].sudo()
        cls.Campaign = cls.env["wa.campaign"].sudo()
        # Clear other defaults
        cls.env["whatsapp.instance"].sudo().search([("is_default", "=", True)]).write(
            {"is_default": False}
        )
        cls.hub_inst = cls.env["whatsapp.instance"].sudo().create(
            {
                "name": "P5B Camp Inst",
                "api_url": "http://127.0.0.1:9",
                "api_key": "p5b-key",
                "instance_name": "p5b_camp_%s"
                % fields.Datetime.now().strftime("%H%M%S%f"),
                "purpose": "other",
                "is_default": True,
                "unified_outbound_enabled": True,
                "campaign_cutover_enabled": True,
            }
        )
        cls.partner = cls.env["res.partner"].sudo().create(
            {"name": "P5B Partner", "phone": "201009991122"}
        )
        # Production-safe defaults for most tests
        cls.ICP.set_param("whatsapp_hub.campaign_cutover_enabled", "False")
        cls.ICP.set_param("whatsapp_hub.campaign_hub_allowed_campaign_ids", "")

    def _enable_hub_flags(self, campaign):
        self.ICP.set_param("whatsapp_hub.unified_outbound_enabled", "True")
        self.ICP.set_param("whatsapp_hub.campaign_cutover_enabled", "True")
        self.ICP.set_param("whatsapp_hub.unified_outbound_purposes", "discuss,campaign")
        self.ICP.set_param(
            "whatsapp_hub.campaign_hub_allowed_campaign_ids", str(campaign.id)
        )
        self.hub_inst.write(
            {"unified_outbound_enabled": True, "campaign_cutover_enabled": True}
        )

    def _make_campaign(self, mode="legacy", n_lines=1, with_attachment=False):
        partners = self.partner
        if n_lines > 1:
            extra = []
            for i in range(n_lines - 1):
                extra.append(
                    self.env["res.partner"]
                    .sudo()
                    .create(
                        {
                            "name": "P5B P%d" % i,
                            "phone": "20100999%04d" % (2000 + i),
                        }
                    )
                )
            partners = self.partner | self.env["res.partner"].browse(
                [p.id for p in extra]
            )
        camp = self.Campaign.create(
            {
                "name": "P5B %s" % mode,
                "message": "Hello {name}",
                "target_model": "res.partner",
                "partner_ids": [(6, 0, partners.ids)],
                "send_mode": "immediate",
                "wa_outbound_mode": mode,
                "check_duplicates": False,
            }
        )
        if with_attachment:
            att = self.env["ir.attachment"].sudo().create(
                {
                    "name": "p5b.txt",
                    "datas": "dGVzdA==",
                    "res_model": "wa.campaign",
                    "res_id": camp.id,
                }
            )
            camp.attachment_ids = [(6, 0, [att.id])]
        camp.action_generate_lines()
        return camp

    def test_01_legacy_unchanged_when_mode_legacy(self):
        camp = self._make_campaign(mode="legacy")
        decision = self.Routing.resolve_outbound_route(camp)
        self.assertEqual(decision["route"], "legacy")
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel._send_via_evolution",
            return_value=(True, {"ok": True}, "LEGACY1"),
        ) as evo, patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text"
        ) as hub:
            camp.action_start_campaign()
            evo.assert_called()
            hub.assert_not_called()
        line = camp.campaign_line_ids[:1]
        self.assertEqual(line.status, "sent")
        self.assertFalse(line.hub_outbound_id)

    def test_02_flags_off_hub_mode_blocked(self):
        camp = self._make_campaign(mode="hub")
        self.ICP.set_param("whatsapp_hub.campaign_cutover_enabled", "False")
        decision = self.Routing.resolve_outbound_route(camp)
        self.assertEqual(decision["route"], "hub")
        self.assertFalse(decision["ok"])
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel._send_via_evolution"
        ) as evo, patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text"
        ) as hub:
            camp._process_campaign_queue()
            evo.assert_not_called()
            hub.assert_not_called()
        self.assertEqual(camp.campaign_line_ids[:1].status, "failed")

    def test_03_empty_allowlist_fail_closed(self):
        camp = self._make_campaign(mode="hub")
        self.ICP.set_param("whatsapp_hub.unified_outbound_enabled", "True")
        self.ICP.set_param("whatsapp_hub.campaign_cutover_enabled", "True")
        self.ICP.set_param("whatsapp_hub.unified_outbound_purposes", "discuss,campaign")
        self.ICP.set_param("whatsapp_hub.campaign_hub_allowed_campaign_ids", "")
        ok, err = self.Routing.hub_cutover_prerequisites(camp)
        self.assertFalse(ok)
        self.assertIn("fail-closed", err.lower())

    def test_04_not_in_allowlist_fail_closed(self):
        camp = self._make_campaign(mode="hub")
        self._enable_hub_flags(camp)
        self.ICP.set_param("whatsapp_hub.campaign_hub_allowed_campaign_ids", "999999")
        ok, _ = self.Routing.hub_cutover_prerequisites(camp)
        self.assertFalse(ok)

    def test_05_purpose_campaign_absent_blocked(self):
        camp = self._make_campaign(mode="hub")
        self._enable_hub_flags(camp)
        self.ICP.set_param("whatsapp_hub.unified_outbound_purposes", "discuss")
        ok, err = self.Routing.hub_cutover_prerequisites(camp)
        self.assertFalse(ok)
        self.assertIn("campaign", err.lower())

    def test_06_instance_campaign_flag_off_blocked(self):
        camp = self._make_campaign(mode="hub")
        self._enable_hub_flags(camp)
        self.hub_inst.campaign_cutover_enabled = False
        ok, err = self.Routing.hub_cutover_prerequisites(camp)
        self.assertFalse(ok)
        self.assertIn("instance", err.lower())

    def test_07_08_09_10_11_12_eligible_admit_idempotent_not_sent(self):
        camp = self._make_campaign(mode="hub")
        self._enable_hub_flags(camp)
        line = camp.campaign_line_ids[:1]
        Queue = self.env["integration.outbound.queue"].sudo()
        q_before = Queue.search_count([])
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel._send_via_evolution"
        ) as evo, patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text"
        ) as hub:
            camp._process_campaign_queue()
            evo.assert_not_called()
            hub.assert_not_called()  # enqueue only
        line.invalidate_recordset()
        self.assertEqual(line.status, "pending")
        self.assertTrue(line.hub_message_id)
        self.assertTrue(line.hub_outbound_id)
        biz = campaign_business_key(camp.id, line.id)
        msg = self.Message.browse(line.hub_message_id)
        self.assertEqual(msg.business_key, biz)
        job = self.Out.browse(line.hub_outbound_id)
        self.assertEqual(job.priority, 3)
        self.assertEqual(job.purpose, "campaign")
        self.assertEqual(Queue.search_count([]), q_before)
        # Idempotent replay
        mid, oid = line.hub_message_id, line.hub_outbound_id
        camp._process_campaign_queue()
        line.invalidate_recordset()
        self.assertEqual(line.hub_message_id, mid)
        self.assertEqual(line.hub_outbound_id, oid)
        self.assertEqual(
            self.Message.search_count([("business_key", "=", biz)]), 1
        )
        self.assertEqual(
            self.Out.search_count([("business_key", "=", biz)]), 1
        )

    def test_13_provider_success_projects_sent(self):
        camp = self._make_campaign(mode="hub")
        self._enable_hub_flags(camp)
        camp._process_campaign_queue()
        line = camp.campaign_line_ids[:1]
        job = self.Out.browse(line.hub_outbound_id)
        with patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text",
            return_value={
                "ok": True,
                "provider_message_id": "PROV-P5B-1",
                "http_status": 200,
                "transport": "bridge_oneshot",
            },
        ):
            job._send_one()
        line.invalidate_recordset()
        self.assertEqual(line.status, "sent")
        self.assertEqual(line.wa_message_id, "PROV-P5B-1")
        self.assertTrue(line.sent_date)

    def test_14_15_failure_and_retry_not_sent(self):
        camp = self._make_campaign(mode="hub")
        self._enable_hub_flags(camp)
        camp._process_campaign_queue()
        line = camp.campaign_line_ids[:1]
        job = self.Out.browse(line.hub_outbound_id)
        job.max_retries = 5
        with patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text",
            return_value={"ok": False, "error": "temp", "temporary": True},
        ):
            job._send_one()
        line.invalidate_recordset()
        job.invalidate_recordset()
        self.assertEqual(line.status, "pending")
        self.assertEqual(job.state, "pending")
        # Exhaust via permanent failure after retries
        job.retry_count = job.max_retries
        with patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text",
            return_value={"ok": False, "error": "perm", "temporary": False},
        ):
            job._send_one()
        line.invalidate_recordset()
        self.assertEqual(line.status, "failed")

    def test_16_17_compat_converges_no_walog_twin(self):
        camp = self._make_campaign(mode="hub")
        self._enable_hub_flags(camp)
        camp._process_campaign_queue()
        line = camp.campaign_line_ids[:1]
        biz = campaign_business_key(camp.id, line.id)
        log = self.env["wa.message.log"].sudo().search(
            [("campaign_line_id", "=", line.id), ("send_origin", "=", "hub_unified")],
            limit=1,
        )
        self.assertTrue(log)
        self.assertEqual(log.hub_message_id.id, line.hub_message_id)
        # Mirror must not create walog:* twin
        before = self.Message.search_count([])
        self.env["whatsapp.hub.compat"].sudo().mirror_wa_message_log(log)
        after = self.Message.search_count([])
        self.assertEqual(before, after)
        self.assertFalse(
            self.Message.search([("business_key", "=", "walog:%s" % log.id)])
        )
        self.assertEqual(
            self.Message.search([("business_key", "=", biz)], limit=1).id,
            line.hub_message_id,
        )

    def test_18_batch_size_limits(self):
        self.ICP.set_param("whatsapp_hub.campaign_admit_batch_size", "2")
        camp = self._make_campaign(mode="hub", n_lines=5)
        self._enable_hub_flags(camp)
        camp._process_campaign_queue()
        admitted = camp.campaign_line_ids.filtered(lambda l: l.hub_outbound_id)
        still_pending_no_hub = camp.campaign_line_ids.filtered(
            lambda l: l.status == "pending" and not l.hub_outbound_id
        )
        self.assertEqual(len(admitted), 2)
        self.assertEqual(len(still_pending_no_hub), 3)

    def test_19_backpressure_stops(self):
        self.ICP.set_param("whatsapp_hub.max_pending_campaign_jobs", "1")
        self.ICP.set_param("whatsapp_hub.campaign_admit_batch_size", "50")
        camp = self._make_campaign(mode="hub", n_lines=3)
        self._enable_hub_flags(camp)
        camp._process_campaign_queue()
        admitted = camp.campaign_line_ids.filtered(lambda l: l.hub_outbound_id)
        self.assertEqual(len(admitted), 1)
        remaining = camp.campaign_line_ids.filtered(
            lambda l: l.status == "pending" and not l.hub_outbound_id
        )
        self.assertEqual(len(remaining), 2)

    def test_20_priority_is_3(self):
        camp = self._make_campaign(mode="hub")
        self._enable_hub_flags(camp)
        camp._process_campaign_queue()
        job = self.Out.browse(camp.campaign_line_ids[:1].hub_outbound_id)
        self.assertEqual(job.priority, 3)

    def test_21_attachments_rejected_for_hub(self):
        camp = self._make_campaign(mode="hub", with_attachment=True)
        self._enable_hub_flags(camp)
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel._send_via_evolution"
        ) as evo:
            camp._process_campaign_queue()
            evo.assert_not_called()
        self.assertEqual(camp.campaign_line_ids[:1].status, "failed")
        self.assertFalse(camp.campaign_line_ids[:1].hub_outbound_id)

    def test_22_23_pause_and_resume_no_dup(self):
        self.ICP.set_param("whatsapp_hub.campaign_admit_batch_size", "1")
        camp = self._make_campaign(mode="hub", n_lines=3)
        self._enable_hub_flags(camp)
        camp.state = "running"
        camp._process_campaign_queue()
        self.assertEqual(
            len(camp.campaign_line_ids.filtered(lambda l: l.hub_outbound_id)), 1
        )
        camp.action_pause_campaign()
        before = self.Out.search_count([("purpose", "=", "campaign")])
        camp._process_campaign_queue()  # paused mid-state already paused
        # Resume admits next without duplicating first
        camp.action_resume_campaign()
        after = self.Out.search_count([("purpose", "=", "campaign")])
        self.assertGreaterEqual(after, before)
        first = camp.campaign_line_ids.filtered(lambda l: l.hub_outbound_id)[:1]
        biz = campaign_business_key(camp.id, first.id)
        self.assertEqual(self.Out.search_count([("business_key", "=", biz)]), 1)

    def test_24_25_quarantine_isolates_discuss(self):
        camp = self._make_campaign(mode="hub")
        self._enable_hub_flags(camp)
        camp._process_campaign_queue()
        line = camp.campaign_line_ids[:1]
        discuss_biz = "discuss:5:p5b-protect-%s" % line.id
        djob = self.Out.create(
            {
                "name": "protect discuss",
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
            login="p5b_q_%s" % camp.id,
            groups="whatsapp_hub.group_whatsapp_manager",
        )
        self.Out.with_user(manager).service_quarantine_campaign(camp.id, reason="t")
        line.invalidate_recordset()
        job = self.Out.browse(line.hub_outbound_id)
        self.assertEqual(job.state, "cancelled")
        self.assertEqual(djob.state, "pending")

    def test_26_legacy_path_green_flags_off(self):
        camp = self._make_campaign(mode="legacy")
        self.ICP.set_param("whatsapp_hub.campaign_cutover_enabled", "False")
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel._send_via_evolution",
            return_value=(True, {}, "L2"),
        ):
            camp.action_start_campaign()
        self.assertEqual(camp.campaign_line_ids[:1].status, "sent")
