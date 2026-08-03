# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import fields, models, _

_logger = logging.getLogger(__name__)

POST_VISIT_WORDING = (
    "أوافق بشكل اختياري على استلام رسائل واتساب تسويقية من عيادة Pet Spot "
    "عن خدمات العيادة والمتجر والعروض. رفضي لن يؤثر على خدمات العيادة أو الشراء، "
    "ويمكنني الإلغاء في أي وقت بالرد وقف."
)


class SurveyUserInput(models.Model):
    _inherit = "survey.user_input"

    visit_id = fields.Many2one(
        "pet.medical.visit",
        string="Medical Visit",
        index=True,
        ondelete="set null",
    )

    def _mark_done(self):
        res = super()._mark_done()
        for user_input in self:
            user_input._grant_vet_feedback_reward()
            # Consent must never block survey completion / coupon grant.
            try:
                user_input._petspot_capture_optional_wa_marketing_consent()
            except Exception:
                _logger.exception(
                    "post-visit WA marketing consent capture failed for user_input %s",
                    user_input.id,
                )
        return res

    def _grant_vet_feedback_reward(self):
        self.ensure_one()
        visit = self.visit_id
        if not visit or visit.feedback_coupon_id:
            return False

        feedback_survey = self.env.ref(
            "petspot_vet_feedback.vet_feedback_survey",
            raise_if_not_found=False,
        )
        if not feedback_survey or self.survey_id.id != feedback_survey.id:
            return False

        rating = self._compute_vet_feedback_rating()
        coupon = self._create_feedback_loyalty_card(visit)
        visit.sudo().write(
            {
                "feedback_rating": rating,
                "feedback_coupon_id": coupon.id,
            }
        )
        self._notify_owner_feedback_coupon(visit, coupon)
        return coupon

    def _compute_vet_feedback_rating(self):
        """Average the two 1-5 scale vet-rating questions."""
        self.ensure_one()
        q_overall = self.env.ref(
            "petspot_vet_feedback.vet_feedback_q_overall",
            raise_if_not_found=False,
        )
        q_vet = self.env.ref(
            "petspot_vet_feedback.vet_feedback_q_vet",
            raise_if_not_found=False,
        )
        ratings = []
        for question in (q_overall, q_vet):
            if not question:
                continue
            line = self.user_input_line_ids.filtered(
                lambda l: l.question_id == question and l.answer_type == "scale"
            )[:1]
            if line and line.value_scale:
                ratings.append(float(line.value_scale))
        return round(sum(ratings) / len(ratings), 2) if ratings else 0.0

    def _create_feedback_loyalty_card(self, visit):
        self.ensure_one()
        program = self.env.ref(
            "petspot_vet_feedback.vet_feedback_loyalty_program",
            raise_if_not_found=False,
        )
        if not program:
            raise ValueError(_("Feedback loyalty program is not configured."))
        owner = visit.pet_id.owner_id if visit.pet_id else self.partner_id
        expiration = fields.Date.today() + timedelta(days=60)
        return (
            self.env["loyalty.card"]
            .sudo()
            .create(
                {
                    "program_id": program.id,
                    "partner_id": owner.id if owner else False,
                    "points": 1.0,
                    "expiration_date": expiration,
                }
            )
        )

    def _notify_owner_feedback_coupon(self, visit, coupon):
        owner = visit.pet_id.owner_id if visit.pet_id else self.partner_id
        if not owner:
            return False
        phone = owner.phone if owner else False
        msg = _(
            "شكراً لتقييمكم PetSpot 🎁\n\n"
            "كود خصم 10%% لزيارتكم القادمة: %(code)s\n"
            "صالح لمدة 60 يوم.\n\n"
            "Thank you for your feedback!"
        ) % {"code": coupon.code}
        if phone:
            visit.petspot_notify_whatsapp_number(phone, msg)
        if visit.chatwoot_conversation_id:
            visit.petspot_notify_chatwoot(visit.chatwoot_conversation_id, msg)
        return True

    def _petspot_consent_checkbox_ticked(self):
        """Return True only when the optional consent checkbox answer is present."""
        self.ensure_one()
        q = self.env.ref(
            "petspot_vet_feedback.vet_feedback_q_wa_marketing_consent",
            raise_if_not_found=False,
        )
        ans = self.env.ref(
            "petspot_vet_feedback.vet_feedback_q_wa_marketing_consent_yes",
            raise_if_not_found=False,
        )
        if not q or not ans:
            return False
        lines = self.user_input_line_ids.filtered(
            lambda l: l.question_id.id == q.id and l.suggested_answer_id.id == ans.id
        )
        return bool(lines)

    def _petspot_capture_optional_wa_marketing_consent(self):
        self.ensure_one()
        feedback_survey = self.env.ref(
            "petspot_vet_feedback.vet_feedback_survey",
            raise_if_not_found=False,
        )
        if not feedback_survey or self.survey_id.id != feedback_survey.id:
            return False
        if not self._petspot_consent_checkbox_ticked():
            return False

        visit = self.visit_id
        owner = visit.pet_id.owner_id if visit and visit.pet_id else self.partner_id
        if not owner:
            _logger.info("skip consent: no owner on survey user_input %s", self.id)
            return False

        Consent = self.env["petspot.wa.marketing.consent"].sudo()
        Wording = self.env["petspot.wa.consent.wording"].sudo()
        wording = Wording.search([("version", "=", "post_visit_v1_1")], limit=1)
        if not wording:
            wording = Wording.create(
                {
                    "name": "Post-visit survey v1.1",
                    "version": "post_visit_v1_1",
                    "route": "post_visit_survey",
                    "body_ar": POST_VISIT_WORDING,
                    "body_en": POST_VISIT_WORDING,
                    "active": True,
                }
            )

        evidence = (
            f"post_visit_survey:user_input={self.id};"
            f"visit={visit.id if visit else 0};token={self.access_token}"
        )
        return Consent.register_pending_from_post_visit_survey(
            owner,
            owner.phone_sanitized or owner.phone,
            wording,
            survey_user_input_id=self.id,
            visit_id=visit.id if visit else False,
            technical_submission_id=self.access_token or str(self.id),
            evidence_ref=evidence,
            checkbox_explicit=True,
        )
