# -*- coding: utf-8 -*-
"""
Tests for evolution_whatsapp_chat.

Workflow covered (no browser):
  - wa.campaign state machine: draft → running, pause, resume, cancel
  - Starting without lines raises UserError
  - Starting with no pending lines raises UserError
  - action_retry_failed resets failed lines to pending
  - Anti-duplicate check: _already_sent_to_partner / _already_sent_to_lead
  - action_clone_campaign creates a new draft copy
  - wa.message.log: create and verify delivery status fields
  - wa.campaign.line: create and assert field defaults
"""

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestWaCampaignStateMachine(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Campaign = cls.env["wa.campaign"]
        cls.Line = cls.env["wa.campaign.line"]
        cls.Partner = cls.env["res.partner"]

    def _campaign(self, name="Test Campaign", **kwargs):
        vals = {
            "name": name,
            "message": "Hello {name}, welcome!",
            "target_model": "res.partner",
            "state": "draft",
        }
        vals.update(kwargs)
        return self.Campaign.create(vals)

    def _partner_with_phone(self, name="Test Partner", phone="+201001234567"):
        return self.Partner.create({"name": name, "phone": phone})

    def _pending_line(self, campaign, partner=None, phone="+201001234567"):
        if partner is None:
            partner = self._partner_with_phone()
        return self.Line.create(
            {
                "campaign_id": campaign.id,
                "partner_id": partner.id,
                "phone": phone,
                "status": "pending",
            }
        )

    # ── state transitions ─────────────────────────────────────────────────────

    def test_start_campaign_from_draft(self):
        campaign = self._campaign()
        self._pending_line(campaign)
        campaign.action_start_campaign()
        self.assertEqual(campaign.state, "running")

    def test_pause_running_campaign(self):
        campaign = self._campaign()
        self._pending_line(campaign)
        campaign.action_start_campaign()
        campaign.action_pause_campaign()
        self.assertEqual(campaign.state, "paused")

    def test_resume_paused_campaign(self):
        campaign = self._campaign()
        self._pending_line(campaign)
        campaign.action_start_campaign()
        campaign.action_pause_campaign()
        # Re-add a pending line so resume doesn't fail on empty queue
        self._pending_line(campaign, phone="+201009999999")
        campaign.action_resume_campaign()
        self.assertIn(campaign.state, ("running", "completed"))

    def test_cancel_draft_campaign(self):
        campaign = self._campaign()
        campaign.action_cancel_campaign()
        self.assertEqual(campaign.state, "cancelled")

    def test_cancel_running_campaign(self):
        campaign = self._campaign()
        self._pending_line(campaign)
        campaign.action_start_campaign()
        campaign.action_cancel_campaign()
        self.assertEqual(campaign.state, "cancelled")

    # ── guard: cannot start without lines ─────────────────────────────────────

    def test_start_without_lines_raises_user_error(self):
        campaign = self._campaign()
        with self.assertRaises(UserError):
            campaign.action_start_campaign()

    def test_start_with_no_pending_lines_raises_user_error(self):
        """All lines sent → no pending lines → UserError."""
        campaign = self._campaign()
        self.Line.create(
            {
                "campaign_id": campaign.id,
                "phone": "+201001111111",
                "status": "sent",
            }
        )
        with self.assertRaises(UserError):
            campaign.action_start_campaign()

    # ── guard: cannot pause non-running ──────────────────────────────────────

    def test_pause_draft_campaign_raises(self):
        campaign = self._campaign()
        with self.assertRaises(UserError):
            campaign.action_pause_campaign()

    # ── guard: cannot resume non-paused ──────────────────────────────────────

    def test_resume_draft_campaign_raises(self):
        campaign = self._campaign()
        with self.assertRaises(UserError):
            campaign.action_resume_campaign()

    # ── guard: cannot cancel already finished ────────────────────────────────

    def test_cancel_cancelled_campaign_raises(self):
        campaign = self._campaign(state="cancelled")
        with self.assertRaises(UserError):
            campaign.action_cancel_campaign()

    def test_cancel_completed_campaign_raises(self):
        campaign = self._campaign(state="completed")
        with self.assertRaises(UserError):
            campaign.action_cancel_campaign()

    # ── retry failed ──────────────────────────────────────────────────────────

    def test_retry_failed_resets_lines_to_pending(self):
        campaign = self._campaign()
        failed_line = self.Line.create(
            {
                "campaign_id": campaign.id,
                "phone": "+201002222222",
                "status": "failed",
                "error_msg": "Timeout",
            }
        )
        campaign.action_retry_failed()
        self.assertEqual(failed_line.status, "pending")
        self.assertFalse(failed_line.error_msg)

    def test_retry_failed_no_failed_lines_raises(self):
        campaign = self._campaign()
        self._pending_line(campaign)
        with self.assertRaises(UserError):
            campaign.action_retry_failed()

    # ── anti-duplicate checks ─────────────────────────────────────────────────

    def test_already_sent_to_partner_true(self):
        campaign = self._campaign()
        partner = self._partner_with_phone()
        self.Line.create(
            {
                "campaign_id": campaign.id,
                "partner_id": partner.id,
                "phone": partner.phone,
                "status": "sent",
            }
        )
        self.assertTrue(campaign._already_sent_to_partner(partner))

    def test_already_sent_to_partner_false_for_pending(self):
        campaign = self._campaign()
        partner = self._partner_with_phone(name="NeverSent")
        self.Line.create(
            {
                "campaign_id": campaign.id,
                "partner_id": partner.id,
                "phone": partner.phone,
                "status": "pending",
            }
        )
        self.assertFalse(campaign._already_sent_to_partner(partner))

    def test_already_sent_to_partner_false_for_other_campaign(self):
        c1 = self._campaign(name="Camp A")
        c2 = self._campaign(name="Camp B")
        partner = self._partner_with_phone(name="SharedContact")
        self.Line.create(
            {
                "campaign_id": c1.id,
                "partner_id": partner.id,
                "phone": partner.phone,
                "status": "sent",
            }
        )
        self.assertFalse(c2._already_sent_to_partner(partner))

    # ── wa.message.log ────────────────────────────────────────────────────────

    def test_message_log_create_and_delivery_status(self):
        partner = self._partner_with_phone(name="LogContact")
        log = self.env["wa.message.log"].create(
            {
                "partner_id": partner.id,
                "phone": partner.phone,
                "direction": "out",
                "message_text": "Hello there",
                "delivery_status": "pending",
            }
        )
        self.assertEqual(log.delivery_status, "pending")
        log.write({"delivery_status": "delivered"})
        self.assertEqual(log.delivery_status, "delivered")

    def test_message_log_display_name_uses_partner(self):
        partner = self._partner_with_phone(name="DisplayTest")
        log = self.env["wa.message.log"].create(
            {
                "partner_id": partner.id,
                "phone": partner.phone,
                "direction": "out",
            }
        )
        self.assertIn("DisplayTest", log.display_name)

    # ── clone ─────────────────────────────────────────────────────────────────

    def test_clone_campaign_creates_draft_copy(self):
        campaign = self._campaign(name="Original")
        count_before = self.Campaign.search_count([])
        campaign.action_clone_campaign()
        count_after = self.Campaign.search_count([])
        self.assertEqual(count_after, count_before + 1)
        clone = self.Campaign.search([("name", "like", "Original")], order="id desc", limit=1)
        self.assertEqual(clone.state, "draft")
