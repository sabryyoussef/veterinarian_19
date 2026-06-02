from odoo import models, fields, api, _ # type
from odoo.exceptions import ValidationError

# Check if calendar module is installed
try:
    # This will work if calendar module is installed
    from odoo.addons.calendar.models.calendar_event import CalendarEvent
    CALENDAR_INSTALLED = True
except ImportError:
    CALENDAR_INSTALLED = False

class PetAppointment(models.Model):
    _name = 'pet.appointment'
    _description = 'Pet Appointment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_datetime desc'

    pet_id = fields.Many2one('pet.pet', required=True, ondelete='cascade', tracking=True, help="The pet for this appointment")
    owner_id = fields.Many2one(related='pet_id.owner_id', store=True, readonly=True, help="Pet owner")
    # Appointment Categories (can select multiple)
    is_medical = fields.Boolean(string='Medical', default=False, help="Include medical services")
    is_vaccination = fields.Boolean(string='Include Vaccination', default=False, help="Include vaccination services")
    is_grooming = fields.Boolean(string='Grooming', default=False, help="Include grooming services")
    is_training = fields.Boolean(string='Training', default=False, help="Include training services")
    is_boarding = fields.Boolean(string='Boarding', default=False, help="Include boarding services")
    
    # Primary appointment type for categorization
    primary_type = fields.Selection([
        ('checkup', 'Routine Checkup'), ('emergency', 'Emergency'), ('surgery', 'Surgery'), 
        ('dental', 'Dental'), ('comprehensive', 'Comprehensive Care'), ('other', 'Other')
    ], required=True, tracking=True, help="Primary type of appointment")
    name = fields.Char(string='Reference', readonly=True, copy=False, default=lambda s: _('New'), help="Appointment reference")
    title = fields.Char(required=True, tracking=True, help="Appointment title")
    start_datetime = fields.Datetime(required=True, index=True, tracking=True, help="Appointment start time")
    end_datetime = fields.Datetime(required=True, index=True, tracking=True, help="Appointment end time")
    resource_id = fields.Many2one(
        'res.partner',
        domain=lambda self: [('id', '=', self.env.user.partner_id.id)] if self.env.user.has_group('pet_management.group_pet_staff_appointments') else [],
        help="Veterinarian or staff member"
    )
    room_id = fields.Many2one('pet.kennel', string='Room', help="Room or kennel for the appointment")
    notes = fields.Text(help="Additional notes about the appointment")
    state = fields.Selection([
        ('draft','Draft'), ('confirmed','Confirmed'), ('in_progress','In Progress'), 
        ('done','Done'), ('cancelled','Cancelled'), ('rescheduled','Rescheduled')
    ], default='draft', index=True, tracking=True, help="Current status of the appointment")
    
    # Enhanced Fields
    duration_minutes = fields.Float(compute='_compute_duration', store=True, help="Duration in minutes")
    duration_display = fields.Char(compute='_compute_duration', store=True, help="Duration in readable format")
    cost = fields.Float(compute='_compute_cost', store=True, help="Automatically calculated cost from connected facility")
    payment_status = fields.Selection([
        ('pending', 'Pending'), ('paid', 'Paid'), ('partial', 'Partial'), ('cancelled', 'Cancelled')
    ], string='Payment Status', default='pending', help="Payment status for the appointment")
    follow_up_date = fields.Date(help="Recommended follow-up date")
    follow_up_notes = fields.Text(help="Follow-up instructions")
    
    # Calendar Integration Fields (only if calendar module is installed)
    sync_to_calendar = fields.Boolean(default=True, help="Sync this appointment to calendar")
    enable_calendar_integration = fields.Boolean(compute='_compute_enable_calendar_integration', help="Whether calendar integration is enabled")
    has_calendar_event = fields.Boolean(compute='_compute_has_calendar_event', help="Whether a calendar event is linked")
    
    # Inventory Integration Fields (only if stock module is installed)
    inventory_items_ids = fields.One2many('pet.appointment.inventory', 'appointment_id', string='Inventory Items', help="Items used during appointment")
    inventory_cost = fields.Float(compute='_compute_inventory_cost', store=True, help="Total cost of inventory items used")
    
    # Service Selection Fields (for specific service types)
    service_id = fields.Many2one('pet.grooming.service', string='Grooming Service', help="Selected grooming service")
    program_id = fields.Many2one('pet.training.program', string='Training Program', help="Selected training program")
    vaccine_id = fields.Many2one('pet.vaccine', string='Vaccine', help="Selected vaccine")
    kennel_id = fields.Many2one('pet.kennel', string='Boarding Facility', help="Selected boarding facility")
    
    # Facility Connection Fields (for created facility entries)
    medical_visit_id = fields.Many2one('pet.medical.visit', string='Medical Visit', help="Connected medical visit")
    vaccination_id = fields.Many2one('pet.vaccination', string='Vaccination', help="Connected vaccination")
    grooming_session_id = fields.Many2one('pet.grooming.session', string='Grooming Session', help="Connected grooming session")
    training_session_id = fields.Many2one('pet.training.session', string='Training Session', help="Connected training session")
    boarding_stay_id = fields.Many2one('pet.boarding.stay', string='Boarding Stay', help="Connected boarding stay")
    
    # Auto-creation flags
    auto_create_facility = fields.Boolean(default=True, help="Automatically create facility entry when appointment is confirmed")
    
    # Computed Fields
    days_since_appointment = fields.Integer(compute='_compute_days_since_appointment', store=False, help="Days since the appointment")
    is_overdue = fields.Boolean(compute='_compute_is_overdue', search='_search_is_overdue', store=False, help="Whether appointment is overdue")
    is_today = fields.Boolean(compute='_compute_is_today', store=False, help="Whether appointment is today")
    state_color = fields.Integer(compute='_compute_state_color', string='State Color', store=True, help="Color index for status display")
    
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, help="Company this appointment belongs to")
    
    # Invoice Related Fields
    invoice_id = fields.Many2one('account.move', string='Invoice', readonly=True, help="Generated invoice for this appointment")
    invoice_state = fields.Selection([
        ('no_invoice', 'No Invoice'),
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancelled', 'Cancelled')
    ], string='Invoice Status', compute='_compute_invoice_state', store=True, help="Status of the generated invoice")
    invoice_amount = fields.Monetary(related='invoice_id.amount_total', string='Invoice Amount', readonly=True, help="Total amount of the invoice")
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', readonly=True, help="Currency")
    
    # Service Status Fields (to track completion status)
    medical_visit_status = fields.Selection(related='medical_visit_id.status', string='Medical Status', readonly=True, help="Status of medical visit")
    vaccination_status = fields.Selection(related='vaccination_id.state', string='Vaccination Status', readonly=True, help="Status of vaccination")
    grooming_session_status = fields.Selection(related='grooming_session_id.state', string='Grooming Status', readonly=True, help="Status of grooming session")
    training_session_status = fields.Selection(related='training_session_id.state', string='Training Status', readonly=True, help="Status of training session")
    boarding_stay_status = fields.Selection(related='boarding_stay_id.state', string='Boarding Status', readonly=True, help="Status of boarding stay")
    
    # Computed cost fields for table display
    medical_visit_cost = fields.Float(related='medical_visit_id.cost', string='Medical Cost', readonly=True, help="Cost of medical visit")
    vaccination_cost = fields.Monetary(related='vaccination_id.cost', string='Vaccination Cost', readonly=True, help="Cost of vaccination")
    vaccine_cost = fields.Float(related='vaccine_id.cost', string='Vaccine Cost', readonly=True, help="Cost of vaccine")
    grooming_session_cost = fields.Float(related='grooming_session_id.total_cost', string='Grooming Session Cost', readonly=True, help="Cost of grooming session")
    grooming_service_cost = fields.Float(related='service_id.base_price', string='Grooming Service Cost', readonly=True, help="Cost of grooming service")
    training_session_cost = fields.Monetary(related='training_session_id.session_cost', string='Training Session Cost', readonly=True, help="Cost of training session")
    training_program_cost = fields.Monetary(related='program_id.base_price', string='Training Program Cost', readonly=True, help="Cost of training program")
    boarding_stay_cost = fields.Float(related='boarding_stay_id.total_cost', string='Boarding Stay Cost', readonly=True, help="Cost of boarding stay")

    @api.depends('invoice_id', 'invoice_id.state')
    def _compute_invoice_state(self):
        """Compute invoice state based on the actual invoice state"""
        for rec in self:
            if rec.invoice_id:
                # Map Odoo invoice states to our custom states
                state_mapping = {
                    'draft': 'draft',
                    'posted': 'posted',
                    'cancel': 'cancelled'
                }
                rec.invoice_state = state_mapping.get(rec.invoice_id.state, 'draft')
            else:
                rec.invoice_state = 'no_invoice'

    @api.depends('start_datetime', 'end_datetime')
    def _compute_duration(self):
        for rec in self:
            if rec.start_datetime and rec.end_datetime:
                delta = rec.end_datetime - rec.start_datetime
                rec.duration_minutes = delta.total_seconds() / 60.0
                hours = int(delta.total_seconds() // 3600)
                minutes = int((delta.total_seconds() % 3600) // 60)
                if hours > 0:
                    rec.duration_display = f"{hours}h {minutes}m" if minutes > 0 else f"{hours}h"
                else:
                    rec.duration_display = f"{minutes}m"
            else:
                rec.duration_minutes = 0.0
                rec.duration_display = "0m"

    @api.depends('start_datetime')
    def _compute_days_since_appointment(self):
        today = fields.Date.today()
        for rec in self:
            if rec.start_datetime:
                appointment_date = rec.start_datetime.date()
                rec.days_since_appointment = (today - appointment_date).days
            else:
                rec.days_since_appointment = 0

    @api.depends('start_datetime', 'state')
    def _compute_is_overdue(self):
        today = fields.Datetime.now()
        for rec in self:
            rec.is_overdue = (
                rec.start_datetime and 
                rec.start_datetime < today and 
                rec.state in ['draft', 'confirmed']
            )

    @api.depends('start_datetime')
    def _compute_is_today(self):
        today = fields.Date.today()
        for rec in self:
            if rec.start_datetime:
                rec.is_today = rec.start_datetime.date() == today
            else:
                rec.is_today = False

    @api.depends('state')
    def _compute_state_color(self):
        color_map = {
            'draft': 1,        # blue
            'confirmed': 2,    # orange
            'in_progress': 3,  # green
            'done': 4,         # green
            'cancelled': 0,    # grey
            'rescheduled': 5,  # purple
        }
        for rec in self:
            rec.state_color = color_map.get(rec.state, 1)

    @api.depends('medical_visit_id.cost', 'vaccination_id.cost', 'grooming_session_id.total_cost', 
                 'training_session_id.session_cost', 'boarding_stay_id.total_cost', 'vaccine_id.cost', 'service_id.base_price', 'program_id.base_price',
                 'medical_visit_id.status', 'vaccination_id.state', 'grooming_session_id.state', 'training_session_id.state', 'boarding_stay_id.state')
    def _compute_cost(self):
        for rec in self:
            cost = 0.0
            # Add costs only from completed/done services
            
            # Medical Visit - only count if completed
            if rec.medical_visit_id and rec.medical_visit_id.status == 'completed':
                cost += rec.medical_visit_id.cost or 0.0
            
            # Vaccination - only count if administered
            if rec.vaccination_id and rec.vaccination_id.state == 'administered':
                cost += rec.vaccination_id.cost or 0.0
            
            # Vaccine - always count (no status field, assume completed when selected)
            if rec.vaccine_id:
                cost += rec.vaccine_id.cost or 0.0
            
            # Grooming Session - only count if completed
            if rec.grooming_session_id and rec.grooming_session_id.state == 'completed':
                cost += rec.grooming_session_id.total_cost or 0.0
            elif rec.service_id and rec.grooming_session_id and rec.grooming_session_id.state == 'completed':
                # If grooming session is completed, also add base service price
                cost += rec.service_id.base_price or 0.0
            
            # Training Session - only count if completed
            if rec.training_session_id and rec.training_session_id.state == 'completed':
                cost += rec.training_session_id.session_cost or 0.0
            elif rec.program_id and rec.training_session_id and rec.training_session_id.state == 'completed':
                # If training session is completed, also add base program price
                cost += rec.program_id.base_price or 0.0
            
            # Boarding Stay - only count if checked out (completed)
            if rec.boarding_stay_id and rec.boarding_stay_id.state == 'checked_out':
                cost += rec.boarding_stay_id.total_cost or 0.0
                
            rec.cost = cost

    @api.depends('inventory_items_ids', 'inventory_items_ids.total_cost')
    def _compute_inventory_cost(self):
        """Compute total inventory cost for this appointment"""
        for rec in self:
            rec.inventory_cost = sum(rec.inventory_items_ids.mapped('total_cost'))

    def _compute_enable_calendar_integration(self):
        """Compute whether calendar integration is enabled"""
        for rec in self:
            rec.enable_calendar_integration = rec._is_calendar_module_installed()

    def _compute_has_calendar_event(self):
        """Compute whether a calendar event exists (safe even if module missing)"""
        for rec in self:
            # Truthy if there is an id set; Unknown records are fine to test for truthiness
            if CALENDAR_INSTALLED:
                rec.has_calendar_event = bool(rec.calendar_event_id)
            else:
                rec.has_calendar_event = False

    @api.constrains('start_datetime', 'end_datetime')
    def _check_range(self):
        for rec in self:
            if rec.start_datetime and rec.end_datetime and rec.end_datetime <= rec.start_datetime:
                raise ValidationError('End must be after Start.')

    @api.constrains("resource_id", "room_id", "start_datetime", "end_datetime")
    def _check_overlap(self):
        for rec in self:
            # Check resource overlap
            if rec.resource_id:
                resource_overlap = self.search([
                    ("id", "!=", rec.id),
                    ("resource_id", "=", rec.resource_id.id),
                    ("start_datetime", "<=", rec.end_datetime),
                    ("end_datetime", ">=", rec.start_datetime),
                    ("state", "not in", ["cancelled"])
                ], limit=1)
                if resource_overlap:
                    raise ValidationError(f"Resource {rec.resource_id.name} is already booked during this time period.")
            
            # Check room overlap
            if rec.room_id:
                room_overlap = self.search([
                    ("id", "!=", rec.id),
                    ("room_id", "=", rec.room_id.id),
                    ("start_datetime", "<=", rec.end_datetime),
                    ("end_datetime", ">=", rec.start_datetime),
                    ("state", "not in", ["cancelled"])
                ], limit=1)
                if room_overlap:
                    raise ValidationError(f"Room {rec.room_id.name} is already booked during this time period.")

    def _search_is_overdue(self, operator, value):
        """Search method for is_overdue field"""
        now = fields.Datetime.now()
        if operator == '=' and value:
            return [
                ('start_datetime', '<', now),
                ('state', 'in', ['draft', 'confirmed'])
            ]
        elif operator == '=' and not value:
            return [
                '|',
                ('start_datetime', '=', False),
                '|',
                ('start_datetime', '>=', now),
                ('state', 'not in', ['draft', 'confirmed'])
            ]
        return []

    def set_to_confirmed(self):
        for rec in self:
            rec.state = 'confirmed'

    def set_to_in_progress(self):
        for rec in self:
            rec.state = 'in_progress'

    def set_to_done(self):
        for rec in self:
            rec.state = 'done'

    def set_to_cancel(self):
        for rec in self:
            rec.state = 'cancelled'

    def set_to_reschedule(self):
        for rec in self:
            rec.state = 'rescheduled'

    def action_send_notification(self):
        """Create and send notification for this appointment"""
        for rec in self:
            # Determine notification type and priority based on appointment state and timing
            now = fields.Datetime.now()
            time_diff = (rec.start_datetime - now).total_seconds() / 3600  # hours
            
            if rec.state == 'draft':
                notification_type = 'appointment_reminder'
                priority = 'medium'
                message = f"Appointment scheduled: {rec.pet_id.name} has a {rec.type} appointment on {rec.start_datetime.strftime('%B %d, %Y at %I:%M %p')}."
            elif rec.state == 'confirmed':
                if time_diff <= 24:  # Within 24 hours
                    notification_type = 'appointment_reminder'
                    priority = 'high'
                    message = f"REMINDER: {rec.pet_id.name}'s {rec.type} appointment is tomorrow at {rec.start_datetime.strftime('%I:%M %p')}. Please arrive 10 minutes early."
                else:
                    notification_type = 'appointment_reminder'
                    priority = 'medium'
                    message = f"Confirmed: {rec.pet_id.name}'s {rec.type} appointment is scheduled for {rec.start_datetime.strftime('%B %d, %Y at %I:%M %p')}."
            elif rec.state == 'in_progress':
                notification_type = 'general'
                priority = 'medium'
                message = f"In Progress: {rec.pet_id.name}'s {rec.type} appointment is currently in progress with {rec.resource_id.name if rec.resource_id else 'staff'}."
            elif rec.state == 'done':
                notification_type = 'general'
                priority = 'low'
                message = f"Completed: {rec.pet_id.name}'s {rec.type} appointment was completed on {rec.start_datetime.strftime('%B %d, %Y')}. Follow-up: {rec.follow_up_date.strftime('%B %d, %Y') if rec.follow_up_date else 'Not required'}."
            elif rec.state == 'cancelled':
                notification_type = 'general'
                priority = 'low'
                message = f"Cancelled: {rec.pet_id.name}'s {rec.type} appointment scheduled for {rec.start_datetime.strftime('%B %d, %Y at %I:%M %p')} has been cancelled."
            elif rec.state == 'rescheduled':
                notification_type = 'general'
                priority = 'medium'
                message = f"Rescheduled: {rec.pet_id.name}'s {rec.type} appointment has been rescheduled. New time: {rec.start_datetime.strftime('%B %d, %Y at %I:%M %p')}."
            else:
                notification_type = 'general'
                priority = 'low'
                message = f"Update: {rec.pet_id.name}'s {rec.type} appointment status is {rec.state}."
            
            # Create notification
            notification = self.env['pet.notification'].sudo().create({
                'name': f'Appointment Notification - {rec.pet_id.name}',
                'pet_id': rec.pet_id.id,
                'notification_type': notification_type,
                'message': message,
                'priority': priority,
                'status': 'draft',
                'related_appointment_id': rec.id,
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

    def action_create_reminder_notification(self):
        """Create a reminder notification for this appointment"""
        for rec in self:
            if rec.state not in ['draft', 'confirmed']:
                continue
                
            # Check if reminder already exists
            existing = self.env['pet.notification'].search([
                ('related_appointment_id', '=', rec.id),
                ('notification_type', '=', 'appointment_reminder'),
                ('status', 'in', ['draft', 'sent'])
            ])
            
            if not existing:
                notification = self.env['pet.notification'].sudo().create({
                    'name': f'Appointment Reminder - {rec.pet_id.name}',
                    'pet_id': rec.pet_id.id,
                    'notification_type': 'appointment_reminder',
                    'message': f"Reminder: {rec.pet_id.name}'s {rec.type} appointment is scheduled for {rec.start_datetime.strftime('%B %d, %Y at %I:%M %p')}. Please arrive 10 minutes early.",
                    'priority': 'high' if (rec.start_datetime - fields.Datetime.now()).total_seconds() <= 86400 else 'medium',  # 24 hours
                    'status': 'draft',
                    'related_appointment_id': rec.id,
                    'date_scheduled': fields.Datetime.now(),
                    'is_enabled': True,
                    'auto_send': True,
                    'preferred_time': 'morning',
                    'send_email': True,
                    'send_in_app': True,
                })
                
                return {
                    'type': 'ir.actions.act_window',
                    'name': 'Reminder Created',
                    'res_model': 'pet.notification',
                    'res_id': notification.id,
                    'view_mode': 'form',
                    'target': 'current',
                }

    def action_view_pet(self):
        """Action to view the pet record"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Pet',
            'res_model': 'pet.pet',
            'res_id': self.pet_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
    
    def action_view_medical_visit(self):
        """Open the medical visit form view"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Medical Visit',
            'res_model': 'pet.medical.visit',
            'view_mode': 'form',
            'res_id': self.medical_visit_id.id,
            'target': 'current',
        }
    
    def action_view_vaccination(self):
        """Open the vaccination form view"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Vaccination',
            'res_model': 'pet.vaccination',
            'view_mode': 'form',
            'res_id': self.vaccination_id.id,
            'target': 'current',
        }
    
    def action_view_vaccine(self):
        """Open the vaccine form view"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Vaccine',
            'res_model': 'pet.vaccine',
            'view_mode': 'form',
            'res_id': self.vaccine_id.id,
            'target': 'current',
        }
    
    def action_view_grooming_session(self):
        """Open the grooming session form view"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Grooming Session',
            'res_model': 'pet.grooming.session',
            'view_mode': 'form',
            'res_id': self.grooming_session_id.id,
            'target': 'current',
        }
    
    def action_view_grooming_service(self):
        """Open the grooming service form view"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Grooming Service',
            'res_model': 'pet.grooming.service',
            'view_mode': 'form',
            'res_id': self.service_id.id,
            'target': 'current',
        }
    
    def action_view_boarding_stay(self):
        """Open the boarding stay form view"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Boarding Stay',
            'res_model': 'pet.boarding.stay',
            'view_mode': 'form',
            'res_id': self.boarding_stay_id.id,
            'target': 'current',
        }
    
    def action_view_kennel(self):
        """Open the kennel form view"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Kennel',
            'res_model': 'pet.kennel',
            'view_mode': 'form',
            'res_id': self.kennel_id.id,
            'target': 'current',
        }
    
    def action_view_training_session(self):
        """Open the training session form view"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Training Session',
            'res_model': 'pet.training.session',
            'view_mode': 'form',
            'res_id': self.training_session_id.id,
            'target': 'current',
        }
    
    def action_view_training_program(self):
        """Open the training program form view"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Training Program',
            'res_model': 'pet.training.program',
            'view_mode': 'form',
            'res_id': self.program_id.id,
            'target': 'current',
        }

    def action_create_facility_entry(self):
        """Create facility entries based on selected service types"""
        for rec in self:
            if not rec.auto_create_facility:
                continue
                
            # Create medical visit if medical services are selected
            if rec.is_medical or rec.primary_type in ['checkup', 'emergency', 'surgery', 'dental']:
                rec._create_medical_visit()
            
            # Create vaccination if vaccination services are selected
            if rec.is_vaccination and rec.vaccine_id:
                rec._create_vaccination()
            
            # Create grooming session if grooming services are selected
            if rec.is_grooming and rec.service_id:
                rec._create_grooming_session()
            
            # Create training session if training services are selected
            if rec.is_training and rec.program_id:
                rec._create_training_session()
            
            # Create boarding stay if boarding services are selected
            if rec.is_boarding and rec.kennel_id:
                rec._create_boarding_stay()

    def action_create_medical_visit(self):
        """Manually create medical visit entry"""
        for rec in self:
            rec._create_medical_visit()

    def action_create_vaccination(self):
        """Manually create vaccination entry"""
        for rec in self:
            if rec.vaccine_id:
                rec._create_vaccination()
            else:
                raise ValidationError("Please select a vaccine before creating vaccination entry.")

    def action_create_grooming_session(self):
        """Manually create grooming session entry"""
        for rec in self:
            if rec.service_id:
                rec._create_grooming_session()
            else:
                raise ValidationError("Please select a grooming service before creating grooming session.")

    def action_create_training_session(self):
        """Manually create training session entry"""
        for rec in self:
            if rec.program_id:
                rec._create_training_session()
            else:
                raise ValidationError("Please select a training program before creating training session.")

    def action_create_boarding_stay(self):
        """Manually create boarding stay entry"""
        for rec in self:
            if rec.kennel_id:
                rec._create_boarding_stay()
            else:
                raise ValidationError("Please select a kennel before creating boarding stay.")

    def _create_medical_visit(self):
        """Create medical visit entry"""
        if not self.medical_visit_id:
            visit_vals = {
                'pet_id': self.pet_id.id,
                'date': self.start_datetime,
                'visit_type': self.primary_type,
                'reason': self.title,
                'vet_id': self.resource_id.id if self.resource_id else False,
                'plan': self.notes,
                'appointment_id': self.id,
            }
            visit = self.env['pet.medical.visit'].sudo().create(visit_vals)
            self.medical_visit_id = visit.id

    def _create_vaccination(self):
        """Create vaccination entry"""
        if not self.vaccination_id and self.vaccine_id:
            vacc_vals = {
                'pet_id': self.pet_id.id,
                'vaccine_id': self.vaccine_id.id,
                'date_administered': self.start_datetime.date(),
                'vet_id': self.resource_id.id if self.resource_id else False,
                'notes': self.notes,
                'appointment_id': self.id,
                'state': 'scheduled',
                'vaccination_type': 'initial',
            }
            vaccination = self.env['pet.vaccination'].sudo().create(vacc_vals)
            self.vaccination_id = vaccination.id

    def _create_grooming_session(self):
        """Create grooming session entry"""
        if not self.grooming_session_id and self.service_id:
            # Find a valid groomer (employee) or leave it empty
            groomer_id = False
            if self.resource_id and self.resource_id._name == 'hr.employee':
                groomer_id = self.resource_id.id
            else:
                # Try to find any available groomer
                groomer = self.env['hr.employee'].search([('active', '=', True)], limit=1)
                if groomer:
                    groomer_id = groomer.id
            
            session_vals = {
                'pet_id': self.pet_id.id,
                'service_id': self.service_id.id,
                'appointment_datetime': self.start_datetime,
                'groomer_id': groomer_id,
                'notes': self.notes,
                'appointment_id': self.id,
                'state': 'confirmed',
            }
            session = self.env['pet.grooming.session'].sudo().create(session_vals)
            self.grooming_session_id = session.id

    def _create_training_session(self):
        """Create training session entry"""
        if not self.training_session_id and self.program_id:
            # Find a valid trainer (employee) or leave it empty
            trainer_id = False
            if self.resource_id and self.resource_id._name == 'hr.employee':
                trainer_id = self.resource_id.id
            else:
                # Try to find any available trainer
                trainer = self.env['hr.employee'].search([('active', '=', True)], limit=1)
                if trainer:
                    trainer_id = trainer.id
            
            session_vals = {
                'pet_id': self.pet_id.id,
                'program_id': self.program_id.id,
                'session_datetime': self.start_datetime,
                'trainer_id': trainer_id,
                'session_notes': self.notes,
                'appointment_id': self.id,
                'state': 'confirmed',
            }
            session = self.env['pet.training.session'].sudo().create(session_vals)
            self.training_session_id = session.id

    def _create_boarding_stay(self):
        """Create boarding stay entry"""
        if not self.boarding_stay_id and self.kennel_id:
            stay_vals = {
                'pet_id': self.pet_id.id,
                'kennel_id': self.kennel_id.id,
                'check_in': self.start_datetime,
                'check_out': self.end_datetime,
                'special_instructions': self.notes,
                'appointment_id': self.id,
                'state': 'confirmed',
            }
            stay = self.env['pet.boarding.stay'].sudo().create(stay_vals)
            self.boarding_stay_id = stay.id

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to generate sequence and auto-create facility entry"""
        # Get default appointment duration from settings
        icp = self.env['ir.config_parameter'].sudo()
        default_duration = float(icp.get_param('pet_management.appointment_duration_default', 1.0))
        
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('pet.appointment') or _('New')
            
            # Apply default duration if not specified
            if 'start_datetime' in vals and 'end_datetime' not in vals:
                from datetime import datetime, timedelta
                start_dt = vals['start_datetime']
                if isinstance(start_dt, str):
                    start_dt = datetime.fromisoformat(start_dt.replace('Z', '+00:00'))
                vals['end_datetime'] = start_dt + timedelta(hours=default_duration)
                
        appointments = super().create(vals_list)
        for appointment in appointments:
            if appointment.auto_create_facility and appointment.state == 'confirmed':
                appointment.action_create_facility_entry()
            
            # Auto-sync to calendar if enabled
            if appointment.sync_to_calendar and appointment._is_calendar_module_installed():
                icp = self.env['ir.config_parameter'].sudo()
                enable_calendar = icp.get_param('pet_management.enable_calendar_integration') in (True, 'True', '1', 1)
                if enable_calendar:
                    appointment.action_sync_to_calendar()
                    
        return appointments

    def write(self, vals):
        """Override write to auto-create facility entry when confirmed and refresh invoice when needed"""
        # Clear service fields when service types are unchecked
        service_type_mappings = {
            'is_medical': ['medical_visit_id'],
            'is_vaccination': ['vaccination_id', 'vaccine_id'],
            'is_grooming': ['grooming_session_id', 'service_id'],
            'is_training': ['training_session_id', 'program_id'],
            'is_boarding': ['boarding_stay_id', 'kennel_id']
        }
        
        # Check if any service type is being unchecked
        for service_type, related_fields in service_type_mappings.items():
            if service_type in vals and not vals[service_type]:
                # Clear all related fields when service type is unchecked
                for field in related_fields:
                    if field not in vals:  # Only clear if not explicitly set
                        vals[field] = False
        
        result = super().write(vals)
        
        # Auto-create facility entry when confirmed
        if 'state' in vals and vals['state'] == 'confirmed':
            for rec in self:
                if rec.auto_create_facility:
                    rec.action_create_facility_entry()
        
        # Auto-link facility records to appointment
        facility_fields = [
            'medical_visit_id', 'vaccination_id', 'grooming_session_id', 
            'training_session_id', 'boarding_stay_id'
        ]
        
        for field in facility_fields:
            if field in vals and vals[field]:
                for rec in self:
                    facility_record = getattr(rec, field)
                    if facility_record and hasattr(facility_record, 'appointment_id'):
                        facility_record.write({'appointment_id': rec.id})
        
        return result

    def _refresh_invoice_sync(self):
        """Synchronous method to refresh invoice without UI interaction"""
        if self.invoice_id and self.invoice_state == 'draft':
            # First, recalculate appointment cost to ensure it's up to date
            self._compute_cost()
            
            # Clear existing invoice lines
            self.invoice_id.invoice_line_ids.unlink()
            
            # Recreate invoice lines with current data
            invoice_lines = self._prepare_invoice_lines()
            total_amount = 0.0
            
            for line_vals in invoice_lines:
                line_vals['move_id'] = self.invoice_id.id
                line = self.env['account.move.line'].sudo().create(line_vals)
                total_amount += line.price_subtotal
            
            # Manually update invoice amounts to avoid expensive compute methods
            self.invoice_id.write({
                'amount_untaxed': total_amount,
                'amount_total': total_amount,  # Assuming no taxes for now
            })

    def name_get(self):
        """Custom name_get to show pet name and title in Many2one selection"""
        result = []
        for rec in self:
            pet_name = rec.pet_id.name if rec.pet_id else 'Unknown Pet'
            title = rec.title if rec.title else 'No Title'
            name = f"{pet_name} - {title}"
            result.append((rec.id, name))
        return result

    def action_create_invoice(self):
        """Create invoice for this appointment"""
        for rec in self:
            if rec.invoice_id:
                return {
                    'type': 'ir.actions.act_window',
                    'name': 'Invoice',
                    'res_model': 'account.move',
                    'view_mode': 'form',
                    'res_id': rec.invoice_id.id,
                    'target': 'current',
                }
            
            # Create invoice
            invoice_vals = {
                'move_type': 'out_invoice',
                'partner_id': rec.owner_id.id if rec.owner_id else False,
                'invoice_date': fields.Date.today(),
                'invoice_date_due': fields.Date.today(),
                'ref': f"Appointment: {rec.name}",
                'invoice_origin': rec.name,
                'company_id': rec.company_id.id,
                'currency_id': rec.currency_id.id,
            }
            
            invoice = self.env['account.move'].sudo().create(invoice_vals)
            
            # Create invoice lines based on facilities and services
            invoice_lines = rec._prepare_invoice_lines()
            for line_vals in invoice_lines:
                line_vals['move_id'] = invoice.id
                self.env['account.move.line'].sudo().create(line_vals)
            
            # Update appointment with invoice reference
            rec.invoice_id = invoice.id
            
            return {
                'type': 'ir.actions.act_window',
                'name': 'Invoice Created',
                'res_model': 'account.move',
                'view_mode': 'form',
                'res_id': invoice.id,
                'target': 'current',
            }

    def _prepare_invoice_lines(self):
        """Prepare invoice lines based on appointment facilities and services"""
        lines = []
        
        # Medical Visit - only if completed
        if self.medical_visit_id and self.medical_visit_id.cost and self.medical_visit_id.status == 'completed':
            lines.append({
                'name': f"Medical Visit - {self.medical_visit_id.reason or 'Consultation'}",
                'quantity': 1,
                'price_unit': self.medical_visit_id.cost,
                'account_id': self._get_default_account_id(),
            })
        
        # Vaccination - only if administered
        if self.vaccination_id and self.vaccination_id.cost and self.vaccination_id.state == 'administered':
            lines.append({
                'name': f"Vaccination - {self.vaccination_id.vaccine_id.name if self.vaccination_id.vaccine_id else 'Vaccine'}",
                'quantity': 1,
                'price_unit': self.vaccination_id.cost,
                'account_id': self._get_default_account_id(),
            })
        
        # Direct Vaccine (if selected separately)
        if self.vaccine_id and self.vaccine_id.cost:
            lines.append({
                'name': f"Vaccine - {self.vaccine_id.name}",
                'quantity': 1,
                'price_unit': self.vaccine_id.cost,
                'account_id': self._get_default_account_id(),
            })
        
        # Grooming Session - only if completed
        if self.grooming_session_id and self.grooming_session_id.total_cost and self.grooming_session_id.state == 'completed':
            lines.append({
                'name': f"Grooming - {self.grooming_session_id.service_id.name if self.grooming_session_id.service_id else 'Grooming Service'}",
                'quantity': 1,
                'price_unit': self.grooming_session_id.total_cost,
                'account_id': self._get_default_account_id(),
            })
        elif self.service_id and self.service_id.base_price and self.grooming_session_id and self.grooming_session_id.state == 'completed':
            lines.append({
                'name': f"Grooming Service - {self.service_id.name}",
                'quantity': 1,
                'price_unit': self.service_id.base_price,
                'account_id': self._get_default_account_id(),
            })
        
        # Training Session - only if completed
        if self.training_session_id and self.training_session_id.session_cost and self.training_session_id.state == 'completed':
            lines.append({
                'name': f"Training - {self.training_session_id.program_id.name if self.training_session_id.program_id else 'Training Program'}",
                'quantity': 1,
                'price_unit': self.training_session_id.session_cost,
                'account_id': self._get_default_account_id(),
            })
        elif self.program_id and self.program_id.base_price and self.training_session_id and self.training_session_id.state == 'completed':
            lines.append({
                'name': f"Training Program - {self.program_id.name}",
                'quantity': 1,
                'price_unit': self.program_id.base_price,
                'account_id': self._get_default_account_id(),
            })
        
        # Boarding Stay - only if checked out (completed)
        if self.boarding_stay_id and self.boarding_stay_id.total_cost and self.boarding_stay_id.state == 'checked_out':
            lines.append({
                'name': f"Boarding - {self.boarding_stay_id.kennel_id.name if self.boarding_stay_id.kennel_id else 'Boarding Stay'}",
                'quantity': 1,
                'price_unit': self.boarding_stay_id.total_cost,
                'account_id': self._get_default_account_id(),
            })
        
        # If no specific service lines were created, use appointment cost as fallback
        if not lines and self.cost > 0:
            lines.append({
                'name': f"Appointment - {self.title or 'Pet Care Services'}",
                'quantity': 1,
                'price_unit': self.cost,
                'account_id': self._get_default_account_id(),
            })
        
        return lines

    def _get_default_account_id(self):
        """Get default account for invoice lines"""
        # Try to get the default income account for services
        account = self.env['account.account'].search([
            ('account_type', '=', 'income_other'),
            ('company_id', '=', self.company_id.id)
        ], limit=1)
        
        # Fallback to any account if no income account found
        if not account:
            account = self.env['account.account'].search([
                ('company_id', '=', self.company_id.id)
            ], limit=1)
        
        return account.id if account else False

    def action_view_invoice(self):
        """View the generated invoice"""
        for rec in self:
            if rec.invoice_id:
                return {
                    'type': 'ir.actions.act_window',
                    'name': 'Invoice',
                    'res_model': 'account.move',
                    'view_mode': 'form',
                    'res_id': rec.invoice_id.id,
                    'target': 'current',
                }
            else:
                return rec.action_create_invoice()

    def action_cancel_invoice(self):
        """Cancel the generated invoice"""
        for rec in self:
            if rec.invoice_id and rec.invoice_state in ['draft', 'posted']:
                rec.invoice_id.button_cancel()

    def action_refresh_invoice(self):
        """Refresh/update the invoice with current appointment data"""
        for rec in self:
            if not rec.invoice_id:
                return rec.action_create_invoice()
            
            # Only refresh if invoice is in draft state
            if rec.invoice_state not in ['draft']:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Warning',
                        'message': 'Invoice can only be refreshed when in draft state.',
                        'type': 'warning',
                        'sticky': False,
                    }
                }
            
            # Refresh invoice using the synchronous method
            rec._refresh_invoice_sync()
            
            return {
                'type': 'ir.actions.act_window',
                'name': 'Invoice Refreshed',
                'res_model': 'account.move',
                'view_mode': 'form',
                'res_id': rec.invoice_id.id,
                'target': 'current',
            }
    
    def action_assign_current_user_as_resource(self):
        """Assign current user as resource to this appointment"""
        self.ensure_one()
        user = self.env.user
        
        # Check if user has a partner
        if not user.partner_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': 'Current user does not have a partner record',
                    'type': 'error',
                    'sticky': True,
                }
            }
        
        # Assign current user's partner as resource
        self.resource_id = user.partner_id.id
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': f'Assigned {user.partner_id.name} as resource to this appointment',
                'type': 'success',
                'sticky': True,
            }
        }

    # Integration Methods
    def _is_calendar_module_installed(self):
        """Check if calendar module is installed and active"""
        try:
            return self.env['ir.module.module'].search([
                ('name', '=', 'calendar'),
                ('state', '=', 'installed')
            ]).exists() and 'calendar.event' in self.env
        except:
            return False

    def _is_stock_module_installed(self):
        """Check if stock module is installed and active"""
        try:
            return self.env['ir.module.module'].search([
                ('name', '=', 'stock'),
                ('state', '=', 'installed')
            ]).exists() and 'stock.move' in self.env
        except:
            return False

    def action_sync_to_calendar(self):
        """Sync appointment to calendar if calendar module is installed and enabled"""
        if not self._is_calendar_module_installed():
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Warning',
                    'message': 'Calendar module is not installed. Please install the Calendar module to use this feature.',
                    'type': 'warning',
                    'sticky': True,
                }
            }
        
        if not self.sync_to_calendar:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Info',
                    'message': 'Calendar sync is disabled for this appointment.',
                    'type': 'info',
                    'sticky': False,
                }
            }
        
        # Check if calendar integration is enabled in settings
        icp = self.env['ir.config_parameter'].sudo()
        enable_calendar = icp.get_param('pet_management.enable_calendar_integration') in (True, 'True', '1', 1)
        
        if not enable_calendar:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Info',
                    'message': 'Calendar integration is disabled in Pet Management settings.',
                    'type': 'info',
                    'sticky': False,
                }
            }
        
        # Create or update calendar event
        if CALENDAR_INSTALLED:
            if not self.calendar_event_id:
                event_vals = {
                    'name': f"Pet Appointment: {self.title}",
                    'start': self.start_datetime,
                    'stop': self.end_datetime,
                    'description': f"Pet: {self.pet_id.sudo().name}\nOwner: {self.owner_id.sudo().name}\nNotes: {self.notes or ''}",
                    'partner_ids': [(6, 0, [self.owner_id.id])],
                    'user_id': self.resource_id.user_ids[0].id if self.resource_id and self.resource_id.user_ids else self.env.user.id,
                }
                event = self.env['calendar.event'].sudo().create(event_vals)
                self.calendar_event_id = event.id
            else:
                self.calendar_event_id.sudo().write({
                    'name': f"Pet Appointment: {self.title}",
                    'start': self.start_datetime,
                    'stop': self.end_datetime,
                    'description': f"Pet: {self.pet_id.sudo().name}\nOwner: {self.owner_id.sudo().name}\nNotes: {self.notes or ''}",
                })
        else:
            # Calendar module not installed, cannot sync
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': 'Calendar module is not installed. Cannot sync to calendar.',
                    'type': 'error',
                    'sticky': True,
                }
            }
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': 'Appointment synced to calendar successfully.',
                'type': 'success',
                'sticky': True,
            }
        }

    def action_view_calendar_event(self):
        """Open the linked calendar event"""
        if not CALENDAR_INSTALLED or not self.calendar_event_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Warning',
                    'message': 'No calendar event linked to this appointment or calendar module not installed.',
                    'type': 'warning',
                    'sticky': True,
                }
            }

        return {
            'type': 'ir.actions.act_window',
            'name': 'Calendar Event',
            'res_model': 'calendar.event',
            'res_id': self.calendar_event_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_manage_inventory(self):
        """Open inventory management for this appointment if stock module is installed"""
        if not self._is_stock_module_installed():
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Warning',
                    'message': 'Stock module is not installed. Please install the Stock module to use this feature.',
                    'type': 'warning',
                    'sticky': True,
                }
            }
        
        # Check if inventory integration is enabled in settings
        icp = self.env['ir.config_parameter'].sudo()
        enable_inventory = icp.get_param('pet_management.enable_inventory_integration') in (True, 'True', '1', 1)
        
        if not enable_inventory:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Info',
                    'message': 'Inventory integration is disabled in Pet Management settings.',
                    'type': 'info',
                    'sticky': False,
                }
            }
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Appointment Inventory Items',
            'res_model': 'pet.appointment.inventory',
            'view_mode': 'list,form',
            'domain': [('appointment_id', '=', self.id)],
            'context': {'default_appointment_id': self.id},
            'target': 'current',
        }


# Conditionally add calendar_event_id field if calendar module is installed
if CALENDAR_INSTALLED:
    PetAppointment.calendar_event_id = fields.Many2one('calendar.event', string='Calendar Event', help="Linked calendar event")
