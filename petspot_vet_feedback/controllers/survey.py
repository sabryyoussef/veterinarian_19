# -*- coding: utf-8 -*-
from odoo.http import request
from odoo.addons.survey.controllers.main import Survey


class PetspotVetFeedbackSurvey(Survey):
    """Vet feedback survey is public: never block on logged-in user / partner mismatch."""

    def _check_validity(self, survey_sudo, answer_sudo, answer_token, ensure_token=True, check_partner=True):
        feedback_survey = request.env.ref(
            'petspot_vet_feedback.vet_feedback_survey', raise_if_not_found=False,
        )
        if feedback_survey and survey_sudo and survey_sudo.id == feedback_survey.id:
            check_partner = False
        return super()._check_validity(
            survey_sudo, answer_sudo, answer_token,
            ensure_token=ensure_token, check_partner=check_partner,
        )
