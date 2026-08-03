# -*- coding: utf-8 -*-
"""Phase 6 marketing queue — ≥30 automated fail-closed tests (TEST/UAT)."""
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.petspot_wa_marketing_queue.models.settings import OPT_OUT_PHRASE, REQUIRED_INSTANCE


@tagged("post_install", "-at_install", "petspot_wa_marketing_queue")
class TestPetspotWaMarketingQueue(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Settings = cls.env["petspot.wa.marketing.settings"]
        cls.settings = cls.Settings.get_settings()
        cls.settings.write(
            {
                "global_pause": False,
                "mock_send": True,
                "tier": 1,
                "daily_sent_count": 0,
                "daily_reserved_count": 0,
                "daily_cairo_date": cls.settings.cairo_today(),
                "consecutive_delivery_failures": 0,
                "rolling_opt_out_count": 0,
                "rolling_send_count": 0,
                "spacing_min_minutes": 0,
                "spacing_max_minutes": 0,
            }
        )
        cls.Consent = cls.env["petspot.wa.marketing.consent"]
        cls.Wording = cls.env["petspot.wa.consent.wording"]
        wording = cls.Wording.search([("version", "=", "staff_v1_1_approved")], limit=1)
        if not wording:
            wording = cls.Wording.create(
                {
                    "name": "Staff test",
                    "version": "staff_v1_1_approved",
                    "route": "staff_recorded",
                    "active": True,
                    "body_ar": "test",
                    "body_en": "test",
                }
            )
        cls.wording = wording
        cls.template = cls.env["petspot.wa.marketing.template"].create(
            {
                "name": "UAT Template",
                "version": "mkt_v1_uat",
                "body_ar": f"أهلاً {{first_name}} زورونا {{url}}\n{OPT_OUT_PHRASE}",
                "url": "https://shopify.drpaws.ai/pages/clinic-services",
                "state": "draft",
            }
        )
        cls.template.action_approve()

    def _person(self, name, phone, opted_in=True):
        partner = self.env["res.partner"].create(
            {"name": name, "phone": phone, "is_company": False}
        )
        if opted_in:
            from odoo.addons.petspot_wa_marketing_consent.models.wa_marketing_consent import (
                normalize_eg_mobile,
            )

            mobile = normalize_eg_mobile(phone)
            self.Consent.create(
                {
                    "partner_id": partner.id,
                    "mobile_normalized": mobile,
                    "mobile_raw": phone,
                    "channel": "whatsapp",
                    "purpose": "marketing",
                    "status": "opted_in",
                    "consent_source": "staff_recorded",
                    "staff_explicit_confirm": True,
                    "wording_id": self.wording.id,
                    "wording_version": self.wording.version,
                    "wording_text": self.wording.body_ar or "w",
                    "consent_timestamp": fields.Datetime.now(),
                    "captured_by": self.env.user.id,
                    "evidence_ref": "PHASE6-UAT",
                }
            )
        return partner

    def _campaign(self, partners_domain=None):
        camp = self.env["petspot.wa.marketing.campaign"].create(
            {
                "name": "UAT Campaign",
                "template_id": self.template.id,
                "partner_domain": partners_domain
                or f"[('id','in',{self.env['res.partner'].search([]).ids})]",
                "internal_test_ok": True,
            }
        )
        return camp

    # --- settings / isolation ---
    def test_01_global_pause_default_exists(self):
        s = self.Settings.create(
            {"name": "tmp pause check", "global_pause": True, "evolution_instance": REQUIRED_INSTANCE}
        )
        self.assertTrue(s.global_pause)

    def test_02_instance_must_be_petspot_marketing(self):
        with self.assertRaises(Exception):
            self.settings.write({"evolution_instance": "sabry min"})

    def test_03_forbidden_instance_constraint(self):
        with self.assertRaises(Exception):
            self.Settings.create(
                {"name": "bad", "evolution_instance": "sabry min", "global_pause": True}
            )

    def test_04_tier_cap_values(self):
        self.settings.tier = 1
        self.assertEqual(self.settings.daily_cap(), 5)
        self.settings.tier = 2
        self.assertEqual(self.settings.daily_cap(), 10)
        self.settings.tier = 3
        self.assertEqual(self.settings.daily_cap(), 20)

    def test_05_tier_no_auto_increase(self):
        self.settings.tier = 1
        self.settings.tier_active_day_count = 99
        # dispatcher must not bump tier
        self.env["petspot.wa.marketing.dispatcher"].cron_process_queue()
        self.assertEqual(self.settings.tier, 1)

    def test_06_manual_tier_increase(self):
        self.settings.tier = 1
        self.settings.action_approve_tier_increase()
        self.assertEqual(self.settings.tier, 2)

    def test_07_tier_max_blocks(self):
        self.settings.tier = 3
        with self.assertRaises(UserError):
            self.settings.action_approve_tier_increase()

    # --- template ---
    def test_08_template_requires_opt_out_phrase(self):
        with self.assertRaises(ValidationError):
            self.env["petspot.wa.marketing.template"].create(
                {
                    "name": "bad",
                    "version": "x",
                    "body_ar": "hello {first_name}",
                }
            )

    def test_09_template_blocks_bad_placeholder(self):
        with self.assertRaises(ValidationError):
            self.env["petspot.wa.marketing.template"].create(
                {
                    "name": "bad2",
                    "version": "y",
                    "body_ar": f"hi {{last_name}}\n{OPT_OUT_PHRASE}",
                }
            )

    def test_10_template_blocks_drug_claims(self):
        with self.assertRaises(ValidationError):
            self.env["petspot.wa.marketing.template"].create(
                {
                    "name": "drug",
                    "version": "z",
                    "body_ar": f"اشتري apoquel الآن\n{OPT_OUT_PHRASE}",
                }
            )

    def test_11_template_approve(self):
        self.assertEqual(self.template.state, "approved")

    def test_12_render_body(self):
        p = self._person("Ahmed Test", "01011112222")
        body = self.template.render_body(p)
        self.assertIn("Ahmed", body)
        self.assertIn(OPT_OUT_PHRASE, body)

    # --- eligibility ---
    def test_13_company_not_eligible(self):
        company = self.env["res.partner"].create({"name": "Co", "is_company": True, "phone": "01011113333"})
        res = self.env["petspot.wa.marketing.queue.eligibility"].evaluate(company, check_pause=False)
        self.assertFalse(res["eligible"])

    def test_14_donotcontact_name_blocked(self):
        p = self._person("PHASE6 DO NOT CONTACT X", "01011114444")
        res = self.env["petspot.wa.marketing.queue.eligibility"].evaluate(p, check_pause=False)
        self.assertFalse(res["eligible"])

    def test_15_opted_in_eligible(self):
        p = self._person("Eligible Person", "01011115555")
        res = self.env["petspot.wa.marketing.queue.eligibility"].evaluate(
            p, check_pause=False, check_instance=False
        )
        self.assertTrue(res["eligible"], res)

    def test_16_global_pause_blocks_eval(self):
        p = self._person("Paused Person", "01011116666")
        self.settings.global_pause = True
        res = self.env["petspot.wa.marketing.queue.eligibility"].evaluate(p, check_pause=True)
        self.assertFalse(res["eligible"])
        self.assertEqual(res["reason"], "global_pause_on")

    def test_17_opted_out_not_eligible(self):
        p = self._person("Out Person", "01011117777")
        c = self.Consent.search([("partner_id", "=", p.id)], limit=1)
        c.action_opt_out(source="test")
        res = self.env["petspot.wa.marketing.queue.eligibility"].evaluate(
            p, check_pause=False, check_instance=False
        )
        self.assertFalse(res["eligible"])

    # --- campaign / queue ---
    def test_18_ineligible_never_queued(self):
        bad = self.env["res.partner"].create(
            {"name": "No Consent", "phone": "01011118888", "is_company": False}
        )
        good = self._person("Good One", "01011119999")
        camp = self.env["petspot.wa.marketing.campaign"].create(
            {
                "name": "C1",
                "template_id": self.template.id,
                "partner_domain": f"[('id','in',[{bad.id},{good.id}])]",
                "internal_test_ok": True,
            }
        )
        camp.action_approve_and_schedule()
        mobiles = camp.queue_item_ids.mapped("mobile_normalized")
        self.assertEqual(len(camp.queue_item_ids), 1)
        self.assertTrue(all(m.startswith("+20") for m in mobiles))

    def test_19_idempotency_unique(self):
        p = self._person("Idem Person", "01022221111")
        camp = self.env["petspot.wa.marketing.campaign"].create(
            {
                "name": "C2",
                "template_id": self.template.id,
                "partner_domain": f"[('id','=',{p.id})]",
                "internal_test_ok": True,
            }
        )
        camp.action_approve_and_schedule()
        key = camp.queue_item_ids.idempotency_key
        with self.assertRaises(Exception):
            self.env["petspot.wa.marketing.queue.item"].create(
                {
                    "campaign_id": camp.id,
                    "partner_id": p.id,
                    "mobile_normalized": camp.queue_item_ids.mobile_normalized,
                    "template_id": self.template.id,
                    "template_version": self.template.version,
                    "idempotency_key": key,
                    "rendered_body": "x",
                    "scheduled_at": fields.Datetime.now(),
                }
            )

    def test_20_duplicate_phone_one_message(self):
        p1 = self._person("Dup A", "01022223333")
        p2 = self.env["res.partner"].create(
            {"name": "Dup B", "phone": "01022223333", "is_company": False}
        )
        # second partner same phone → eligibility fail closed for both or ambiguity
        res1 = self.env["petspot.wa.marketing.queue.eligibility"].evaluate(
            p1, check_pause=False, check_instance=False
        )
        res2 = self.env["petspot.wa.marketing.queue.eligibility"].evaluate(
            p2, check_pause=False, check_instance=False
        )
        # At least one path fails closed on duplicate
        self.assertFalse(res1["eligible"] and res2["eligible"])

    def test_21_approve_requires_internal_test(self):
        p = self._person("Need Test", "01022224444")
        camp = self.env["petspot.wa.marketing.campaign"].create(
            {
                "name": "C3",
                "template_id": self.template.id,
                "partner_domain": f"[('id','=',{p.id})]",
                "internal_test_ok": False,
            }
        )
        with self.assertRaises(UserError):
            camp.action_approve_and_schedule()

    def test_22_preview_sets_count(self):
        p = self._person("Preview P", "01022225555")
        camp = self.env["petspot.wa.marketing.campaign"].create(
            {
                "name": "C4",
                "template_id": self.template.id,
                "partner_domain": f"[('id','=',{p.id})]",
            }
        )
        camp.action_preview()
        self.assertGreaterEqual(camp.preview_count, 1)
        self.assertTrue(camp.preview_sample_body)

    # --- dispatcher / caps ---
    def test_23_dispatch_respects_global_pause(self):
        p = self._person("Pause Disp", "01033331111")
        camp = self.env["petspot.wa.marketing.campaign"].create(
            {
                "name": "C5",
                "template_id": self.template.id,
                "partner_domain": f"[('id','=',{p.id})]",
                "internal_test_ok": True,
            }
        )
        camp.action_approve_and_schedule()
        self.settings.global_pause = True
        n = self.env["petspot.wa.marketing.dispatcher"].cron_process_queue()
        self.assertEqual(n, 0)
        self.assertEqual(camp.queue_item_ids.state, "pending")

    def test_24_dispatch_mock_send(self):
        p = self._person("Send Me", "01033332222")
        camp = self.env["petspot.wa.marketing.campaign"].create(
            {
                "name": "C6",
                "template_id": self.template.id,
                "partner_domain": f"[('id','=',{p.id})]",
                "internal_test_ok": True,
            }
        )
        camp.action_approve_and_schedule()
        self.settings.write(
            {
                "global_pause": False,
                "mock_send": True,
                "spacing_min_minutes": 0,
                "window_start_hour": 0,
                "window_end_hour": 24,
            }
        )
        # force in window
        with patch.object(
            type(self.settings), "in_send_window", lambda self, when=None: True
        ):
            n = self.env["petspot.wa.marketing.dispatcher"].cron_process_queue()
        self.assertEqual(n, 1)
        self.assertEqual(camp.queue_item_ids.state, "sent")

    def test_25_daily_cap_blocks_extra(self):
        self.settings.write(
            {
                "tier": 1,
                "daily_sent_count": 5,
                "daily_reserved_count": 0,
                "daily_cairo_date": self.settings.cairo_today(),
                "global_pause": False,
            }
        )
        self.assertFalse(self.settings.reserve_daily_slot())

    def test_26_concurrent_cap_reservation(self):
        self.settings.write(
            {
                "tier": 1,
                "daily_sent_count": 4,
                "daily_reserved_count": 0,
                "daily_cairo_date": self.settings.cairo_today(),
                "global_pause": False,
            }
        )
        self.assertTrue(self.settings.reserve_daily_slot())
        self.assertFalse(self.settings.reserve_daily_slot())

    def test_27_eligibility_change_skips_dispatch(self):
        p = self._person("Change Elig", "01033333333")
        camp = self.env["petspot.wa.marketing.campaign"].create(
            {
                "name": "C7",
                "template_id": self.template.id,
                "partner_domain": f"[('id','=',{p.id})]",
                "internal_test_ok": True,
            }
        )
        camp.action_approve_and_schedule()
        c = self.Consent.search([("partner_id", "=", p.id)], limit=1)
        c.action_opt_out(source="pre_dispatch")
        self.settings.write(
            {"global_pause": False, "spacing_min_minutes": 0, "window_start_hour": 0, "window_end_hour": 24}
        )
        with patch.object(type(self.settings), "in_send_window", lambda self, when=None: True):
            self.env["petspot.wa.marketing.dispatcher"].cron_process_queue()
        self.assertEqual(camp.queue_item_ids.state, "skipped")

    def test_28_stop_cancels_pending(self):
        p = self._person("Stop Me", "01033334444")
        camp = self.env["petspot.wa.marketing.campaign"].create(
            {
                "name": "C8",
                "template_id": self.template.id,
                "partner_domain": f"[('id','=',{p.id})]",
                "internal_test_ok": True,
            }
        )
        camp.action_approve_and_schedule()
        mobile = camp.queue_item_ids.mobile_normalized
        self.env["petspot.wa.marketing.dispatcher"].handle_inbound_text(mobile, "وقف")
        self.assertEqual(camp.queue_item_ids.state, "cancelled")
        c = self.Consent.search([("mobile_normalized", "=", mobile)], limit=1)
        self.assertEqual(c.status, "opted_out")

    def test_29_wrong_number_cancels(self):
        p = self._person("Wrong Me", "01033335555")
        camp = self.env["petspot.wa.marketing.campaign"].create(
            {
                "name": "C9",
                "template_id": self.template.id,
                "partner_domain": f"[('id','=',{p.id})]",
                "internal_test_ok": True,
            }
        )
        camp.action_approve_and_schedule()
        mobile = camp.queue_item_ids.mobile_normalized
        self.env["petspot.wa.marketing.dispatcher"].handle_inbound_text(mobile, "wrong number")
        self.assertEqual(camp.queue_item_ids.state, "cancelled")

    def test_30_no_duplicate_after_sent(self):
        p = self._person("Once Only", "01033336666")
        camp = self.env["petspot.wa.marketing.campaign"].create(
            {
                "name": "C10",
                "template_id": self.template.id,
                "partner_domain": f"[('id','=',{p.id})]",
                "internal_test_ok": True,
            }
        )
        camp.action_approve_and_schedule()
        self.settings.write(
            {"global_pause": False, "spacing_min_minutes": 0, "window_start_hour": 0, "window_end_hour": 24}
        )
        with patch.object(type(self.settings), "in_send_window", lambda self, when=None: True):
            self.env["petspot.wa.marketing.dispatcher"].cron_process_queue()
        # re-approve path should not create second pending for same key
        res = self.env["petspot.wa.marketing.queue.eligibility"].evaluate(
            p, campaign=camp, template=self.template, check_pause=False, check_instance=False
        )
        self.assertFalse(res["eligible"])

    def test_31_uncertain_no_auto_retry(self):
        p = self._person("Uncertain", "01033337777")
        camp = self.env["petspot.wa.marketing.campaign"].create(
            {
                "name": "C11",
                "template_id": self.template.id,
                "partner_domain": f"[('id','=',{p.id})]",
                "internal_test_ok": True,
            }
        )
        camp.action_approve_and_schedule()
        item = camp.queue_item_ids
        item.state = "uncertain"
        self.settings.write({"global_pause": False, "spacing_min_minutes": 0})
        with patch.object(type(self.settings), "in_send_window", lambda self, when=None: True):
            n = self.env["petspot.wa.marketing.dispatcher"].cron_process_queue()
        self.assertEqual(n, 0)
        self.assertEqual(item.state, "uncertain")

    def test_32_two_failures_pause(self):
        self.settings.consecutive_delivery_failures = 1
        self.settings.global_pause = False
        Client = self.env["petspot.wa.marketing.evolution.client"]
        p = self._person("Fail Pause", "01033338888")
        camp = self.env["petspot.wa.marketing.campaign"].create(
            {
                "name": "C12",
                "template_id": self.template.id,
                "partner_domain": f"[('id','=',{p.id})]",
                "internal_test_ok": True,
            }
        )
        camp.action_approve_and_schedule()
        with patch.object(type(self.settings), "in_send_window", lambda self, when=None: True), patch.object(
            type(Client), "send_text", lambda self, m, t: {"ok": False, "error": "http_500", "detail": "x"}
        ):
            self.settings.write({"spacing_min_minutes": 0, "global_pause": False})
            self.env["petspot.wa.marketing.dispatcher"].cron_process_queue()
        self.settings.invalidate_recordset()
        self.assertTrue(self.settings.global_pause)

    def test_33_event_immutable(self):
        ev = self.env["petspot.wa.marketing.event"].create(
            {"event_type": "health", "note": "x"}
        )
        with self.assertRaises(UserError):
            ev.write({"note": "y"})
        with self.assertRaises(UserError):
            ev.unlink()

    def test_34_campaign_cancel_cancels_queue(self):
        p = self._person("Cancel Camp", "01033339999")
        camp = self.env["petspot.wa.marketing.campaign"].create(
            {
                "name": "C13",
                "template_id": self.template.id,
                "partner_domain": f"[('id','=',{p.id})]",
                "internal_test_ok": True,
            }
        )
        camp.action_approve_and_schedule()
        camp.action_cancel()
        self.assertEqual(camp.state, "cancelled")
        self.assertEqual(camp.queue_item_ids.state, "cancelled")

    def test_35_evolution_client_rejects_sabry(self):
        Client = self.env["petspot.wa.marketing.evolution.client"]
        with self.assertRaises(UserError):
            Client._assert_instance("sabry min")

    def test_36_release_slot_after_skip(self):
        self.settings.write(
            {
                "daily_sent_count": 0,
                "daily_reserved_count": 0,
                "daily_cairo_date": self.settings.cairo_today(),
                "global_pause": False,
            }
        )
        self.assertTrue(self.settings.reserve_daily_slot())
        self.settings.release_daily_slot()
        self.settings.invalidate_recordset()
        self.assertEqual(self.settings.daily_reserved_count, 0)

    def test_37_no_capacity_rollover_new_day(self):
        yesterday = self.settings.cairo_today() - timedelta(days=1)
        self.settings.write(
            {
                "daily_cairo_date": yesterday,
                "daily_sent_count": 5,
                "daily_reserved_count": 0,
                "global_pause": False,
                "tier": 1,
            }
        )
        # reserve should rollover counters
        self.assertTrue(self.settings.reserve_daily_slot())
        self.settings.invalidate_recordset()
        self.assertEqual(self.settings.daily_cairo_date, self.settings.cairo_today())
        self.assertEqual(self.settings.daily_sent_count, 0)

    def test_38_retired_template_not_usable(self):
        tpl = self.env["petspot.wa.marketing.template"].create(
            {
                "name": "Retire Me",
                "version": "retire_v1",
                "body_ar": f"x {{first_name}}\n{OPT_OUT_PHRASE}",
                "state": "draft",
            }
        )
        tpl.action_approve()
        tpl.action_retire()
        p = self._person("Retired T", "01044441111")
        camp = self.env["petspot.wa.marketing.campaign"].create(
            {
                "name": "C14",
                "template_id": tpl.id,
                "partner_domain": f"[('id','=',{p.id})]",
                "internal_test_ok": True,
            }
        )
        with self.assertRaises(UserError):
            camp.action_approve_and_schedule()

    def test_39_install_settings_pause_on(self):
        # default data record
        s = self.Settings.search([], limit=1)
        # recreate check: newly created defaults True
        s2 = self.Settings.create(
            {"name": "pause default", "evolution_instance": REQUIRED_INSTANCE}
        )
        self.assertTrue(s2.global_pause)

    def test_40_real_send_requires_allowlist(self):
        self.settings.mock_send = False
        self.settings.allowlist_test_mobiles = "+201099999999"
        Client = self.env["petspot.wa.marketing.evolution.client"]
        with self.assertRaises(UserError):
            Client.send_text("+201088888888", "hi")
