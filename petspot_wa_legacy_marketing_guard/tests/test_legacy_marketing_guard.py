# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "petspot_legacy_wa_guard")
class TestLegacyWaMarketingGuard(TransactionCase):

    def test_01_start_campaign_blocked(self):
        camp = self.env["wa.campaign"].create(
            {
                "name": "UAT Guard Block Start",
                "message": "hello",
                "state": "draft",
            }
        )
        with self.assertRaises(UserError) as err:
            camp.action_start_campaign()
        self.assertIn("petspot_wa_marketing_queue", str(err.exception))

    def test_02_bulk_wizard_blocked(self):
        wiz = self.env["whatsapp.bulk.wizard"].create({"message": "bulk hello"})
        with self.assertRaises(UserError) as err:
            wiz.action_send_bulk()
        self.assertIn("petspot_wa_marketing_queue", str(err.exception))

    def test_03_historical_campaign_readable(self):
        camp = self.env["wa.campaign"].search([], limit=1)
        if not camp:
            camp = self.env["wa.campaign"].create(
                {"name": "UAT Guard Read", "message": "x", "state": "cancelled"}
            )
        # read must not raise
        self.assertTrue(camp.name)
        self.assertTrue(camp.read(["name", "state"]))

    def test_04_process_queue_blocked(self):
        camp = self.env["wa.campaign"].create(
            {"name": "UAT Guard Process", "message": "x", "state": "draft"}
        )
        with self.assertRaises(UserError):
            camp._process_campaign_queue()

    def test_05_marketing_queue_settings_untouched(self):
        settings = self.env["petspot.wa.marketing.settings"].browse(1)
        self.assertTrue(settings.exists())
        # Guard module must not flip pause/mock
        self.assertTrue(settings.global_pause)
        self.assertTrue(settings.mock_send)
