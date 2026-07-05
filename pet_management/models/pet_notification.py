from datetime import timedelta
from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class PetNotification(models.Model):
    _name = 'pet.notification'
    _description = 'Pet Notification'
    _table = 'pet_notification'
    _order = 'date_sent desc, priority desc'

    name = fields.Char(string="Subject", required=True, 
                      help="Notification subject line")
    pet_id = fields.Many2one('pet.pet', string="Pet", required=True, ondelete='cascade',
                            help="Pet this notification is about")
    owner_id = fields.Many2one('res.partner', string="Owner", related='pet_id.owner_id', 
                              store=True, help="Pet owner to notify")
    notification_type = fields.Selection([
        ('vaccination_due', 'Vaccination Due'),
        ('vaccination_overdue', 'Vaccination Overdue'),
        ('appointment_reminder', 'Appointment Reminder'),
        ('medical_visit_due', 'Medical Visit Due'),
        ('boarding_reminder', 'Boarding Reminder'),
        ('grooming_reminder', 'Grooming Reminder'),
        ('training_reminder', 'Training Reminder'),
        ('general', 'General Reminder')
    ], string="Type", required=True, help="Type of notification")
    
    message = fields.Text(string="Message", required=True, 
                         help="Detailed notification message")
    priority = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent')
    ], string="Priority", default='medium', required=True,
    help="Notification priority level")
    
    status = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled')
    ], string="Status", default='draft', required=True,
    help="Current status of the notification")
    
    date_created = fields.Datetime(string="Date Created", default=fields.Datetime.now, 
                                  help="When the notification was created")
    date_sent = fields.Datetime(string="Date Sent", help="When the notification was sent")
    date_scheduled = fields.Datetime(string="Date Scheduled", help="When the notification is scheduled to be sent")
    
    # Related record references
    related_vaccination_id = fields.Many2one('pet.vaccination', string="Related Vaccination",
                                           help="Related vaccination record")
    related_appointment_id = fields.Many2one('pet.appointment', string="Related Appointment",
                                           help="Related appointment record")
    related_medical_visit_id = fields.Many2one('pet.medical.visit', string="Related Medical Visit",
                                             help="Related medical visit record")
    
    # Notification settings
    send_email = fields.Boolean(string="Send Email", default=True, 
                               help="Send notification via email")
    send_sms = fields.Boolean(string="Send SMS", default=False, 
                             help="Send notification via SMS")
    send_in_app = fields.Boolean(string="Send In App", default=True, 
                                help="Show notification in app")
    
    # Notification control
    is_enabled = fields.Boolean(string="Is Enabled", default=True, 
                               help="Enable this notification")
    auto_send = fields.Boolean(string="Auto Send", default=True, 
                              help="Automatically send when scheduled")
    retry_count = fields.Integer(string="Retry Count", default=0, 
                                help="Number of retry attempts")
    max_retries = fields.Integer(string="Max Retries", default=3, 
                                help="Maximum retry attempts")
    last_retry_date = fields.Datetime(string="Last Retry Date", help="Last retry attempt date")
    
    # Notification preferences
    preferred_time = fields.Selection([
        ('morning', 'Morning (8:00 AM)'),
        ('afternoon', 'Afternoon (2:00 PM)'),
        ('evening', 'Evening (6:00 PM)'),
        ('custom', 'Custom Time')
    ], string="Preferred Time", default='morning', help="Preferred time for sending notifications")
    
    custom_time = fields.Float(string="Custom Time", digits=(2, 2), 
                              help="Custom time in 24-hour format (e.g., 14.30 for 2:30 PM)")
    
    # Delivery tracking
    delivery_status = fields.Selection([
        ('pending', 'Pending'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed'),
        ('bounced', 'Bounced'),
        ('unsubscribed', 'Unsubscribed')
    ], string="Delivery Status", default='pending', help="Delivery status of the notification")
    
    delivery_notes = fields.Text(string="Delivery Notes", help="Notes about delivery status")
    
    # Computed fields
    days_until_due = fields.Integer(string="Days Until Due", compute='_compute_days_until_due',
                                  help="Days until the related event is due")
    is_overdue = fields.Boolean(string="Is Overdue", compute='_compute_is_overdue', search='_search_is_overdue',
                               help="True if the related event is overdue")
    color = fields.Integer(string="Color", compute='_compute_color', 
                          help="Color for kanban view")

    @api.depends('date_scheduled', 'related_vaccination_id.next_due_date', 
                 'related_appointment_id.start_datetime')
    def _compute_days_until_due(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.related_vaccination_id and rec.related_vaccination_id.next_due_date:
                rec.days_until_due = (rec.related_vaccination_id.next_due_date - today).days
            elif rec.related_appointment_id and rec.related_appointment_id.start_datetime:
                appointment_date = rec.related_appointment_id.start_datetime.date()
                rec.days_until_due = (appointment_date - today).days
            else:
                rec.days_until_due = 0

    @api.depends('days_until_due')
    def _compute_is_overdue(self):
        for rec in self:
            rec.is_overdue = rec.days_until_due < 0

    def _search_is_overdue(self, operator, value):
        """Search method for is_overdue field"""
        today = fields.Date.context_today(self)
        if operator == '=' and value:
            # Find overdue notifications
            return [
                '|',
                '&', ('related_vaccination_id', '!=', False), 
                     ('related_vaccination_id.next_due_date', '<', today),
                '&', ('related_appointment_id', '!=', False), 
                     ('related_appointment_id.start_datetime', '<', today)
            ]
        elif operator == '=' and not value:
            # Find not overdue notifications
            return [
                '|',
                '&', ('related_vaccination_id', '!=', False), 
                     ('related_vaccination_id.next_due_date', '>=', today),
                '&', ('related_appointment_id', '!=', False), 
                     ('related_appointment_id.start_datetime', '>=', today)
            ]
        return []

    @api.depends('priority', 'status', 'is_overdue')
    def _compute_color(self):
        for rec in self:
            if rec.status == 'failed':
                rec.color = 1  # red
            elif rec.is_overdue:
                rec.color = 2  # orange
            elif rec.priority == 'urgent':
                rec.color = 3  # yellow
            elif rec.priority == 'high':
                rec.color = 4  # blue
            elif rec.status == 'sent':
                rec.color = 5  # green
            else:
                rec.color = 0  # default

    def generate_dynamic_message(self):
        """Generate dynamic message content based on notification type and related data"""
        for rec in self:
            if rec.notification_type == 'vaccination_due' and rec.related_vaccination_id:
                vaccination = rec.related_vaccination_id
                days_until = rec.days_until_due
                urgency = "urgent" if days_until <= 1 else "soon" if days_until <= 3 else "upcoming"
                
                rec.message = f"""
                {rec.pet_id.name}'s {vaccination.vaccine_id.name} vaccination is {urgency}.
                
                📅 Due Date: {vaccination.next_due_date}
                🏥 Veterinarian: {vaccination.vet_id.name if vaccination.vet_id else 'TBD'}
                💉 Vaccine Type: {vaccination.vaccination_type.title()}
                
                Please schedule an appointment to keep your pet healthy and protected.
                """
                
            elif rec.notification_type == 'vaccination_overdue' and rec.related_vaccination_id:
                vaccination = rec.related_vaccination_id
                overdue_days = abs(rec.days_until_due)
                
                rec.message = f"""
                ⚠️ URGENT: {rec.pet_id.name}'s vaccination is {overdue_days} days overdue!
                
                🚨 This is critical for your pet's health and legal compliance.
                📅 Overdue since: {vaccination.next_due_date}
                💉 Required: {vaccination.vaccine_id.name}
                
                Please contact us immediately to schedule this appointment.
                """
                
            elif rec.notification_type == 'appointment_reminder' and rec.related_appointment_id:
                appointment = rec.related_appointment_id
                
                rec.message = f"""
                📅 Appointment Reminder for {rec.pet_id.name}
                
                🕐 Time: {appointment.start_datetime}
                🏥 Veterinarian: {appointment.vet_id.name if appointment.vet_id else 'TBD'}
                📝 Purpose: {appointment.purpose or 'General Checkup'}
                
                Please arrive 10 minutes early. Call us if you need to reschedule.
                """
                
            elif rec.notification_type == 'medical_visit_due' and rec.related_medical_visit_id:
                visit = rec.related_medical_visit_id
                
                rec.message = f"""
                🏥 Medical Follow-up Required for {rec.pet_id.name}
                
                📋 Visit Type: {visit.visit_type.title() if visit.visit_type else 'General'}
                🩺 Last Visit: {visit.date}
                👨‍⚕️ Veterinarian: {visit.vet_id.name if visit.vet_id else 'TBD'}
                
                A follow-up appointment is recommended within the next week.
                """

    # Notification control methods
    def action_enable_notification(self):
        """Enable the notification"""
        for rec in self:
            rec.is_enabled = True
            rec.status = 'draft'
    
    def action_disable_notification(self):
        """Disable the notification"""
        for rec in self:
            rec.is_enabled = False
            if rec.status == 'draft':
                rec.status = 'cancelled'
    
    def action_toggle_enabled(self):
        """Toggle notification enabled status"""
        for rec in self:
            rec.is_enabled = not rec.is_enabled
            if not rec.is_enabled and rec.status == 'draft':
                rec.status = 'cancelled'
            elif rec.is_enabled and rec.status == 'cancelled':
                rec.status = 'draft'
    
    def action_retry_notification(self):
        """Retry sending the notification"""
        for rec in self:
            if rec.retry_count < rec.max_retries:
                rec.retry_count += 1
                rec.last_retry_date = fields.Datetime.now()
                rec.status = 'draft'
                rec.action_send_notification()
            else:
                rec.status = 'failed'
                rec.delivery_status = 'failed'
                rec.delivery_notes = f'Max retries ({rec.max_retries}) exceeded'
    
    def action_reset_retry_count(self):
        """Reset retry count for failed notifications"""
        for rec in self:
            rec.retry_count = 0
            rec.last_retry_date = False
            rec.status = 'draft'
            rec.delivery_status = 'pending'
            rec.delivery_notes = ''

    # Action methods
    def action_send_notification(self):
        """Send the notification via configured channels"""
        for rec in self:
            if rec.status != 'draft' or not rec.is_enabled:
                continue
                
            try:
                # Send email if enabled
                if rec.send_email and rec.owner_id.email:
                    rec._send_email_notification()
                
                # Send SMS if enabled (placeholder for future implementation)
                if rec.send_sms and rec.owner_id.mobile:
                    rec._send_sms_notification()
                
                # Mark as sent
                rec.status = 'sent'
                rec.date_sent = fields.Datetime.now()
                rec.delivery_status = 'delivered'
                
            except Exception as e:
                rec.status = 'failed'
                raise UserError(f"Failed to send notification: {str(e)}")

    def _send_email_notification(self):
        """Send email notification to pet owner"""
        template = self.env.ref('pet_management.email_template_pet_notification', False)
        if template:
            template.send_mail(self.id, force_send=True)
        else:
            # Fallback: send simple email
            mail_values = {
                'subject': self.name,
                'body_html': f'<p>{self.message}</p>',
                'email_to': self.owner_id.email,
                'email_from': self.env.user.email,
            }
            self.env['mail.mail'].create(mail_values).send()

    def _send_sms_notification(self):
        """Send SMS notification (placeholder for future implementation)"""
        # This would integrate with an SMS service provider
        pass

    def action_mark_sent(self):
        """Manually mark notification as sent"""
        for rec in self:
            rec.status = 'sent'
            rec.date_sent = fields.Datetime.now()

    def action_cancel(self):
        """Cancel the notification"""
        for rec in self:
            rec.status = 'cancelled'

    def action_retry(self):
        """Retry sending a failed notification"""
        for rec in self:
            if rec.status == 'failed':
                rec.status = 'draft'
                rec.action_send_notification()

    def action_view_pet(self):
        """View the related pet record"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Pet',
            'res_model': 'pet.pet',
            'res_id': self.pet_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_owner(self):
        """View the pet owner record"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Pet Owner',
            'res_model': 'res.partner',
            'res_id': self.owner_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to apply notification settings"""
        # Get notification settings
        icp = self.env['ir.config_parameter'].sudo()
        enable_email = icp.get_param('pet_management.enable_email_notifications') in (True, 'True', '1', 1)
        enable_sms = icp.get_param('pet_management.enable_sms_notifications') in (True, 'True', '1', 1)
        
        for vals in vals_list:
            # Set notification methods based on settings
            if 'send_email' not in vals:
                vals['send_email'] = enable_email
            if 'send_sms' not in vals:
                vals['send_sms'] = enable_sms
            if 'send_in_app' not in vals:
                vals['send_in_app'] = True  # Always show in-app notifications
                    
        return super().create(vals_list)

    @api.model
    def create_vaccination_reminders(self):
        """Create vaccination reminder notifications"""
        # Find vaccinations due in the next 7 days
        today = fields.Date.context_today(self)
        next_week = today + timedelta(days=7)
        
        due_vaccinations = self.env['pet.vaccination'].search([
            ('next_due_date', '>=', today),
            ('next_due_date', '<=', next_week),
            ('state', 'in', ['scheduled', 'administered'])
        ])
        
        for vaccination in due_vaccinations:
            # Check if notification already exists
            existing = self.search([
                ('related_vaccination_id', '=', vaccination.id),
                ('notification_type', '=', 'vaccination_due'),
                ('status', 'in', ['draft', 'sent'])
            ])
            
            if not existing:
                self.create({
                    'name': f'Vaccination Due: {vaccination.pet_id.name}',
                    'pet_id': vaccination.pet_id.id,
                    'notification_type': 'vaccination_due',
                    'message': f'Your pet {vaccination.pet_id.name} is due for {vaccination.vaccine_id.name} vaccination on {vaccination.next_due_date}. Please schedule an appointment.',
                    'priority': 'high' if (vaccination.next_due_date - today).days <= 3 else 'medium',
                    'related_vaccination_id': vaccination.id,
                    'date_scheduled': fields.Datetime.now(),
                    'is_enabled': True,
                    'auto_send': True,
                })

    @api.model
    def create_overdue_notifications(self):
        """Create overdue vaccination notifications"""
        today = fields.Date.context_today(self)
        
        overdue_vaccinations = self.env['pet.vaccination'].search([
            ('next_due_date', '<', today),
            ('state', 'in', ['scheduled', 'administered'])
        ])
        
        for vaccination in overdue_vaccinations:
            # Check if notification already exists
            existing = self.search([
                ('related_vaccination_id', '=', vaccination.id),
                ('notification_type', '=', 'vaccination_overdue'),
                ('status', 'in', ['draft', 'sent'])
            ])
            
            if not existing:
                overdue_days = (today - vaccination.next_due_date).days
                self.create({
                    'name': f'URGENT: Overdue Vaccination - {vaccination.pet_id.name}',
                    'pet_id': vaccination.pet_id.id,
                    'notification_type': 'vaccination_overdue',
                    'message': f'URGENT: Your pet {vaccination.pet_id.name} is {overdue_days} days overdue for {vaccination.vaccine_id.name} vaccination. Please contact us immediately.',
                    'priority': 'urgent',
                    'related_vaccination_id': vaccination.id,
                    'date_scheduled': fields.Datetime.now(),
                    'is_enabled': True,
                    'auto_send': True,
                })

    @api.model
    def create_appointment_reminders(self):
        """Create appointment reminder notifications"""
        # Find appointments in the next 24 hours
        now = fields.Datetime.now()
        tomorrow = now + timedelta(days=1)
        
        upcoming_appointments = self.env['pet.appointment'].search([
            ('start_datetime', '>=', now),
            ('start_datetime', '<=', tomorrow),
            ('state', 'in', ['confirmed', 'draft'])
        ])
        
        for appointment in upcoming_appointments:
            # Check if notification already exists
            existing = self.search([
                ('related_appointment_id', '=', appointment.id),
                ('notification_type', '=', 'appointment_reminder'),
                ('status', 'in', ['draft', 'sent'])
            ])
            
            if not existing:
                self.create({
                    'name': f'Appointment Reminder: {appointment.pet_id.name}',
                    'pet_id': appointment.pet_id.id,
                    'notification_type': 'appointment_reminder',
                    'message': f'Reminder: You have an appointment for {appointment.pet_id.name} on {appointment.start_datetime.strftime("%B %d, %Y at %I:%M %p")}.',
                    'priority': 'medium',
                    'related_appointment_id': appointment.id,
                    'date_scheduled': fields.Datetime.now(),
                    'is_enabled': True,
                    'auto_send': True,
                })

    @api.model
    def send_scheduled_notifications(self):
        """Send all scheduled notifications that are ready to be sent"""
        now = fields.Datetime.now()
        
        # Find notifications that are scheduled to be sent now or earlier
        scheduled_notifications = self.search([
            ('status', '=', 'draft'),
            ('is_enabled', '=', True),
            ('auto_send', '=', True),
            ('date_scheduled', '<=', now)
        ])
        
        for notification in scheduled_notifications:
            try:
                notification.action_send_notification()
            except Exception as e:
                # Log error but continue with other notifications
                _logger.error(f"Failed to send notification {notification.id}: {str(e)}")
                notification.status = 'failed'
