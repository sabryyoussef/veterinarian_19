# -*- coding: utf-8 -*-
"""Sahel tagged audience policy UAT — tags only; never consent; TEST/UAT."""
import ast
import json
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.petspot_wa_marketing_queue.models.audience import (
    SAHEL_REQUIRED_TAG_NAMES,
    SAHEL_TAGGED_CODE,
)
from odoo.addons.petspot_wa_marketing_queue.models.settings import OPT_OUT_PHRASE, REQUIRED_INSTANCE

PRESENCE_BODY = (
    "أهلاً {first_name} 👋\n\n"
    "Pet Spot Clinic موجودين معاكم في الساحل الشمالي، في الطريق الرئيسي بجوار بوابة أمواج 1 وSimonds Amwaj، "
    "سيدي عبدالرحمن.\n\n"
    "للحجز أو الاستفسار: 01201568888\n\n"
    "تعرّف على خدمات العيادة ومنتجات الموسم المتاحة على موقعنا:\n"
    "https://shopify.drpaws.ai/?utm_source=whatsapp&utm_medium=petspot_marketing&utm_campaign=sahel_presence_tagged\n\n"
    f"{OPT_OUT_PHRASE}"
)


@tagged("post_install", "-at_install", "petspot_wa_sahel_tagged")
class TestSahelTaggedAudience(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Settings = cls.env["petspot.wa.marketing.settings"]
        cls.settings = cls.Settings.get_settings()
        cls.settings.write(
            {
                "global_pause": True,
                "mock_send": True,
                "tier": 1,
                "daily_sent_count": 0,
                "daily_reserved_count": 0,
                "daily_cairo_date": cls.settings.cairo_today(),
                "consecutive_delivery_failures": 0,
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
        cls.Category = cls.env["res.partner.category"]
        cls.tags = {}
        for name in SAHEL_REQUIRED_TAG_NAMES:
            existing = cls.Category.search([("name", "=", name)])
            if len(existing) > 1:
                # Deduplicate for clean UAT
                keep = existing[0]
                (existing - keep).unlink()
                existing = keep
            elif not existing:
                existing = cls.Category.create({"name": name})
            else:
                existing = existing[0]
            cls.tags[name] = existing

        # Excluded tags used in tests
        for excl in ("Marketing Lead", "Palm Hills", "New Giza", "WorldPosta Contact"):
            cat = cls.Category.search([("name", "=", excl)], limit=1)
            if not cat:
                cat = cls.Category.create({"name": excl})
            cls.tags[excl] = cat

        audience = cls.env["petspot.wa.marketing.audience"].search(
            [("code", "=", SAHEL_TAGGED_CODE)], limit=1
        )
        if not audience:
            audience = cls.env["petspot.wa.marketing.audience"].create(
                {
                    "name": "Sahel Tagged Clients 2020–2026",
                    "code": SAHEL_TAGGED_CODE,
                    "required_tag_names_json": json.dumps(list(SAHEL_REQUIRED_TAG_NAMES)),
                }
            )
        cls.audience = audience
        cls.audience.resolve_tags()

        cls.template = cls.env["petspot.wa.marketing.template"].create(
            {
                "name": "PetSpot Sahel Presence V1",
                "version": "PETSPOT_SAHEL_PRESENCE_V1",
                "body_ar": PRESENCE_BODY,
                "url": "https://shopify.drpaws.ai/?utm_source=whatsapp&utm_medium=petspot_marketing&utm_campaign=sahel_presence_tagged",
                "state": "draft",
            }
        )
        cls.template.action_approve()

    def _opt_in(self, partner, phone, status="opted_in"):
        from odoo.addons.petspot_wa_marketing_consent.models.wa_marketing_consent import (
            normalize_eg_mobile,
        )

        mobile = normalize_eg_mobile(phone)
        vals = {
            "partner_id": partner.id,
            "mobile_normalized": mobile,
            "mobile_raw": phone,
            "channel": "whatsapp",
            "purpose": "marketing",
            "status": status,
            "consent_source": "staff_recorded",
            "staff_explicit_confirm": True,
            "wording_id": self.wording.id,
            "wording_version": self.wording.version,
            "wording_text": self.wording.body_ar or "w",
            "consent_timestamp": fields.Datetime.now(),
            "captured_by": self.env.user.id,
            "evidence_ref": "SAHEL-TAGGED-UAT",
        }
        return self.Consent.create(vals)

    def _person(self, name, phone, tag_names=None, opted_in=False, is_company=False, active=True):
        cats = self.Category.browse()
        for n in tag_names or []:
            cats |= self.tags[n]
        partner = self.env["res.partner"].create(
            {
                "name": name,
                "phone": phone,
                "is_company": is_company,
                "active": active,
                "category_id": [(6, 0, cats.ids)],
            }
        )
        if opted_in and not is_company:
            self._opt_in(partner, phone)
        return partner

    def _campaign(self):
        return self.env["petspot.wa.marketing.campaign"].create(
            {
                "name": "PetSpot Sahel Presence — Tagged Years",
                "template_id": self.template.id,
                "state": "draft",
            }
        )

    def test_01_sahel_client_only_included_in_domain(self):
        p = self._person("Ahmed SahelClient", "01011110001", ["Sahel Client"])
        camp = self._campaign()
        camp.action_load_sahel_tagged_audience()
        domain = ast.literal_eval(camp.partner_domain)
        ids = self.env["res.partner"].search(domain).ids
        self.assertIn(p.id, ids)

    def test_02_year_tag_only_included(self):
        p = self._person("Mona Sahel25", "01011110002", ["Sahel 2025"])
        camp = self._campaign()
        camp.action_load_sahel_tagged_audience()
        domain = ast.literal_eval(camp.partner_domain)
        self.assertIn(p.id, self.env["res.partner"].search(domain).ids)

    def test_03_multi_tag_dedup_once(self):
        p = self._person(
            "Karim Multi",
            "01011110003",
            ["Sahel Client", "Sahel 2024", "Sahel 2025"],
        )
        camp = self._campaign()
        camp.action_load_sahel_tagged_audience()
        domain = ast.literal_eval(camp.partner_domain)
        found = self.env["res.partner"].search(domain)
        self.assertEqual(len(found.filtered(lambda r: r.id == p.id)), 1)

    def test_04_company_excluded(self):
        p = self._person("Co Sahel", "01011110004", ["Sahel 2025"], is_company=True)
        camp = self._campaign()
        camp.action_load_sahel_tagged_audience()
        domain = ast.literal_eval(camp.partner_domain)
        self.assertNotIn(p.id, self.env["res.partner"].search(domain).ids)

    def test_05_inactive_excluded(self):
        p = self._person("Old Inactive", "01011110005", ["Sahel 2023"], active=False)
        camp = self._campaign()
        camp.action_load_sahel_tagged_audience()
        domain = ast.literal_eval(camp.partner_domain)
        self.assertNotIn(p.id, self.env["res.partner"].search(domain).ids)

    def test_06_excluded_tag_not_eligible(self):
        p = self._person(
            "Lead Tagged",
            "01011110006",
            ["Sahel 2025", "Marketing Lead"],
            opted_in=True,
        )
        camp = self._campaign()
        camp.action_load_sahel_tagged_audience()
        Eligibility = self.env["petspot.wa.marketing.queue.eligibility"]
        res = Eligibility.evaluate(
            p, campaign=camp, template=self.template, check_pause=False, check_instance=False
        )
        self.assertFalse(res["eligible"])
        self.assertIn("excluded_tags", res["reason"])

    def test_07_tagged_no_consent_excluded(self):
        p = self._person("No Consent", "01011110007", ["Sahel Client"])
        camp = self._campaign()
        camp.action_load_sahel_tagged_audience()
        Eligibility = self.env["petspot.wa.marketing.queue.eligibility"]
        res = Eligibility.evaluate(
            p, campaign=camp, template=self.template, check_pause=False, check_instance=False
        )
        self.assertFalse(res["eligible"])
        self.assertIn(res["reason"], ("no_consent_record", "consent_pending"))

    def test_08_opted_in_synthetic_eligible(self):
        # Name must be reliable for greeting; eligibility uses name markers separately
        p = self._person("Nour Eligible", "01011110008", ["Sahel 2026"], opted_in=True)
        camp = self._campaign()
        camp.action_load_sahel_tagged_audience()
        Eligibility = self.env["petspot.wa.marketing.queue.eligibility"]
        res = Eligibility.evaluate(
            p, campaign=camp, template=self.template, check_pause=False, check_instance=False
        )
        self.assertTrue(res["eligible"], res)

    def test_09_opted_out_and_wrong_number(self):
        p1 = self._person("Out One", "01011110009", ["Sahel 2022"])
        self._opt_in(p1, "01011110009", status="opted_out")
        p2 = self._person("Wrong Two", "01011110010", ["Sahel 2022"])
        self._opt_in(p2, "01011110010", status="wrong_number")
        camp = self._campaign()
        Eligibility = self.env["petspot.wa.marketing.queue.eligibility"]
        r1 = Eligibility.evaluate(
            p1, campaign=camp, template=self.template, check_pause=False, check_instance=False
        )
        r2 = Eligibility.evaluate(
            p2, campaign=camp, template=self.template, check_pause=False, check_instance=False
        )
        self.assertEqual(r1["reason"], "opted_out")
        self.assertEqual(r2["reason"], "wrong_number")

    def test_10_duplicate_mobile_fail_closed(self):
        phone = "01011110011"
        self._person("Dup A", phone, ["Sahel 2025"], opted_in=True)
        p2 = self._person("Dup B", phone, ["Sahel 2024"], opted_in=False)
        camp = self._campaign()
        Eligibility = self.env["petspot.wa.marketing.queue.eligibility"]
        res = Eligibility.evaluate(
            p2, campaign=camp, template=self.template, check_pause=False, check_instance=False
        )
        self.assertFalse(res["eligible"])
        self.assertIn("duplicate_mobile", res["reason"])

    def test_11_missing_tag_fail_closed(self):
        aud = self.env["petspot.wa.marketing.audience"].create(
            {
                "name": "Broken",
                "code": "SAHEL_BROKEN_MISSING",
                "required_tag_names_json": json.dumps(["Sahel Client", "Sahel DOESNOTEXIST999"]),
            }
        )
        with self.assertRaises(UserError):
            aud.resolve_tags()

    def test_12_no_visit_sale_queries_on_load(self):
        camp = self._campaign()
        queried = []

        orig_execute = None

        def watch_execute(self_cr, query, *args, **kwargs):
            q = query if isinstance(query, str) else str(query)
            low = q.lower()
            if "pet_medical_visit" in low or "sale_order" in low or "account_move" in low:
                queried.append(q[:200])
            return orig_execute(query, *args, **kwargs)

        # Patch cursor execute on this env's cr
        cr = self.env.cr
        orig_execute = cr.execute

        def wrapped(query, *args, **kwargs):
            q = query if isinstance(query, str) else str(query)
            low = q.lower()
            if any(
                t in low
                for t in ("pet_medical_visit", "sale_order", "account_move", "calendar_event")
            ):
                queried.append(q[:240])
            return orig_execute(query, *args, **kwargs)

        cr.execute = wrapped
        try:
            camp.action_load_sahel_tagged_audience()
        finally:
            cr.execute = orig_execute
        self.assertEqual(queried, [], "visit/sale models must not be queried: %s" % queried)

    def test_13_preview_creates_no_queue(self):
        self._person("Preview Only", "01011110013", ["Sahel Client"], opted_in=True)
        camp = self._campaign()
        before = self.env["petspot.wa.marketing.queue.item"].search_count([])
        camp.action_load_sahel_tagged_audience()
        after = self.env["petspot.wa.marketing.queue.item"].search_count([])
        self.assertEqual(before, after)
        audit = json.loads(camp.preview_audit_json or "{}")
        self.assertFalse(audit.get("queue_created", True))
        self.assertFalse(audit.get("phones_in_report", True))

    def test_14_draft_cannot_dispatch(self):
        camp = self._campaign()
        self.assertEqual(camp.state, "draft")
        Item = self.env["petspot.wa.marketing.queue.item"]
        # Even if a stray pending existed, dispatcher requires approved_scheduled/sending
        processed = self.env["petspot.wa.marketing.dispatcher"].cron_process_queue(limit=5)
        self.assertEqual(processed, 0)
        self.assertTrue(self.settings.global_pause)

    def test_15_legacy_wa_campaign_blocked(self):
        if "wa.campaign" not in self.env:
            self.skipTest("wa.campaign not installed")
        Guard = self.env["wa.campaign"]
        camp = Guard.create(
            {
                "name": "LEGACY BLOCK UAT",
                "message": "blocked by petspot_wa_legacy_marketing_guard",
            }
        )
        with self.assertRaises(UserError):
            camp.action_start_campaign()

    def test_16_sabry_min_cannot_be_selected(self):
        with self.assertRaises(Exception):
            self.settings.write({"evolution_instance": "sabry min"})
        self.assertEqual(self.settings.evolution_instance, REQUIRED_INSTANCE)

    def test_17_greeting_named_and_fallback(self):
        p = self._person("Sara Named", "01011110017", ["Sahel 2025"])
        named = self.template.render_body(p)
        self.assertIn("أهلاً Sara 👋", named)
        fallback = self.template.render_body(self.env["res.partner"].browse())
        self.assertIn("أهلاً بيك 👋", fallback)
        bad = self._person("UAT Synth 99", "01011110018", ["Sahel 2025"])
        bad_body = self.template.render_body(bad)
        self.assertIn("أهلاً بيك 👋", bad_body)

    def test_18_whatsapp_ready_not_consent(self):
        wa = self.Category.search([("name", "=", "WhatsApp Ready")], limit=1)
        if not wa:
            wa = self.Category.create({"name": "WhatsApp Ready"})
        p = self._person("Ready Tag Only", "01011110019", ["Sahel Client"])
        p.write({"category_id": [(4, wa.id)]})
        Eligibility = self.env["petspot.wa.marketing.queue.eligibility"]
        camp = self._campaign()
        res = Eligibility.evaluate(
            p, campaign=camp, template=self.template, check_pause=False, check_instance=False
        )
        self.assertFalse(res["eligible"])
        self.assertNotEqual(res.get("reason"), "eligible")
