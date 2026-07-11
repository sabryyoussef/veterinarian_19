from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta

class PetMedicalVisit(models.Model):
    _name = 'pet.medical.visit'
    _description = 'Pet Medical Visit'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc'

    VISIT_TYPE_SELECTION = [
        ('checkup', 'Regular Exam'),
        ('emergency', 'Emergency Exam'),
        ('home_visit', 'Home Visit'),
        ('vaccination', 'Vaccination'),
        ('surgery', 'Surgery'),
        ('dental', 'Dental'),
        ('grooming', 'Grooming'),
        ('other', 'Other'),
    ]

    pet_id = fields.Many2one('pet.pet', required=True, ondelete='cascade', tracking=True, help="The pet for this medical visit")
    appointment_id = fields.Many2one('pet.appointment', string='Appointment', help="Related appointment")
    appointment_sale_order_id = fields.Many2one(
        related='appointment_id.sale_order_id',
        string='Sale Order',
        readonly=True,
    )
    appointment_has_active_invoice = fields.Boolean(
        related='appointment_id.has_active_invoice',
        string='Has Active Invoice',
        readonly=True,
    )
    appointment_state = fields.Selection(
        related='appointment_id.state',
        string='Appointment State',
        readonly=True,
    )
    date = fields.Datetime(required=True, default=fields.Datetime.now, tracking=True, help="Date and time of the medical visit")
    reason = fields.Char(required=True, tracking=True, help="Primary reason for the visit")
    visit_type = fields.Selection(
        selection=VISIT_TYPE_SELECTION,
        string='Visit Type',
        default='checkup',
        help="Type of medical visit",
    )
    status = fields.Selection([
        ('scheduled', 'Scheduled'), ('in_progress', 'In Progress'), ('completed', 'Completed'),
        ('cancelled', 'Cancelled'), ('rescheduled', 'Rescheduled')
    ], string='Status', default='scheduled', tracking=True, help="Current status of the visit")
    
    # SOAP Notes
    subjective = fields.Text(help="Subjective observations from pet owner")
    objective = fields.Text(help="Objective findings from examination")
    assessment = fields.Text(help="Assessment and diagnosis")
    plan = fields.Text(help="Treatment plan and recommendations")
    
    # Medical Details
    diagnosis = fields.Char(help="Primary diagnosis")
    procedure_performed = fields.Char(help="Procedures performed during visit")
    vital_signs = fields.Text(help="Vital signs recorded (temperature, heart rate, etc.)")
    medications_prescribed = fields.Text(help="Medications prescribed")
    follow_up_date = fields.Date(help="Recommended follow-up date")
    follow_up_notes = fields.Text(help="Follow-up instructions")
    
    # Veterinary Information
    vet_employee_id = fields.Many2one(
        'hr.employee', string='Veterinarian (Employee)', tracking=True, index=True,
        default=lambda self: self.env.user.employee_id.id if self.env.user.employee_id else False,
        help="Veterinarian (employee) who performed the visit — used for performance evaluation",
    )
    vet_id = fields.Many2one(
        'res.partner',
        domain=lambda self: [('id', '=', self.env.user.partner_id.id)] if self.env.user.has_group('pet_management.group_pet_staff_health') else [],
        help="Veterinarian who performed the visit"
    )
    vet_notes = fields.Text(help="Additional notes from the veterinarian")

    # Case documentation quality (vet evaluation)
    case_completeness_pct = fields.Float(
        string='Case Completeness %',
        compute='_compute_case_completeness', store=True,
        help="How complete the case documentation is (SOAP, diagnosis, plan, vet, billing, diagnostics).",
    )
    is_case_complete = fields.Boolean(
        string='Case Complete',
        compute='_compute_case_completeness', store=True,
        help="True when all required documentation items are filled.",
    )
    missing_case_items = fields.Text(
        string='Missing Documentation',
        compute='_compute_case_completeness', store=True,
        help="List of documentation items the veterinarian still needs to fill in.",
    )
    missing_case_count = fields.Integer(
        string='Missing Items',
        compute='_compute_case_completeness', store=True,
    )
    
    # Financial
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        store=True,
        readonly=True,
    )
    line_ids = fields.One2many(
        'pet.medical.visit.line',
        'visit_id',
        string='Visit Lines',
    )
    diagnostic_report_ids = fields.One2many(
        'pet.medical.diagnostic.report',
        'visit_id',
        string='Diagnostic Reports',
    )
    diagnostic_report_count = fields.Integer(
        compute='_compute_diagnostic_report_stats',
        string='Diagnostics Count',
    )
    abnormal_diagnostic_count = fields.Integer(
        compute='_compute_diagnostic_report_stats',
        string='Abnormal Diagnostics',
    )
    discount_amount = fields.Float(
        string='Discount Amount',
        help='Fixed discount applied to visit line subtotal.',
    )
    amount_subtotal = fields.Float(
        compute='_compute_visit_amounts',
        store=True,
        string='Subtotal',
    )
    amount_total = fields.Float(
        compute='_compute_visit_amounts',
        store=True,
        string='Total',
    )
    cost = fields.Float(help="Cost of the medical visit")
    payment_status = fields.Selection([
        ('pending', 'Pending'), ('paid', 'Paid'), ('partial', 'Partial'), ('cancelled', 'Cancelled')
    ], string='Payment Status', default='pending', help="Payment status for the visit")
    
    # Computed Fields
    days_since_visit = fields.Integer(compute='_compute_days_since_visit', store=False, help="Days since the visit")
    is_overdue = fields.Boolean(compute='_compute_is_overdue', search='_search_is_overdue', store=False, help="Whether follow-up is overdue")
    state_color = fields.Integer(compute='_compute_state_color', string='State Color', store=True, help="Color index for status display")
    
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, help="Company this visit belongs to")

    @api.depends('diagnostic_report_ids', 'diagnostic_report_ids.is_abnormal', 'diagnostic_report_ids.status')
    def _compute_diagnostic_report_stats(self):
        for visit in self:
            active_reports = visit.diagnostic_report_ids.filtered(lambda r: r.status != 'cancelled')
            visit.diagnostic_report_count = len(active_reports)
            visit.abnormal_diagnostic_count = len(active_reports.filtered('is_abnormal'))

    @api.depends(
        'subjective', 'objective', 'assessment', 'plan', 'diagnosis',
        'vet_employee_id', 'vet_id',
        'line_ids', 'line_ids.price_subtotal', 'line_ids.line_type',
        'diagnostic_report_ids', 'diagnostic_report_ids.status',
    )
    def _compute_case_completeness(self):
        """Score documentation quality and list what is still missing.

        Each item is worth an equal share. ``missing_case_items`` gives the
        veterinarian a clear checklist of what still needs to be filled in.
        """
        for visit in self:
            checks = [
                (_('Subjective (S)'), bool(visit.subjective)),
                (_('Objective (O)'), bool(visit.objective)),
                (_('Assessment (A)'), bool(visit.assessment)),
                (_('Plan (P)'), bool(visit.plan)),
                (_('Diagnosis'), bool(visit.diagnosis)),
                (_('Responsible veterinarian'), bool(visit.vet_employee_id or visit.vet_id)),
                (_('Billable service/product line'), any(line.price_subtotal > 0 for line in visit.line_ids)),
            ]
            # Diagnostic reports required only when diagnostic lines exist
            diag_lines = visit.line_ids.filtered(lambda l: l.line_type == 'diagnostic')
            if diag_lines:
                active_reports = visit.diagnostic_report_ids.filtered(lambda r: r.status != 'cancelled')
                checks.append((_('Diagnostic report attached'), bool(active_reports)))

            total = len(checks)
            missing = [label for label, done in checks if not done]
            done = total - len(missing)
            visit.case_completeness_pct = round((done / total) * 100.0, 1) if total else 0.0
            visit.is_case_complete = not missing
            visit.missing_case_count = len(missing)
            visit.missing_case_items = "\n".join("• %s" % label for label in missing)

    @api.onchange('vet_employee_id')
    def _onchange_vet_employee_id(self):
        """Keep the legacy partner vet_id in sync with the chosen employee."""
        if self.vet_employee_id:
            partner = self.vet_employee_id.work_contact_id
            if not partner and self.vet_employee_id.user_id:
                partner = self.vet_employee_id.user_id.partner_id
            if partner:
                self.vet_id = partner.id

    @api.depends('line_ids.price_subtotal', 'discount_amount')
    def _compute_visit_amounts(self):
        for visit in self:
            subtotal = sum(visit.line_ids.mapped('price_subtotal'))
            visit.amount_subtotal = subtotal
            total = max(subtotal - (visit.discount_amount or 0.0), 0.0)
            visit.amount_total = total
            visit.cost = total

    @api.depends('date')
    def _compute_days_since_visit(self):
        today = fields.Date.today()
        for visit in self:
            if visit.date:
                visit_date = visit.date.date()
                visit.days_since_visit = (today - visit_date).days
            else:
                visit.days_since_visit = 0

    @api.depends('follow_up_date', 'status')
    def _compute_is_overdue(self):
        today = fields.Date.today()
        for visit in self:
            visit.is_overdue = (
                visit.follow_up_date and 
                visit.follow_up_date < today and 
                visit.status in ['completed', 'scheduled']
            )

    @api.depends('status')
    def _compute_state_color(self):
        color_map = {
            'scheduled': 1,      # Blue
            'in_progress': 2,    # Green
            'completed': 3,      # Orange
            'cancelled': 4,      # Red
            'rescheduled': 5,    # Purple
        }
        for visit in self:
            visit.state_color = color_map.get(visit.status, 1)

    def _search_is_overdue(self, operator, value):
        """Search method for is_overdue field"""
        today = fields.Date.today()
        if operator == '=' and value:
            return [
                ('follow_up_date', '<', today),
                ('status', 'in', ['completed', 'scheduled'])
            ]
        elif operator == '=' and not value:
            return [
                '|',
                ('follow_up_date', '=', False),
                '|',
                ('follow_up_date', '>=', today),
                ('status', 'not in', ['completed', 'scheduled'])
            ]
        return []

    def action_mark_completed(self):
        """Mark visit as completed"""
        self.status = 'completed'

    def action_mark_cancelled(self):
        """Mark visit as cancelled"""
        self.status = 'cancelled'

    def action_reschedule(self):
        """Mark visit as rescheduled"""
        self.status = 'rescheduled'

    @api.model
    def _get_consultation_product(self):
        product = self.env.ref(
            'pet_management.product_consultation_exam',
            raise_if_not_found=False,
        )
        if product:
            return product
        return self.env['product.product'].search([
            '|',
            ('default_code', '=', 'EXAM'),
            ('name', 'ilike', 'consultation'),
            ('type', '=', 'service'),
        ], limit=1)

    def _get_consultation_line(self):
        self.ensure_one()
        return self.line_ids.filtered(lambda line: line.line_type == 'consultation')[:1]

    def _sync_consultation_line(self, price=None):
        self.ensure_one()
        if price is None:
            price = self.env['pet.exam.price.config'].get_price_for_visit_type(
                self.visit_type,
                company=self.company_id,
            )
        product = self._get_consultation_product()
        line = self._get_consultation_line()
        line_vals = {
            'line_type': 'consultation',
            'quantity': 1.0,
            'price_unit': price,
        }
        if product:
            line_vals.update({
                'product_id': product.id,
                'name': product.display_name,
            })
        elif not line:
            line_vals['name'] = dict(self.VISIT_TYPE_SELECTION).get(
                self.visit_type,
                _('Consultation'),
            )
        if line:
            line.write(line_vals)
        else:
            line_vals['visit_id'] = self.id
            self.env['pet.medical.visit.line'].create(line_vals)

    @api.onchange('visit_type')
    def _onchange_visit_type(self):
        if self.visit_type:
            self._sync_consultation_line()

    @api.model_create_multi
    def create(self, vals_list):
        visits = super().create(vals_list)
        for visit, vals in zip(visits, vals_list):
            if vals.get('visit_type') and not vals.get('line_ids'):
                visit._sync_consultation_line()
        return visits

    def write(self, vals):
        res = super().write(vals)
        if 'visit_type' in vals:
            for visit in self:
                visit._sync_consultation_line()
        return res

    def action_view_diagnostic_reports(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Diagnostic Reports'),
            'res_model': 'pet.medical.diagnostic.report',
            'view_mode': 'list,form',
            'domain': [('visit_id', '=', self.id)],
            'context': {
                'default_visit_id': self.id,
                'default_vet_id': self.vet_id.id,
            },
        }

    def name_get(self):
        """Custom name_get to show pet name and reason in Many2one selection"""
        result = []
        for rec in self:
            pet_name = rec.pet_id.name if rec.pet_id else 'Unknown Pet'
            reason = rec.reason if rec.reason else 'No Reason'
            name = f"{pet_name} - {reason}"
            result.append((rec.id, name))
        return result

    def action_view_pet(self):
        """Action to view the pet record"""
        action = self.env.ref('pet_management.action_pet_pet').read()[0]
        action['domain'] = [('id', '=', self.pet_id.id)]
        action['context'] = {'default_id': self.pet_id.id}
        return action

    def action_send_notification(self):
        """Create and send notification for this medical visit"""
        for rec in self:
            # Determine notification type and priority based on visit status
            if rec.status == 'scheduled':
                notification_type = 'medical_visit_due'
                priority = 'high' if rec.is_overdue else 'medium'
                message = f"Medical visit scheduled: {rec.pet_id.name} has a {rec.visit_type or 'general'} visit on {rec.date.strftime('%B %d, %Y')} with {rec.vet_id.name if rec.vet_id else 'veterinarian'}."
            elif rec.status == 'in_progress':
                notification_type = 'general'
                priority = 'medium'
                message = f"In progress: {rec.pet_id.name}'s {rec.visit_type or 'medical'} visit is currently in progress with {rec.vet_id.name if rec.vet_id else 'veterinarian'}."
            elif rec.status == 'completed':
                notification_type = 'general'
                priority = 'low'
                message = f"Completed: {rec.pet_id.name}'s {rec.visit_type or 'medical'} visit was completed on {rec.date.strftime('%B %d, %Y')}. Follow-up: {rec.follow_up_date.strftime('%B %d, %Y') if rec.follow_up_date else 'Not required'}."
            elif rec.status == 'cancelled':
                notification_type = 'general'
                priority = 'low'
                message = f"Cancelled: {rec.pet_id.name}'s {rec.visit_type or 'medical'} visit scheduled for {rec.date.strftime('%B %d, %Y')} has been cancelled."
            elif rec.status == 'rescheduled':
                notification_type = 'general'
                priority = 'medium'
                message = f"Rescheduled: {rec.pet_id.name}'s {rec.visit_type or 'medical'} visit has been rescheduled. New date: {rec.date.strftime('%B %d, %Y')}."
            else:
                notification_type = 'general'
                priority = 'low'
                message = f"Update: {rec.pet_id.name}'s {rec.visit_type or 'medical'} visit status is {rec.status}."
            
            # Create notification
            notification = self.env['pet.notification'].create({
                'name': f'Medical Visit Notification - {rec.pet_id.name}',
                'pet_id': rec.pet_id.id,
                'notification_type': notification_type,
                'message': message,
                'priority': priority,
                'status': 'draft',
                'related_medical_visit_id': rec.id,
                'date_scheduled': fields.Datetime.now(),
                'is_enabled': True,
                'auto_send': True,
                'preferred_time': 'morning',
                'send_email': True,
                'send_in_app': True,
            })
            
            # Send notification immediately
            notification.action_send_notification()
            
        return {
            'type': 'ir.actions.act_window',
            'name': 'Notification Sent',
            'res_model': 'pet.notification',
            'res_id': notification.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _require_appointment_for_billing(self):
        self.ensure_one()
        if not self.appointment_id:
            raise UserError(_(
                'Link this medical visit to an appointment before creating a sale order.'
            ))
        if not self.pet_id:
            raise UserError(_('A pet is required before creating a sale order.'))
        return self.appointment_id

    def action_create_sale_order(self):
        """Create/open the appointment sale order from the medical visit screen."""
        appointment = self._require_appointment_for_billing()
        return appointment.action_create_or_open_sale_order()

    def action_view_sale_order(self):
        """Open the sale order linked to this visit's appointment."""
        appointment = self._require_appointment_for_billing()
        if not appointment.sale_order_id:
            raise UserError(_('No sale order exists for this medical visit yet.'))
        return appointment.action_view_sale_order()

    def action_confirm_and_create_invoice(self):
        """Confirm SO and create invoice via the linked appointment."""
        appointment = self._require_appointment_for_billing()
        return appointment.action_confirm_and_create_invoice()

    def action_create_followup_notification(self):
        """Create a follow-up notification for this medical visit"""
        for rec in self:
            if rec.status != 'completed' or not rec.follow_up_date:
                continue
                
            # Check if follow-up notification already exists
            existing = self.env['pet.notification'].search([
                ('related_medical_visit_id', '=', rec.id),
                ('notification_type', '=', 'medical_visit_due'),
                ('status', 'in', ['draft', 'sent'])
            ])
            
            if not existing:
                notification = self.env['pet.notification'].create({
                    'name': f'Medical Follow-up - {rec.pet_id.name}',
                    'pet_id': rec.pet_id.id,
                    'notification_type': 'medical_visit_due',
                    'message': f"Follow-up required: {rec.pet_id.name} needs a follow-up visit on {rec.follow_up_date.strftime('%B %d, %Y')}. Reason: {rec.follow_up_notes or 'As discussed during the last visit'}.",
                    'priority': 'high' if rec.is_overdue else 'medium',
                    'status': 'draft',
                    'related_medical_visit_id': rec.id,
                    'date_scheduled': fields.Datetime.now(),
                    'is_enabled': True,
                    'auto_send': True,
                    'preferred_time': 'morning',
                    'send_email': True,
                    'send_in_app': True,
                })
                
                return {
                    'type': 'ir.actions.act_window',
                    'name': 'Follow-up Notification Created',
                    'res_model': 'pet.notification',
                    'res_id': notification.id,
                    'view_mode': 'form',
                    'target': 'current',
                }
