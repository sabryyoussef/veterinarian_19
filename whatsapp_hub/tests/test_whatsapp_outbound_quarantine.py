# -*- coding: utf-8 -*-
"""E1: quarantine incomplete unified_bridge Discuss outbound jobs."""
from odoo import fields
from odoo.tests import TransactionCase, tagged, new_test_user


@tagged("post_install", "-at_install", "whatsapp_hub", "whatsapp_e1_quarantine")
class TestWhatsappOutboundQuarantine(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env,
            login="wa_hub_e1_quarantine",
            groups="whatsapp_hub.group_whatsapp_manager",
        )
        cls.Out = cls.env["whatsapp.outbound.message"]
        cls.hub_inst = cls.env["whatsapp.instance"].create(
            {
                "name": "E1 Quarantine Inst",
                "api_url": "http://127.0.0.1:9",
                "api_key": "secret-e1-q",
                "instance_name": "e1-q-inst",
                "purpose": "other",
            }
        )

    def _make_job(self, channel_id, state="pending", evo_id=False, next_retry=False, body="q"):
        stamp = fields.Datetime.now().strftime("%Y%m%d%H%M%S%f")
        biz = f"discuss:{channel_id}:e1q-{stamp}-{body}"
        return self.Out.sudo().create(
            {
                "name": f"E1Q job {body}",
                "state": state,
                "transport_mode": "unified_bridge",
                "destination": "201000000010",
                "body": body,
                "message_type": "text",
                "purpose": "discuss",
                "source_app": "discuss",
                "business_key": biz,
                "client_request_id": biz,
                "instance_id": self.hub_inst.id,
                "discuss_channel_id": channel_id,
                "evolution_message_id": evo_id or False,
                "next_retry_at": next_retry or False,
                "retry_count": 1 if next_retry else 0,
            }
        )

    def test_quarantine_pending_cancelled(self):
        ch = 910010
        job = self._make_job(ch, state="pending", body="pending")
        result = self.Out.with_user(self.manager).service_quarantine_discuss_channel(
            ch, reason="e1 test pending"
        )
        self.assertEqual(result["cancelled"], 1)
        self.assertIn(job.id, result["job_ids"]["cancelled"])
        job.invalidate_recordset()
        self.assertEqual(job.state, "cancelled")
        self.assertFalse(job.next_retry_at)

    def test_quarantine_retry_scheduled_cleared(self):
        ch = 910011
        retry_at = fields.Datetime.now()
        job = self._make_job(ch, state="pending", next_retry=retry_at, body="retry")
        result = self.Out.with_user(self.manager).service_quarantine_discuss_channel(
            ch, reason="e1 test retry"
        )
        self.assertEqual(result["cancelled"], 1)
        job.invalidate_recordset()
        self.assertEqual(job.state, "cancelled")
        self.assertFalse(job.next_retry_at)

    def test_quarantine_sent_untouched(self):
        ch = 910012
        job = self._make_job(ch, state="sent", evo_id="EVO-SENT-1", body="sent")
        result = self.Out.with_user(self.manager).service_quarantine_discuss_channel(
            ch, reason="e1 test sent"
        )
        self.assertEqual(result["already_sent"], 1)
        self.assertEqual(result["jobs_found"], 1)
        job.invalidate_recordset()
        self.assertEqual(job.state, "sent")
        self.assertEqual(job.evolution_message_id, "EVO-SENT-1")

    def test_quarantine_idempotent(self):
        ch = 910013
        job = self._make_job(ch, state="pending", body="idem")
        r1 = self.Out.with_user(self.manager).service_quarantine_discuss_channel(
            ch, reason="first"
        )
        r2 = self.Out.with_user(self.manager).service_quarantine_discuss_channel(
            ch, reason="second"
        )
        self.assertEqual(r1["cancelled"], 1)
        self.assertEqual(r2["already_cancelled"], 1)
        self.assertIn(job.id, r2["job_ids"]["already_cancelled"])

    def test_quarantine_isolates_channels(self):
        j10 = self._make_job(910014, state="pending", body="ch10")
        j5 = self._make_job(910015, state="pending", body="ch5")
        result = self.Out.with_user(self.manager).service_quarantine_discuss_channel(
            910014, reason="only 910014"
        )
        self.assertEqual(result["cancelled"], 1)
        self.assertIn(j10.id, result["job_ids"]["cancelled"])
        j10.invalidate_recordset()
        j5.invalidate_recordset()
        self.assertEqual(j10.state, "cancelled")
        self.assertEqual(j5.state, "pending")

    def test_quarantine_processing_without_provider_uncertain(self):
        ch = 910016
        job = self._make_job(ch, state="processing", body="uncertain")
        result = self.Out.with_user(self.manager).service_quarantine_discuss_channel(
            ch, reason="uncertain mid-flight"
        )
        self.assertEqual(result["uncertain"], 1)
        job.invalidate_recordset()
        self.assertEqual(job.state, "cancelled")
        self.assertFalse(job.next_retry_at)

    def test_quarantine_processing_with_provider_treated_sent(self):
        ch = 910017
        job = self._make_job(
            ch, state="processing", evo_id="EVO-PROC-1", body="proc-sent"
        )
        result = self.Out.with_user(self.manager).service_quarantine_discuss_channel(
            ch, reason="provider accepted"
        )
        self.assertEqual(result["already_sent"], 1)
        job.invalidate_recordset()
        self.assertEqual(job.state, "sent")
        self.assertEqual(job.evolution_message_id, "EVO-PROC-1")
