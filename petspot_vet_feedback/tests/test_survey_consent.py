# -*- coding: utf-8 -*-
"""UAT tests for optional post-visit WA marketing consent (TEST only)."""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user

from odoo.addons.petspot_vet_feedback.models.survey_user_input import POST_VISIT_WORDING


@tagged("post_install", "-at_install", "petspot_survey_consent")
class TestPostVisitSurveyConsent(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Consent = cls.env["petspot.wa.marketing.consent"]
        cls.Wording = cls.env["petspot.wa.consent.wording"]
        wording = cls.Wording.search([("version", "=", "post_visit_v1_1")], limit=1)
        if not wording:
            wording = cls.Wording.create(
                {
                    "name": "Post-visit survey v1.1",
                    "version": "post_visit_v1_1",
                    "route": "post_visit_survey",
                    "body_ar": POST_VISIT_WORDING,
                    "body_en": POST_VISIT_WORDING,
                    "active": True,
                }
            )
        cls.wording = wording
        cls.survey = cls.env.ref("petspot_vet_feedback.vet_feedback_survey")
        cls.q_consent = cls.env.ref(
            "petspot_vet_feedback.vet_feedback_q_wa_marketing_consent",
            raise_if_not_found=False,
        )
        cls.a_consent = cls.env.ref(
            "petspot_vet_feedback.vet_feedback_q_wa_marketing_consent_yes",
            raise_if_not_found=False,
        )
        # Minimal questions for completion if needed
        cls.Pet = cls.env["pet.pet"]
        cls.Partner = cls.env["res.partner"]

    def _synthetic_owner(self, name, phone):
        return self.Partner.create(
            {"name": name, "phone": phone, "is_company": False}
        )

    def _make_input(self, owner, tick_consent=False):
        user_input = self.survey.sudo()._create_answer(
            email=False, partner=False, user=False, check_attempts=False
        )
        if user_input.partner_id:
            user_input.sudo().write({"partner_id": False})
        # Attach synthetic visit-like context via partner on capture path:
        # set partner_id temporarily for owner resolution when no visit
        user_input.sudo().write({"partner_id": owner.id})
        if tick_consent and self.q_consent and self.a_consent:
            self.env["survey.user_input.line"].sudo().create(
                {
                    "user_input_id": user_input.id,
                    "question_id": self.q_consent.id,
                    "answer_type": "suggestion",
                    "suggested_answer_id": self.a_consent.id,
                }
            )
        return user_input

    def test_01_unticked_creates_no_consent(self):
        owner = self._synthetic_owner("UAT Survey No Consent", "01070001111")
        before = self.Consent.search_count([])
        ui = self._make_input(owner, tick_consent=False)
        ui._petspot_capture_optional_wa_marketing_consent()
        self.assertEqual(self.Consent.search_count([]), before)
        self.assertFalse(
            self.Consent.search(
                [("mobile_normalized", "ilike", "1070001111")], limit=1
            )
        )

    def test_02_ticked_creates_pending_review(self):
        if not self.q_consent:
            self.skipTest("consent question not installed")
        owner = self._synthetic_owner("UAT Survey Tick Consent", "01070002222")
        ui = self._make_input(owner, tick_consent=True)
        rec = ui._petspot_capture_optional_wa_marketing_consent()
        self.assertTrue(rec)
        self.assertEqual(rec.status, "pending_review")
        self.assertTrue(rec.checkbox_explicit)
        self.assertEqual(rec.wording_text.strip(), POST_VISIT_WORDING.strip())
        self.assertEqual(rec.consent_source, "post_visit_survey")
        self.assertTrue(rec.technical_submission_id)

    def test_03_duplicate_submit_one_record(self):
        if not self.q_consent:
            self.skipTest("consent question not installed")
        owner = self._synthetic_owner("UAT Survey Dup", "01070003333")
        ui1 = self._make_input(owner, tick_consent=True)
        r1 = ui1._petspot_capture_optional_wa_marketing_consent()
        ui2 = self._make_input(owner, tick_consent=True)
        r2 = ui2._petspot_capture_optional_wa_marketing_consent()
        self.assertEqual(r1.id, r2.id)
        self.assertEqual(
            self.Consent.search_count(
                [
                    ("partner_id", "=", owner.id),
                    ("status", "=", "pending_review"),
                ]
            ),
            1,
        )

    def test_04_company_blocked(self):
        company = self.Partner.create(
            {"name": "UAT Survey Co", "phone": "01070004444", "is_company": True}
        )
        rec = self.Consent.register_pending_from_post_visit_survey(
            company, company.phone, self.wording, checkbox_explicit=True
        )
        self.assertFalse(rec)

    def test_05_invalid_mobile_blocked(self):
        owner = self._synthetic_owner("UAT Survey Bad Mobile", "123")
        rec = self.Consent.register_pending_from_post_visit_survey(
            owner, "123", self.wording, checkbox_explicit=True
        )
        self.assertFalse(rec)

    def test_06_opted_out_blocked(self):
        owner = self._synthetic_owner("UAT Survey Opted Out", "01070005555")
        from odoo.addons.petspot_wa_marketing_consent.models.wa_marketing_consent import (
            normalize_eg_mobile,
        )

        mobile = normalize_eg_mobile("01070005555")
        self.Consent.create(
            {
                "partner_id": owner.id,
                "mobile_normalized": mobile,
                "mobile_raw": "01070005555",
                "channel": "whatsapp",
                "purpose": "marketing",
                "status": "opted_out",
                "consent_source": "staff_recorded",
                "wording_text": "x",
                "wording_version": "staff_v1_1_approved",
            }
        )
        rec = self.Consent.register_pending_from_post_visit_survey(
            owner, "01070005555", self.wording, checkbox_explicit=True
        )
        self.assertFalse(rec)
        self.assertEqual(
            self.Consent.search([("mobile_normalized", "=", mobile)], limit=1).status,
            "opted_out",
        )

    def test_07_wrong_number_blocked(self):
        owner = self._synthetic_owner("UAT Survey Wrong", "01070006666")
        from odoo.addons.petspot_wa_marketing_consent.models.wa_marketing_consent import (
            normalize_eg_mobile,
        )

        mobile = normalize_eg_mobile("01070006666")
        self.Consent.create(
            {
                "partner_id": owner.id,
                "mobile_normalized": mobile,
                "mobile_raw": "01070006666",
                "channel": "whatsapp",
                "purpose": "marketing",
                "status": "wrong_number",
                "consent_source": "staff_recorded",
                "wording_text": "x",
                "wording_version": "staff_v1_1_approved",
            }
        )
        rec = self.Consent.register_pending_from_post_visit_survey(
            owner, "01070006666", self.wording, checkbox_explicit=True
        )
        self.assertFalse(rec)

    def test_08_sabry_confirm_opted_in(self):
        if not self.q_consent:
            self.skipTest("consent question not installed")
        owner = self._synthetic_owner("UAT Survey Confirm", "01070007777")
        ui = self._make_input(owner, tick_consent=True)
        rec = ui._petspot_capture_optional_wa_marketing_consent()
        # run as admin
        rec.with_user(self.env.ref("base.user_admin")).action_confirm_pending_review()
        self.assertEqual(rec.status, "opted_in")

    def test_09_non_sabry_cannot_confirm(self):
        if not self.q_consent:
            self.skipTest("consent question not installed")
        owner = self._synthetic_owner("UAT Survey NonSabry", "01070008888")
        ui = self._make_input(owner, tick_consent=True)
        rec = ui._petspot_capture_optional_wa_marketing_consent()
        demo = new_test_user(
            self.env,
            login="uat_non_sabry_survey",
            groups="base.group_user,petspot_wa_marketing_consent.group_wa_consent_manager",
        )
        with self.assertRaises(UserError):
            rec.with_user(demo).action_confirm_pending_review()
        self.assertEqual(rec.status, "pending_review")

    def test_10_coupon_independent_of_consent(self):
        """Reward path still callable when consent capture returns False."""
        owner = self._synthetic_owner("UAT Survey Coupon Ind", "01070009999")
        ui = self._make_input(owner, tick_consent=False)
        # No visit → reward returns False but must not raise
        self.assertFalse(ui._grant_vet_feedback_reward())
        ui._petspot_capture_optional_wa_marketing_consent()
