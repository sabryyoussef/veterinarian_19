# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    is_veterinarian = fields.Boolean(
        string='Is Veterinarian',
        help="Mark this employee as a veterinarian to include them in clinic performance reports.",
    )

    pet_appointment_ids = fields.One2many(
        'pet.appointment', 'vet_employee_id', string='Appointments',
    )
    pet_medical_visit_ids = fields.One2many(
        'pet.medical.visit', 'vet_employee_id', string='Medical Visits',
    )
    pet_diagnostic_ids = fields.One2many(
        'pet.medical.diagnostic.report', 'vet_employee_id', string='Diagnostic Reports',
    )

    appointment_count = fields.Integer(
        string='Appointments', compute='_compute_vet_stats',
    )
    appointment_revenue = fields.Monetary(
        string='Total Revenue', compute='_compute_vet_stats', currency_field='vet_currency_id',
    )
    avg_case_value = fields.Monetary(
        string='Avg Case Value', compute='_compute_vet_stats', currency_field='vet_currency_id',
    )
    medical_visit_count = fields.Integer(
        string='Medical Visits', compute='_compute_vet_stats',
    )
    incomplete_case_count = fields.Integer(
        string='Incomplete Cases', compute='_compute_vet_stats',
    )
    avg_case_completeness = fields.Float(
        string='Avg Case Completeness %', compute='_compute_vet_stats',
    )
    diagnostic_count = fields.Integer(
        string='Diagnostics', compute='_compute_vet_stats',
    )
    abnormal_diagnostic_count = fields.Integer(
        string='Abnormal Diagnostics', compute='_compute_vet_stats',
    )
    inventory_items_used = fields.Float(
        string='Inventory Items Used', compute='_compute_vet_stats',
    )
    vet_currency_id = fields.Many2one(
        'res.currency', compute='_compute_vet_currency',
    )
    vet_assessment = fields.Html(
        string='Performance Assessment', compute='_compute_vet_stats',
        help="Auto-generated summary of the veterinarian's activity and documentation quality.",
    )

    def _compute_vet_currency(self):
        currency = self.env.company.currency_id
        for employee in self:
            employee.vet_currency_id = currency

    def _compute_vet_stats(self):
        for employee in self:
            appointments = employee.pet_appointment_ids
            active_appts = appointments.filtered(lambda a: a.state != 'cancelled')
            visits = employee.pet_medical_visit_ids
            diagnostics = employee.pet_diagnostic_ids.filtered(lambda d: d.status != 'cancelled')

            revenue = sum(active_appts.mapped('amount_total'))
            employee.appointment_count = len(active_appts)
            employee.appointment_revenue = revenue
            employee.avg_case_value = (revenue / len(active_appts)) if active_appts else 0.0

            employee.medical_visit_count = len(visits)
            employee.incomplete_case_count = len(visits.filtered(lambda v: not v.is_case_complete))
            employee.avg_case_completeness = (
                sum(visits.mapped('case_completeness_pct')) / len(visits)
            ) if visits else 0.0

            employee.diagnostic_count = len(diagnostics)
            employee.abnormal_diagnostic_count = len(diagnostics.filtered('is_abnormal'))
            employee.inventory_items_used = sum(
                active_appts.mapped('inventory_items_ids.quantity')
            )
            employee.vet_assessment = employee._build_vet_assessment()

    def _build_vet_assessment(self):
        self.ensure_one()
        visits = self.pet_medical_visit_ids
        incomplete = visits.filtered(lambda v: not v.is_case_complete)
        avg = (sum(visits.mapped('case_completeness_pct')) / len(visits)) if visits else 0.0

        if not visits:
            return _(
                "<p>No medical cases recorded yet for this veterinarian.</p>"
            )

        if not incomplete:
            rating = _("Excellent — all cases fully documented.")
            color = "#28a745"
        elif avg >= 75:
            rating = _("Good — a few cases need finishing.")
            color = "#f0ad4e"
        else:
            rating = _("Needs attention — several cases are incomplete.")
            color = "#dc3545"

        lines = [
            "<div>",
            "<p><b>%s</b> <span style='color:%s'>%s</span></p>" % (_("Documentation rating:"), color, rating),
            "<ul>",
            "<li>%s <b>%.0f%%</b></li>" % (_("Average case completeness:"), avg),
            "<li>%s <b>%d</b> / %d</li>" % (_("Incomplete cases:"), len(incomplete), len(visits)),
            "</ul>",
        ]
        if incomplete:
            lines.append("<p><b>%s</b></p><ul>" % _("Cases still to complete:"))
            for visit in incomplete[:15]:
                pet = visit.pet_id.name or _("Unknown pet")
                items = (visit.missing_case_items or "").replace("\n", ", ").replace("• ", "")
                lines.append("<li>%s — %s <i>(%s)</i></li>" % (
                    visit.reason or _("Visit"), pet, items or _("details missing"),
                ))
            lines.append("</ul>")
        lines.append("</div>")
        return "".join(lines)

    def _vet_action(self, name, res_model, field):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': res_model,
            'view_mode': 'list,form',
            'domain': [(field, '=', self.id)],
            'context': {'default_%s' % field: self.id},
        }

    def action_view_vet_appointments(self):
        return self._vet_action(_('Appointments'), 'pet.appointment', 'vet_employee_id')

    def action_view_vet_medical_visits(self):
        return self._vet_action(_('Medical Visits'), 'pet.medical.visit', 'vet_employee_id')

    def action_view_vet_incomplete_cases(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Incomplete Cases'),
            'res_model': 'pet.medical.visit',
            'view_mode': 'list,form',
            'domain': [('vet_employee_id', '=', self.id), ('is_case_complete', '=', False)],
            'context': {'default_vet_employee_id': self.id},
        }

    def action_view_vet_diagnostics(self):
        return self._vet_action(_('Diagnostic Reports'), 'pet.medical.diagnostic.report', 'vet_employee_id')
