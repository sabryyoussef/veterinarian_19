from odoo import models, fields, api
from datetime import datetime, timedelta

class PetMedicalVisit(models.Model):
    _name = 'pet.medical.visit'
    _description = 'Pet Medical Visit'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc'

    pet_id = fields.Many2one('pet.pet', required=True, ondelete='cascade', tracking=True, help="The pet for this medical visit")
    appointment_id = fields.Many2one('pet.appointment', string='Appointment', help="Related appointment")
    date = fields.Datetime(required=True, default=fields.Datetime.now, tracking=True, help="Date and time of the medical visit")
    reason = fields.Char(required=True, tracking=True, help="Primary reason for the visit")
    visit_type = fields.Selection([
        ('checkup', 'Routine Checkup'), ('emergency', 'Emergency'), ('vaccination', 'Vaccination'),
        ('surgery', 'Surgery'), ('dental', 'Dental'), ('grooming', 'Grooming'), ('other', 'Other')
    ], string='Visit Type', default='checkup', help="Type of medical visit")
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
    vet_id = fields.Many2one(
        'res.partner',
        domain=lambda self: [('id', '=', self.env.user.partner_id.id)] if self.env.user.has_group('pet_management.group_pet_staff_health') else [],
        help="Veterinarian who performed the visit"
    )
    vet_notes = fields.Text(help="Additional notes from the veterinarian")
    
    # Financial
    cost = fields.Float(help="Cost of the medical visit")
    payment_status = fields.Selection([
        ('pending', 'Pending'), ('paid', 'Paid'), ('partial', 'Partial'), ('cancelled', 'Cancelled')
    ], string='Payment Status', default='pending', help="Payment status for the visit")
    
    # Computed Fields
    days_since_visit = fields.Integer(compute='_compute_days_since_visit', store=False, help="Days since the visit")
    is_overdue = fields.Boolean(compute='_compute_is_overdue', search='_search_is_overdue', store=False, help="Whether follow-up is overdue")
    state_color = fields.Integer(compute='_compute_state_color', string='State Color', store=True, help="Color index for status display")
    
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, help="Company this visit belongs to")

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

    def name_get(self):
        """Custom name_get to show pet name and reason in Many2one selection"""
        result = []
        for rec in self:
            name = f"{rec.pet_id.name if rec.pet_id else 'Unknown Pet'} - {rec.reason or 'No Reason'}"
            result.append((rec.id, name))
        return result
