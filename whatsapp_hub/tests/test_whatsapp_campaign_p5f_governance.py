# -*- coding: utf-8 -*-
"""P5F-A: Campaign Hub governance — allowlist lifecycle, eligibility, freeze UX."""
from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "whatsapp_hub", "whatsapp_p5f_governance")
class TestWhatsappCampaignP5FGovernance(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ICP = cls.env["ir.config_parameter"].sudo()
        cls.Routing = cls.env["whatsapp.campaign.hub.routing"]
        cls.Health = cls.env["whatsapp.campaign.hub.health"].sudo()
        cls.Out = cls.env["whatsapp.outbound.message"].sudo()
        cls.Message = cls.env["whatsapp.message"].sudo()
        cls.Campaign = cls.env["wa.campaign"].sudo()
        cls.env["whatsapp.instance"].sudo().search([("is_default", "=", True)]).write(
            {"is_default": False}
        )
        cls.hub_inst = cls.env["whatsapp.instance"].sudo().create(
            {
                "name": "P5F-A Inst",
                "api_url": "http://127.0.0.1:9",
                "api_key": "p5fa",
                "instance_name": "p5fa_%s"
                % fields.Datetime.now().strftime("%H%M%S%f"),
                "purpose": "other",
                "is_default": True,
                "unified_outbound_enabled": True,
                "campaign_cutover_enabled": True,
            }
        )
        cls.partner = cls.env["res.partner"].sudo().create(
            {"name": "Gov Alice", "phone": "201001112244"}
        )
        cls.ICP.set_param("whatsapp_hub.campaign_cutover_enabled", "False")
        cls.ICP.set_param("whatsapp_hub.campaign_hub_allowed_campaign_ids", "")
        cls.ICP.set_param("whatsapp_hub.unified_outbound_purposes", "discuss")

    def _make_campaign(self, mode="legacy", message="Hello {first}", send_mode="immediate"):
        camp = self.Campaign.create(
            {
                "name": "P5F-A %s" % mode,
                "message": message,
                "personalise": True,
                "target_model": "res.partner",
                "partner_ids": [(6, 0, self.partner.ids)],
                "send_mode": send_mode,
                "wa_outbound_mode": mode,
                "check_duplicates": False,
                "delay_between": 0,
            }
        )
        camp.action_generate_lines()
        return camp

    def test_01_completed_hub_removed_from_allowlist_no_critical(self):
        camp = self._make_campaign(mode="hub")
        self.Routing.service_allowlist_add(camp.id)
        line = camp.campaign_line_ids[:1]
        line.service_freeze_rendered_body()
        # Simulate historical Hub refs + completed, then remove allowlist
        line.write({"hub_message_id": 1, "hub_outbound_id": 1, "status": "sent"})
        camp.write({"state": "completed", "completed_date": fields.Datetime.now()})
        self.Routing.service_allowlist_remove(camp.id)
        result = self.Health.service_run_health_check(
            notify=False, create_activities=False
        )
        types = {i["type"] for i in result["issues"]}
        self.assertNotIn("hub_not_allowlisted", types)

    def test_02_completed_still_allowlisted_warning(self):
        camp = self._make_campaign(mode="hub")
        self.Routing.service_allowlist_add(camp.id)
        camp.write({"state": "completed", "completed_date": fields.Datetime.now()})
        result = self.Health.service_run_health_check(
            notify=False, create_activities=False
        )
        self.assertTrue(
            any(
                i["type"] == "completed_campaign_still_allowlisted"
                for i in result["issues"]
            )
        )
        self.assertNotIn(
            "hub_not_allowlisted",
            {i["type"] for i in result["issues"] if i["severity"] == "critical"},
        )

    def test_03_active_hub_not_allowlisted_critical(self):
        camp = self._make_campaign(mode="hub")
        self.ICP.set_param("whatsapp_hub.campaign_hub_allowed_campaign_ids", "")
        result = self.Health.service_run_health_check(
            notify=False, create_activities=False
        )
        self.assertTrue(
            any(i["type"] == "hub_not_allowlisted" for i in result["issues"])
        )
        self.assertEqual(result["status"], "critical")

    def test_04_active_allowlisted_hub_healthy_allowlist(self):
        camp = self._make_campaign(mode="hub")
        self.Routing.service_allowlist_add(camp.id)
        result = self.Health.service_run_health_check(
            notify=False, create_activities=False
        )
        types = {i["type"] for i in result["issues"]}
        self.assertNotIn("hub_not_allowlisted", types)
        self.assertNotIn("completed_campaign_still_allowlisted", types)

    def test_05_06_multi_allowlist_and_history(self):
        a = self._make_campaign(mode="hub")
        b = self._make_campaign(mode="hub")
        self.Routing.service_allowlist_add(a.id)
        self.Routing.service_allowlist_add(b.id)
        ids = self.Routing.get_allowlist_ids()
        self.assertEqual(set(ids), {a.id, b.id})
        result = self.Health.service_run_health_check(
            notify=False, create_activities=False
        )
        self.assertEqual(result.get("allowlisted_campaign_count"), 2)
        self.assertNotIn(
            "hub_not_allowlisted", {i["type"] for i in result["issues"]}
        )

    def test_07_08_09_10_approve_helper(self):
        camp = self._make_campaign(mode="legacy", send_mode="immediate")
        camp.action_hub_approve_for_allowlist()
        self.assertTrue(self.Routing.is_campaign_allowlisted(camp.id))
        # idempotent
        camp.action_hub_approve_for_allowlist()
        self.assertEqual(self.Routing.get_allowlist_ids().count(camp.id), 1)
        # attachments rejected
        att = self.env["ir.attachment"].sudo().create(
            {
                "name": "x.txt",
                "datas": "aGVsbG8=",
                "res_model": "wa.campaign",
                "res_id": camp.id,
            }
        )
        camp.attachment_ids = [(4, att.id)]
        with self.assertRaises(UserError):
            camp.action_hub_approve_for_allowlist()
        camp.attachment_ids = [(5, att.id)]
        # scheduled rejected
        sched = self._make_campaign(send_mode="scheduled")
        with self.assertRaises(UserError):
            sched.action_hub_approve_for_allowlist()
        # queue + scheduled_date rejected
        q = self._make_campaign(send_mode="queue")
        q.scheduled_date = fields.Datetime.now()
        with self.assertRaises(UserError):
            q.action_hub_approve_for_allowlist()

    def test_11_12_revoke_and_incomplete(self):
        camp = self._make_campaign(mode="legacy")
        camp.action_hub_approve_for_allowlist()
        camp.action_hub_revoke_allowlist()
        self.assertFalse(self.Routing.is_campaign_allowlisted(camp.id))
        camp.action_hub_approve_for_allowlist()
        # incomplete job blocks revoke
        self.Out.create(
            {
                "name": "inc",
                "state": "pending",
                "transport_mode": "unified_bridge",
                "destination": "201001112244",
                "body": "x",
                "message_type": "text",
                "purpose": "campaign",
                "source_app": "campaign",
                "business_key": "campaign:%s:tmp" % camp.id,
                "client_request_id": "campaign:%s:tmp" % camp.id,
                "campaign_id": camp.id,
                "instance_id": self.hub_inst.id,
                "priority": 3,
            }
        )
        with self.assertRaises(UserError):
            camp.action_hub_revoke_allowlist()

    def test_13_14_15_16_freeze_and_rerender(self):
        camp = self._make_campaign(message="Freeze {first}")
        res = camp.action_freeze_campaign_lines_for_hub()
        self.assertTrue(res)
        line = camp.campaign_line_ids[:1]
        self.assertTrue(line.rendered_locked)
        self.assertEqual(line.rendered_body, "Freeze Gov")
        # idempotent freeze
        camp.action_freeze_campaign_lines_for_hub()
        at1 = line.rendered_at
        camp.message = "Changed {first}"
        line.action_admin_rerender_for_hub()
        line.invalidate_recordset()
        self.assertEqual(line.rendered_body, "Changed Gov")
        self.assertTrue(line.rendered_locked)
        # block after hub refs
        line.write({"hub_message_id": 99, "hub_outbound_id": 99})
        with self.assertRaises(UserError):
            line.action_admin_rerender_for_hub()

    def test_17_18_19_20_eligibility_helpers(self):
        ok = self._make_campaign(send_mode="immediate")
        ok.invalidate_recordset()
        self.assertTrue(ok.wa_hub_eligible)
        self.assertEqual(ok.wa_hub_eligibility_reason, "eligible")
        sched = self._make_campaign(send_mode="scheduled")
        sched.invalidate_recordset()
        self.assertFalse(sched.wa_hub_eligible)
        self.assertEqual(sched.wa_hub_eligibility_reason, "scheduled_not_supported")
        media = self._make_campaign()
        att = self.env["ir.attachment"].sudo().create(
            {
                "name": "m.txt",
                "datas": "aGVsbG8=",
                "res_model": "wa.campaign",
                "res_id": media.id,
            }
        )
        media.attachment_ids = [(4, att.id)]
        media.invalidate_recordset()
        self.assertFalse(media.wa_hub_eligible)
        self.assertEqual(media.wa_hub_eligibility_reason, "attachments_media")
        done = self._make_campaign()
        done.write({"state": "completed", "completed_date": fields.Datetime.now()})
        done.invalidate_recordset()
        self.assertFalse(done.wa_hub_eligible)
        self.assertEqual(done.wa_hub_eligibility_reason, "completed")

    def test_21_ops_helpers(self):
        camp = self._make_campaign(mode="hub")
        camp.action_hub_approve_for_allowlist()
        camp.action_freeze_campaign_lines_for_hub()
        camp.invalidate_recordset()
        self.assertTrue(camp.wa_hub_allowlisted)
        self.assertTrue(camp.wa_hub_active_authorization)
        self.assertTrue(camp.wa_hub_render_ready)
        self.assertGreaterEqual(camp.wa_hub_locked_line_count, 1)
        camp.write({"state": "completed"})
        camp.invalidate_recordset()
        self.assertTrue(camp.wa_hub_requires_allowlist_cleanup)
        camp.action_hub_cleanup_completed_allowlist()
        camp.invalidate_recordset()
        self.assertFalse(camp.wa_hub_allowlisted)

    def test_22_health_no_mutation(self):
        camp = self._make_campaign()
        allow = self.ICP.get_param("whatsapp_hub.campaign_hub_allowed_campaign_ids")
        mode = camp.wa_outbound_mode
        self.Health.service_run_health_check(notify=False, create_activities=False)
        camp.invalidate_recordset()
        self.assertEqual(camp.wa_outbound_mode, mode)
        self.assertEqual(
            self.ICP.get_param("whatsapp_hub.campaign_hub_allowed_campaign_ids"), allow
        )
