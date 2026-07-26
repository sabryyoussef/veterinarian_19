# -*- coding: utf-8 -*-
"""E3: Discuss Hub health checks (read-only; no routing mutations)."""
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged, new_test_user


@tagged("post_install", "-at_install", "whatsapp_hub", "whatsapp_e3_health")
class TestWhatsappDiscussHubHealth(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env,
            login="wa_hub_e3_health",
            groups="whatsapp_hub.group_whatsapp_manager,base.group_system",
        )
        cls.Health = cls.env["whatsapp.discuss.hub.health"]
        cls.Out = cls.env["whatsapp.outbound.message"]
        cls.ICP = cls.env["ir.config_parameter"].sudo()
        # Clear existing defaults first (Test DB may retain UAT default instances).
        cls.env["whatsapp.instance"].sudo().search([("is_default", "=", True)]).write(
            {"is_default": False}
        )
        cls.hub_inst = cls.env["whatsapp.instance"].create(
            {
                "name": "E3 Health Inst",
                "api_url": "http://127.0.0.1:9",
                "api_key": "secret-e3",
                "instance_name": "e3-health-inst-%s"
                % fields.Datetime.now().strftime("%H%M%S%f"),
                "purpose": "other",
                "is_default": True,
                "unified_outbound_enabled": True,
                "discuss_cutover_enabled": True,
            }
        )
        cls.ICP.set_param("whatsapp_hub.unified_outbound_enabled", "True")
        cls.ICP.set_param("whatsapp_hub.discuss_cutover_enabled", "True")
        cls.channel = cls.env["discuss.channel"].sudo().create(
            {
                "name": "E3 WA Health",
                "channel_type": "group",
                "wa_phone": "201009991111",
                "wa_outbound_mode": "hub",
            }
        )
        cls.ICP.set_param(
            "whatsapp_hub.discuss_hub_allowed_channel_ids", str(cls.channel.id)
        )

    def setUp(self):
        super().setUp()
        # Isolate from other WA Hub channels already present on shared Test DBs.
        self.env["discuss.channel"].sudo().search(
            [("wa_outbound_mode", "=", "hub")]
        ).write({"wa_outbound_mode": "legacy"})
        self.channel.wa_outbound_mode = "hub"
        self.ICP.set_param(
            "whatsapp_hub.discuss_hub_allowed_channel_ids", str(self.channel.id)
        )
        singleton = self.Health._get_singleton()
        singleton.write({"last_issue_fingerprint": ""})
        # Clear open health activities on singleton
        self.env["mail.activity"].sudo().search(
            [
                ("res_model", "=", "whatsapp.discuss.hub.health"),
                ("res_id", "=", singleton.id),
            ]
        ).unlink()

    def _make_job(self, channel_id, state="pending", evo_id=False, age_minutes=0, body="h"):
        stamp = fields.Datetime.now().strftime("%Y%m%d%H%M%S%f")
        biz = f"discuss:{channel_id}:e3h-{stamp}-{body}"
        job = self.Out.sudo().create(
            {
                "name": f"E3H {body}",
                "state": state,
                "transport_mode": "unified_bridge",
                "destination": "201009991111",
                "body": body,
                "message_type": "text",
                "purpose": "discuss",
                "source_app": "discuss",
                "business_key": biz,
                "client_request_id": biz,
                "discuss_channel_id": channel_id,
                "evolution_message_id": evo_id or False,
                "instance_id": self.hub_inst.id,
            }
        )
        if age_minutes:
            old = fields.Datetime.now() - timedelta(minutes=age_minutes)
            self.env.cr.execute(
                "UPDATE whatsapp_outbound_message SET create_date=%s WHERE id=%s",
                (old, job.id),
            )
            job.invalidate_recordset()
        return job

    def test_hub_allowlisted_healthy(self):
        # Shared Test DBs may contain historical sent jobs for other channels;
        # only incomplete outside-allowlist jobs are critical.
        self.Out.sudo().search(
            [
                ("transport_mode", "=", "unified_bridge"),
                ("state", "in", ("pending", "processing")),
                ("discuss_channel_id", "!=", self.channel.id),
            ]
        ).write({"state": "cancelled", "next_retry_at": False})
        result = self.Health.service_run_health_check(
            notify=False, create_activities=False
        )
        critical = [i for i in result.get("issues", []) if i["severity"] == "critical"]
        if critical:
            self.fail("unexpected critical issues: %s" % critical)
        self.assertEqual(result["critical_count"], 0)
        self.assertIn(result["status"], ("healthy", "warning"))
        self.assertIn(self.channel.id, result["hub_channels"])

    def test_hub_not_allowlisted_critical(self):
        self.ICP.set_param("whatsapp_hub.discuss_hub_allowed_channel_ids", "999999")
        result = self.Health.service_run_health_check(
            notify=False, create_activities=False
        )
        self.assertEqual(result["status"], "critical")
        types = {i["type"] for i in result["issues"]}
        self.assertIn("hub_not_allowlisted", types)

    def test_allowlisted_missing_channel_critical(self):
        self.ICP.set_param(
            "whatsapp_hub.discuss_hub_allowed_channel_ids",
            f"{self.channel.id},888888",
        )
        result = self.Health.service_run_health_check(
            notify=False, create_activities=False
        )
        self.assertEqual(result["status"], "critical")
        self.assertTrue(
            any(i["type"] == "allowlist_missing_channel" for i in result["issues"])
        )

    def test_allowlisted_missing_jid_critical(self):
        # Create orphan allowlist id by using channel then clearing phone via SQL
        # Safer: create channel, allowlist it, clear wa_phone
        ch = self.env["discuss.channel"].sudo().create(
            {
                "name": "E3 no phone",
                "channel_type": "group",
                "wa_phone": "201009992222",
                "wa_outbound_mode": "legacy",
            }
        )
        self.ICP.set_param(
            "whatsapp_hub.discuss_hub_allowed_channel_ids",
            f"{self.channel.id},{ch.id}",
        )
        ch.write({"wa_phone": False})
        result = self.Health.service_run_health_check(
            notify=False, create_activities=False
        )
        self.assertTrue(
            any(i["type"] == "allowlist_missing_jid" for i in result["issues"])
        )

    def test_job_outside_allowlist_critical(self):
        other = self.env["discuss.channel"].sudo().create(
            {
                "name": "E3 outside",
                "channel_type": "group",
                "wa_phone": "201009993333",
                "wa_outbound_mode": "legacy",
            }
        )
        # Incomplete job outside allowlist is critical
        self._make_job(other.id, state="pending", body="out")
        result = self.Health.service_run_health_check(
            notify=False, create_activities=False
        )
        self.assertTrue(
            any(
                i["type"] == "job_outside_allowlist" and i["severity"] == "critical"
                for i in result["issues"]
            )
        )

    def test_stale_pending_critical(self):
        self._make_job(self.channel.id, state="pending", age_minutes=20, body="stale")
        result = self.Health.service_run_health_check(
            notify=False, create_activities=False
        )
        self.assertTrue(any(i["type"] == "stale_pending" for i in result["issues"]))

    def test_recent_legacy_leakage_critical(self):
        if "wa.message.log" not in self.env:
            self.skipTest("wa.message.log missing")
        Log = self.env["wa.message.log"].sudo()
        # Hub floor
        hub_log = Log.create(
            {
                "phone": self.channel.wa_phone,
                "direction": "out",
                "message_text": "hub floor",
                "channel_id": self.channel.id,
                "send_origin": "hub_unified",
                "delivery_status": "sent",
            }
        )
        # Leakage after floor
        Log.create(
            {
                "phone": self.channel.wa_phone,
                "direction": "out",
                "message_text": "legacy leak",
                "channel_id": self.channel.id,
                "send_origin": "legacy",
                "delivery_status": "sent",
            }
        )
        result = self.Health.service_run_health_check(
            notify=False, create_activities=False
        )
        self.assertTrue(any(i["type"] == "legacy_leakage" for i in result["issues"]))
        self.assertTrue(hub_log.exists())

    def test_historical_legacy_not_false_positive(self):
        if "wa.message.log" not in self.env:
            self.skipTest("wa.message.log missing")
        Log = self.env["wa.message.log"].sudo()
        # Only historical legacy, no hub_unified floor → no leakage issue
        Log.create(
            {
                "phone": self.channel.wa_phone,
                "direction": "out",
                "message_text": "old legacy",
                "channel_id": self.channel.id,
                "send_origin": "legacy",
                "delivery_status": "sent",
            }
        )
        result = self.Health.service_run_health_check(
            notify=False, create_activities=False
        )
        self.assertFalse(any(i["type"] == "legacy_leakage" for i in result["issues"]))

    def test_mid_migration_shadow_regression_not_false_positive(self):
        """Pilot Hub → intentional shadow legacy → soak Hub must not critical."""
        if "wa.message.log" not in self.env:
            self.skipTest("wa.message.log missing")
        Log = self.env["wa.message.log"].sudo()
        Log.create(
            {
                "phone": self.channel.wa_phone,
                "direction": "out",
                "message_text": "pilot hub",
                "channel_id": self.channel.id,
                "send_origin": "hub_unified",
                "delivery_status": "sent",
            }
        )
        Log.create(
            {
                "phone": self.channel.wa_phone,
                "direction": "out",
                "message_text": "E1 preflight shadow regression",
                "channel_id": self.channel.id,
                "send_origin": "legacy",
                "delivery_status": "sent",
            }
        )
        Log.create(
            {
                "phone": self.channel.wa_phone,
                "direction": "out",
                "message_text": "soak hub",
                "channel_id": self.channel.id,
                "send_origin": "hub_unified",
                "delivery_status": "sent",
            }
        )
        result = self.Health.service_run_health_check(
            notify=False, create_activities=False
        )
        self.assertFalse(any(i["type"] == "legacy_leakage" for i in result["issues"]))

    def test_duplicate_provider_detection(self):
        self._make_job(self.channel.id, state="sent", evo_id="DUPPROV", body="a")
        self._make_job(self.channel.id, state="sent", evo_id="DUPPROV", body="b")
        result = self.Health.service_run_health_check(
            notify=False, create_activities=False
        )
        self.assertTrue(
            any(i["type"] == "duplicate_provider_id" for i in result["issues"])
        )

    def test_cron_does_not_mutate_routing(self):
        allow_before = self.ICP.get_param("whatsapp_hub.discuss_hub_allowed_channel_ids")
        mode_before = self.channel.wa_outbound_mode
        flags = (
            self.ICP.get_param("whatsapp_hub.unified_outbound_enabled"),
            self.ICP.get_param("whatsapp_hub.discuss_cutover_enabled"),
        )
        with patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text"
        ) as hub_t, patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel.requests.post"
        ) as evo:
            self.Health.cron_run_health_check()
            hub_t.assert_not_called()
            evo.assert_not_called()
        self.assertEqual(
            self.ICP.get_param("whatsapp_hub.discuss_hub_allowed_channel_ids"),
            allow_before,
        )
        self.assertEqual(self.channel.wa_outbound_mode, mode_before)
        self.assertEqual(
            (
                self.ICP.get_param("whatsapp_hub.unified_outbound_enabled"),
                self.ICP.get_param("whatsapp_hub.discuss_cutover_enabled"),
            ),
            flags,
        )

    def test_activity_dedupe(self):
        self.ICP.set_param("whatsapp_hub.discuss_hub_allowed_channel_ids", "999999")
        self.Health.service_run_health_check(notify=True, create_activities=True)
        singleton = self.Health._get_singleton()
        Activity = self.env["mail.activity"].sudo()
        n1 = Activity.search_count(
            [
                ("res_model", "=", "whatsapp.discuss.hub.health"),
                ("res_id", "=", singleton.id),
                ("summary", "ilike", "Discuss Hub Health CRITICAL"),
            ]
        )
        self.assertGreaterEqual(n1, 1)
        self.Health.service_run_health_check(notify=True, create_activities=True)
        n2 = Activity.search_count(
            [
                ("res_model", "=", "whatsapp.discuss.hub.health"),
                ("res_id", "=", singleton.id),
                ("summary", "ilike", "Discuss Hub Health CRITICAL"),
            ]
        )
        self.assertEqual(n1, n2)

    def test_ops_helpers_compute(self):
        self.channel.invalidate_recordset()
        self.assertTrue(self.channel.wa_hub_allowlisted)
        self.assertEqual(self.channel.wa_outbound_mode, "hub")
        self.assertFalse(self.channel.wa_hub_health_warning)
        self.ICP.set_param("whatsapp_hub.discuss_hub_allowed_channel_ids", "1")
        self.channel.invalidate_recordset()
        self.assertFalse(self.channel.wa_hub_allowlisted)
        self.assertIn("hub not allowlisted", self.channel.wa_hub_health_warning or "")
