# -*- coding: utf-8 -*-
from odoo import fields, models, tools


class PetVetPerformanceReport(models.Model):
    _inherit = 'pet.vet.performance.report'

    feedback_rating = fields.Float(
        string='Owner Rating', readonly=True, aggregator='avg',
    )

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    a.id AS id,
                    a.vet_employee_id AS vet_employee_id,
                    a.company_id AS company_id,
                    c.currency_id AS currency_id,
                    a.start_datetime AS appointment_date,
                    a.primary_type AS primary_type,
                    a.state AS state,
                    a.payment_status AS payment_status,
                    COALESCE(a.amount_total, 0.0) AS revenue,
                    COALESCE(mv.case_completeness_pct, 0.0) AS case_completeness_pct,
                    COALESCE(mv.is_case_complete, FALSE) AS is_case_complete,
                    COALESCE(mv.feedback_rating, 0.0) AS feedback_rating,
                    (
                        SELECT COUNT(*) FROM pet_medical_diagnostic_report d
                        WHERE d.visit_id = mv.id AND d.status != 'cancelled'
                    ) AS diagnostic_count,
                    (
                        SELECT COUNT(*) FROM pet_medical_diagnostic_report d
                        WHERE d.visit_id = mv.id AND d.status != 'cancelled' AND d.is_abnormal
                    ) AS abnormal_diagnostic_count,
                    1 AS nbr
                FROM pet_appointment a
                LEFT JOIN pet_medical_visit mv ON mv.appointment_id = a.id
                LEFT JOIN res_company c ON c.id = a.company_id
                WHERE a.vet_employee_id IS NOT NULL
            )
        """ % self._table)
