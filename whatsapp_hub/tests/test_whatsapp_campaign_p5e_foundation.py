# -*- coding: utf-8 -*-
"""P5E: Campaign render freeze + Campaign Hub health foundation tests."""
from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.evolution_whatsapp_chat.models.wa_campaign_line import (
    campaign_line_body_hash,
)
from odoo.addons.whatsapp_hub.models.whatsapp_message import campaign_business_key


@tagged("post_install", "-at_install", "whatsapp_hub", "whatsapp_p5e_campaign")
class TestWhatsappCampaignP5EFoundation(TransactionCase):
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
                "name": "P5E Camp Inst",
                "api_url": "http://127.0.0.1:9",
                "api_key": "p5e-key",
                "instance_name": "p5e_camp_%s"
                % fields.Datetime.now().strftime("%H%M%S%f"),
                "purpose": "other",
                "is_default": True,
                "unified_outbound_enabled": True,
                "campaign_cutover_enabled": True,
            }
        )
        cls.partner = cls.env["res.partner"].sudo().create(
            {"name": "Alice P5E", "phone": "201001112233"}
        )
        cls.ICP.set_param("whatsapp_hub.campaign_cutover_enabled", "False")
        cls.ICP.set_param("whatsapp_hub.campaign_hub_allowed_campaign_ids", "")
        cls.ICP.set_param("whatsapp_hub.unified_outbound_purposes", "discuss")

    def _make_campaign(self, mode="legacy", message="Hello {first}", n=1):
        partners = self.partner
        if n > 1:
            extras = []
            for i in range(n - 1):
                extras.append(
                    self.env["res.partner"]
                    .sudo()
                    .create(
                        {
                            "name": "P5E %d" % i,
                            "phone": "20100111%04d" % (1000 + i),
                        }
                    )
                )
            partners = self.partner | self.env["res.partner"].browse(
                [p.id for p in extras]
            )
        camp = self.Campaign.create(
            {
                "name": "P5E %s" % mode,
                "message": message,
                "personalise": True,
                "target_model": "res.partner",
                "partner_ids": [(6, 0, partners.ids)],
                "send_mode": "immediate",
                "wa_outbound_mode": mode,
                "check_duplicates": False,
                "delay_between": 0,
            }
        )
        camp.action_generate_lines()
        return camp

    def _enable_hub(self, camp):
        self.ICP.set_param("whatsapp_hub.unified_outbound_enabled", "True")
        self.ICP.set_param("whatsapp_hub.campaign_cutover_enabled", "True")
        self.ICP.set_param("whatsapp_hub.unified_outbound_purposes", "discuss,campaign")
        self.ICP.set_param(
            "whatsapp_hub.campaign_hub_allowed_campaign_ids", str(camp.id)
        )
        self.hub_inst.write(
            {"unified_outbound_enabled": True, "campaign_cutover_enabled": True}
        )

    # ── Rendering freeze ─────────────────────────────────────────────────────

    def test_01_02_03_04_freeze_once_idempotent_hash(self):
        camp = self._make_campaign(message="Hi {first}")
        line = camp.campaign_line_ids[:1]
        body1 = line.service_freeze_rendered_body()
        self.assertTrue(line.rendered_locked)
        self.assertEqual(body1, "Hi Alice")
        self.assertEqual(line.rendered_body, "Hi Alice")
        self.assertEqual(line.message, "Hi Alice")
        self.assertEqual(line.rendered_body_hash, campaign_line_body_hash("Hi Alice"))
        at1 = line.rendered_at
        body2 = line.service_freeze_rendered_body()
        self.assertEqual(body2, body1)
        self.assertEqual(line.rendered_at, at1)

    def test_05_template_change_after_freeze(self):
        camp = self._make_campaign(message="Hi {first}")
        line = camp.campaign_line_ids[:1]
        line.service_freeze_rendered_body()
        camp.message = "CHANGED {first}"
        self.assertEqual(line.get_frozen_or_freeze_body(), "Hi Alice")
        self.assertEqual(line.rendered_body, "Hi Alice")

    def test_06_07_08_hub_and_shadow_use_frozen(self):
        camp = self._make_campaign(mode="hub", message="Pilot {first}")
        self._enable_hub(camp)
        line = camp.campaign_line_ids[:1]
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel._send_via_evolution"
        ) as evo, patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text"
        ):
            camp._process_campaign_queue()
            evo.assert_not_called()
        line.invalidate_recordset()
        self.assertTrue(line.rendered_locked)
        self.assertEqual(line.rendered_body, "Pilot Alice")
        msg = self.Message.browse(line.hub_message_id)
        self.assertEqual(msg.body, "Pilot Alice")
        job = self.Out.browse(line.hub_outbound_id)
        self.assertEqual(job.body, "Pilot Alice")
        # Change template; replay must not mutate
        camp.message = "MUTATED {first}"
        camp._process_campaign_queue()
        line.invalidate_recordset()
        msg.invalidate_recordset()
        self.assertEqual(line.rendered_body, "Pilot Alice")
        self.assertEqual(msg.body, "Pilot Alice")

        # Shadow uses same freeze
        camp_s = self._make_campaign(mode="shadow", message="Shadow {first}")
        line_s = camp_s.campaign_line_ids[:1]
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel._send_via_evolution",
            return_value=(True, {"ok": True}, "SH1"),
        ) as evo:
            camp_s.action_start_campaign()
            evo.assert_called()
            args, kwargs = evo.call_args
            # text is 3rd positional or kw
            text = args[2] if len(args) > 2 else kwargs.get("text")
            self.assertEqual(text, "Shadow Alice")
        self.assertEqual(line_s.rendered_body, "Shadow Alice")
        preview = self.Routing.service_preview_campaign_line(camp_s, line_s)
        self.assertEqual(preview["candidate"]["body"], "Shadow Alice")

    def test_09_10_11_hash_match_and_no_rerender(self):
        camp = self._make_campaign(mode="hub", message="Body {first}")
        self._enable_hub(camp)
        camp._process_campaign_queue()
        line = camp.campaign_line_ids[:1]
        msg = self.Message.browse(line.hub_message_id)
        self.assertEqual(
            line.rendered_body_hash, campaign_line_body_hash(msg.body)
        )
        biz = campaign_business_key(camp.id, line.id)
        self.assertEqual(msg.business_key, biz)

    # ── Health ───────────────────────────────────────────────────────────────

    def test_12_healthy_allowlisted(self):
        camp = self._make_campaign(mode="hub")
        self._enable_hub(camp)
        camp._process_campaign_queue()
        result = self.Health.service_run_health_check(
            notify=False, create_activities=False
        )
        # May be healthy or warning depending on compat; must not be critical for allowlist
        types = {i["type"] for i in result["issues"]}
        self.assertNotIn("hub_not_allowlisted", types)
        self.assertNotIn("job_outside_allowlist", types)

    def test_13_hub_not_allowlisted_critical(self):
        camp = self._make_campaign(mode="hub")
        self.ICP.set_param("whatsapp_hub.campaign_cutover_enabled", "True")
        self.ICP.set_param("whatsapp_hub.campaign_hub_allowed_campaign_ids", "")
        result = self.Health.service_run_health_check(
            notify=False, create_activities=False
        )
        self.assertEqual(result["status"], "critical")
        self.assertTrue(
            any(i["type"] == "hub_not_allowlisted" for i in result["issues"])
        )

    def test_14_missing_allowlisted_campaign(self):
        self.ICP.set_param("whatsapp_hub.campaign_hub_allowed_campaign_ids", "999999")
        result = self.Health.service_run_health_check(
            notify=False, create_activities=False
        )
        self.assertTrue(
            any(i["type"] == "allowlist_missing_campaign" for i in result["issues"])
        )

    def test_15_job_outside_allowlist(self):
        camp = self._make_campaign(mode="hub")
        self._enable_hub(camp)
        camp._process_campaign_queue()
        # Remove from allowlist while job pending
        self.ICP.set_param("whatsapp_hub.campaign_hub_allowed_campaign_ids", "1")
        result = self.Health.service_run_health_check(
            notify=False, create_activities=False
        )
        self.assertTrue(
            any(i["type"] == "job_outside_allowlist" for i in result["issues"])
        )

    def test_18_duplicate_provider(self):
        camp = self._make_campaign(mode="hub", n=2)
        self._enable_hub(camp)
        camp._process_campaign_queue()
        lines = camp.campaign_line_ids
        j1 = self.Out.browse(lines[0].hub_outbound_id)
        j2 = self.Out.browse(lines[1].hub_outbound_id)
        j1.write({"state": "sent", "evolution_message_id": "DUP-PROV"})
        j2.write({"state": "sent", "evolution_message_id": "DUP-PROV"})
        result = self.Health.service_run_health_check(
            notify=False, create_activities=False
        )
        self.assertTrue(
            any(i["type"] == "duplicate_provider_id" for i in result["issues"])
        )

    def test_19_lifecycle_divergence(self):
        camp = self._make_campaign(mode="hub")
        self._enable_hub(camp)
        camp._process_campaign_queue()
        line = camp.campaign_line_ids[:1]
        job = self.Out.browse(line.hub_outbound_id)
        # Bypass projection: SQL update so line stays pending while job is sent
        self.env.cr.execute(
            """
            UPDATE whatsapp_outbound_message
               SET state = 'sent',
                   evolution_message_id = 'PROV-DIVERGE'
             WHERE id = %s
            """,
            (job.id,),
        )
        job.invalidate_recordset()
        line.invalidate_recordset()
        self.assertEqual(line.status, "pending")
        self.assertEqual(job.state, "sent")
        result = self.Health.service_run_health_check(
            notify=False, create_activities=False
        )
        self.assertTrue(
            any(i["type"] == "job_sent_line_not_sent" for i in result["issues"])
        )

    def test_21_render_hash_mismatch(self):
        camp = self._make_campaign(mode="hub", message="FreezeMe {first}")
        self._enable_hub(camp)
        camp._process_campaign_queue()
        line = camp.campaign_line_ids[:1]
        msg = self.Message.browse(line.hub_message_id)
        msg.write({"body": "TAMPERED BODY"})
        result = self.Health.service_run_health_check(
            notify=False, create_activities=False
        )
        self.assertTrue(
            any(i["type"] == "render_hash_mismatch" for i in result["issues"])
        )

    def test_26_27_health_no_mutation_no_send(self):
        camp = self._make_campaign(mode="legacy")
        mode = camp.wa_outbound_mode
        allow = self.ICP.get_param("whatsapp_hub.campaign_hub_allowed_campaign_ids")
        with patch(
            "odoo.addons.whatsapp_hub.models.transport_adapter.WhatsappHubTransport.send_text"
        ) as hub, patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel._send_via_evolution"
        ) as evo:
            self.Health.service_run_health_check(notify=False, create_activities=False)
            hub.assert_not_called()
            evo.assert_not_called()
        camp.invalidate_recordset()
        self.assertEqual(camp.wa_outbound_mode, mode)
        self.assertEqual(
            self.ICP.get_param("whatsapp_hub.campaign_hub_allowed_campaign_ids"), allow
        )

    def test_28_activity_dedupe(self):
        camp = self._make_campaign(mode="hub")
        self.ICP.set_param("whatsapp_hub.campaign_cutover_enabled", "True")
        self.ICP.set_param("whatsapp_hub.campaign_hub_allowed_campaign_ids", "")
        self.Health.service_run_health_check(notify=True, create_activities=True)
        singleton = self.Health._get_singleton()
        Activity = self.env["mail.activity"].sudo()
        n1 = Activity.search_count(
            [
                ("res_model", "=", "whatsapp.campaign.hub.health"),
                ("res_id", "=", singleton.id),
                ("summary", "ilike", "Campaign Hub Health CRITICAL"),
            ]
        )
        self.Health.service_run_health_check(notify=True, create_activities=True)
        n2 = Activity.search_count(
            [
                ("res_model", "=", "whatsapp.campaign.hub.health"),
                ("res_id", "=", singleton.id),
                ("summary", "ilike", "Campaign Hub Health CRITICAL"),
            ]
        )
        self.assertEqual(n1, n2)
        self.assertGreaterEqual(n1, 1)

    def test_29_30_31_ops_helpers(self):
        camp = self._make_campaign(mode="hub", message="Ops {first}")
        self._enable_hub(camp)
        camp._process_campaign_queue()
        camp.invalidate_recordset()
        self.assertTrue(camp.wa_hub_allowlisted)
        self.assertTrue(camp.wa_hub_eligible)
        self.assertGreaterEqual(camp.wa_hub_job_count, 1)
        self.assertGreaterEqual(camp.wa_hub_pending_count, 1)
        camp_sched = self._make_campaign(mode="hub")
        camp_sched.send_mode = "scheduled"
        camp_sched.invalidate_recordset()
        self.assertTrue(camp_sched.wa_hub_scheduled_warning)

    def test_35_36_legacy_and_hub_regression_smoke(self):
        camp = self._make_campaign(mode="legacy")
        with patch(
            "odoo.addons.evolution_whatsapp_chat.models.discuss_channel._send_via_evolution",
            return_value=(True, {"ok": True}, "LEG"),
        ) as evo:
            camp.action_start_campaign()
            evo.assert_called()
        # Restore purposes after tests that enabled campaign
        self.ICP.set_param("whatsapp_hub.unified_outbound_purposes", "discuss")
        self.ICP.set_param("whatsapp_hub.campaign_cutover_enabled", "False")
        self.ICP.set_param("whatsapp_hub.campaign_hub_allowed_campaign_ids", "")
