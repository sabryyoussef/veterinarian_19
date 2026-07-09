# -*- coding: utf-8 -*-
import logging

from odoo import fields, models, _

_logger = logging.getLogger(__name__)


class PetMedicalVisit(models.Model):
    _inherit = 'pet.medical.visit'

    feedback_user_input_id = fields.Many2one(
        'survey.user_input', string='Feedback Survey Response', copy=False, readonly=True,
    )
    feedback_request_sent = fields.Boolean(
        string='Feedback Request Sent', default=False, copy=False, index=True,
    )
    feedback_rating = fields.Float(
        string='Owner Feedback Rating',
        help='Average owner rating (1-5) from the post-visit vet review survey.',
        readonly=True,
    )
    feedback_coupon_id = fields.Many2one(
        'loyalty.card', string='Feedback Reward Coupon', copy=False, readonly=True,
    )

    def _send_vet_feedback_request(self):
        """Create a public survey answer (no partner/user) and WhatsApp the link."""
        survey = self.env.ref(
            'petspot_vet_feedback.vet_feedback_survey', raise_if_not_found=False,
        )
        if not survey:
            _logger.warning('vet feedback survey not configured')
            return False

        sent_any = False
        for visit in self:
            if visit.feedback_request_sent or visit.status != 'completed':
                continue
            if not visit.vet_employee_id:
                continue
            owner = visit.pet_id.owner_id if visit.pet_id else False
            if not owner:
                continue

            phone = owner.phone
            # Public answer: no partner_id / no user — only visit_id for coupon reward.
            user_input = survey.sudo()._create_answer(
                email=False,
                partner=False,
                user=False,
                check_attempts=False,
                visit_id=visit.id,
            )
            # Ensure no partner was attached (e.g. if sudo user leaked in).
            if user_input.partner_id:
                user_input.sudo().write({'partner_id': False, 'email': False})

            survey_url = visit._petspot_build_feedback_survey_url(user_input)
            visit.sudo().write({
                'feedback_user_input_id': user_input.id,
                'feedback_request_sent': True,
            })

            vet_name = visit.vet_employee_id.name or _('your veterinarian')
            pet_name = visit.pet_id.name if visit.pet_id else _('your pet')
            msg = _(
                'شكراً لزيارتكم PetSpot 🐾\n\n'
                'نرجو تقييم تجربتكم مع %(vet)s للحيوان %(pet)s:\n'
                '%(url)s\n\n'
                'بعد إكمال الاستبيان ستحصلون على خصم 10%% على الزيارة القادمة (صالح 60 يوم).'
            ) % {'vet': vet_name, 'pet': pet_name, 'url': survey_url}

            if phone:
                visit.petspot_notify_whatsapp_number(phone, msg)
            if visit.chatwoot_conversation_id:
                visit.petspot_notify_chatwoot(visit.chatwoot_conversation_id, msg)
            sent_any = True
        return sent_any

    def _petspot_build_feedback_survey_url(self, user_input):
        self.ensure_one()
        base = self._petspot_public_base_url()
        survey = user_input.survey_id
        return '%s%s?answer_token=%s' % (base, survey.get_start_url(), user_input.access_token)
