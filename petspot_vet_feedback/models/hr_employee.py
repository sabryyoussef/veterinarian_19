# -*- coding: utf-8 -*-
from odoo import fields, models, tools, _


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    avg_feedback_rating = fields.Float(
        string='Avg Owner Rating', compute='_compute_feedback_stats',
    )
    feedback_count = fields.Integer(
        string='Feedback Responses', compute='_compute_feedback_stats',
    )

    def _compute_feedback_stats(self):
        for employee in self:
            rated_visits = employee.pet_medical_visit_ids.filtered(
                lambda v: v.feedback_rating > 0
            )
            employee.feedback_count = len(rated_visits)
            employee.avg_feedback_rating = (
                sum(rated_visits.mapped('feedback_rating')) / len(rated_visits)
            ) if rated_visits else 0.0

    def _build_vet_assessment(self):
        html = super()._build_vet_assessment()
        self.ensure_one()
        if self.feedback_count:
            extra = (
                '<p><b>%s</b> %.1f/5 (%d %s)</p>'
                % (_('Average owner rating:'), self.avg_feedback_rating, self.feedback_count, _('responses'))
            )
            html = html.replace('</div>', extra + '</div>', 1)
        return html
