from datetime import timedelta
from odoo import models, fields, api, _ # type
from odoo.exceptions import UserError, ValidationError

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
        ('checkup', 'Regular Exam'), ('emergency', 'Emergency Exam'),
        ('home_visit', 'Home Visit'),
        ('surgery', 'Surgery'),
        ('dental', 'Dental'), ('comprehensive', 'Comprehensive Care'), ('other', 'Other')
    ], required=True, tracking=True, help="Primary type of appointment")
    name = fields.Char(string='Reference', readonly=True, copy=False, default=lambda s: _('New'), help="Appointment reference")
    title = fields.Char(
        required=True, tracking=True,
        default=lambda self: self._format_appointment_title(_('New'), fields.Datetime.now()),
        help="Appointment title (auto: serial | date time)")
    start_datetime = fields.Datetime(required=True, index=True, tracking=True,
        default=lambda self: fields.Datetime.now(), help="Appointment start time")
    end_datetime = fields.Datetime(required=True, index=True, tracking=True,
        default=lambda self: fields.Datetime.now() + timedelta(minutes=15), help="Appointment end time")
    vet_employee_id = fields.Many2one(
        'hr.employee', string='Veterinarian', tracking=True,
        default=lambda self: self.env.user.employee_id.id if self.env.user.employee_id else False,
        help="Veterinarian assigned to this appointment")
    resource_id = fields.Many2one(
        'res.partner',
        domain=lambda self: [('id', '=', self.env.user.partner_id.id)] if self.env.user.has_group('pet_management.group_pet_staff_appointments') else [],
        help="Legacy staff field (deprecated — use Veterinarian employee instead)"
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
    amount_total = fields.Monetary(
        compute='_compute_amount_total', store=True, currency_field='currency_id',
        string='Amount', help="Real billable amount: invoice total when invoiced, otherwise the computed service cost")
    payment_status = fields.Selection([
        ('pending', 'Pending'), ('paid', 'Paid'), ('partial', 'Partial'), ('cancelled', 'Cancelled')
    ], string='Payment Status', compute='_compute_payment_status', store=True,
       help="Payment status derived from the linked invoice")
    follow_up_date = fields.Date(help="Recommended follow-up date")
    follow_up_notes = fields.Text(help="Follow-up instructions")
    
    # Calendar Integration Fields
    sync_to_calendar = fields.Boolean(default=True, help="Sync this appointment to calendar")
    calendar_event_id = fields.Many2one('calendar.event', string='Calendar Event', ondelete='set null', help="Linked calendar event")
    enable_calendar_integration = fields.Boolean(compute='_compute_enable_calendar_integration', help="Whether calendar integration is enabled")
    has_calendar_event = fields.Boolean(compute='_compute_has_calendar_event', help="Whether a calendar event is linked")
    
    # Inventory Integration Fields (only if stock module is installed)
    inventory_items_ids = fields.One2many('pet.appointment.inventory', 'appointment_id', string='Inventory Items', help="Items used during appointment")
    inventory_cost = fields.Float(compute='_compute_inventory_cost', store=True, help="Total cost of inventory items used")

    # Additional ad-hoc service/charge lines (billed on top of facility services)
    extra_service_line_ids = fields.One2many(
        'pet.appointment.service.line', 'appointment_id', string='Additional Services',
        help="Extra services or charges added manually; included in the total and the invoice")
    extra_service_cost = fields.Monetary(
        compute='_compute_extra_service_cost', store=True, currency_field='currency_id',
        help="Total of the additional service lines")
    
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
    
    # Sales / Invoice Related Fields
    sale_order_id = fields.Many2one('sale.order', string='Sale Order', readonly=True, copy=False, help="Sales order (quotation) generated for this appointment so it appears in the Sales app")
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

    @api.depends('extra_service_line_ids.price_subtotal')
    def _compute_extra_service_cost(self):
        for rec in self:
            rec.extra_service_cost = sum(rec.extra_service_line_ids.mapped('price_subtotal'))

    @api.depends('medical_visit_id.cost', 'vaccination_id.cost', 'grooming_session_id.total_cost', 
                 'training_session_id.session_cost', 'boarding_stay_id.total_cost', 'vaccine_id.cost', 'service_id.base_price', 'program_id.base_price',
                 'medical_visit_id.status', 'vaccination_id.state', 'grooming_session_id.state', 'training_session_id.state', 'boarding_stay_id.state',
                 'extra_service_line_ids.price_subtotal')
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

            # Additional manual service lines - always counted
            cost += sum(rec.extra_service_line_ids.mapped('price_subtotal'))

            rec.cost = cost

    @api.depends('invoice_id', 'invoice_id.amount_total', 'cost')
    def _compute_amount_total(self):
        """Real billable amount: prefer the actual invoice total, else the service cost."""
        for rec in self:
            if rec.invoice_id and rec.invoice_id.amount_total:
                rec.amount_total = rec.invoice_id.amount_total
            else:
                rec.amount_total = rec.cost

    @api.depends('invoice_id', 'invoice_id.payment_state', 'invoice_id.state', 'state')
    def _compute_payment_status(self):
        """Reflect the real invoice payment state instead of a manual flag."""
        for rec in self:
            if rec.state == 'cancelled':
                rec.payment_status = 'cancelled'
                continue
            inv = rec.invoice_id
            if inv and inv.state == 'posted':
                ps = inv.payment_state
                if ps in ('paid', 'in_payment', 'reversed'):
                    rec.payment_status = 'paid'
                elif ps == 'partial':
                    rec.payment_status = 'partial'
                else:
                    rec.payment_status = 'pending'
            else:
                rec.payment_status = 'pending'

    @api.depends('inventory_items_ids', 'inventory_items_ids.total_cost')
    def _compute_inventory_cost(self):
        """Compute total inventory cost for this appointment"""
        for rec in self:
            rec.inventory_cost = sum(rec.inventory_items_ids.mapped('total_cost'))

    def _compute_enable_calendar_integration(self):
        """Compute whether calendar integration is enabled"""
        for rec in self:
            rec.enable_calendar_integration = rec._is_calendar_module_installed()

    @api.depends('calendar_event_id')
    def _compute_has_calendar_event(self):
        """Compute whether a calendar event exists."""
        for rec in self:
            rec.has_calendar_event = bool(rec.calendar_event_id)

    @api.constrains('start_datetime', 'end_datetime')
    def _check_range(self):
        for rec in self:
            if rec.start_datetime and rec.end_datetime and rec.end_datetime <= rec.start_datetime:
                raise ValidationError('End must be after Start.')

    @api.constrains("vet_employee_id", "room_id", "start_datetime", "end_datetime")
    def _check_overlap(self):
        for rec in self:
            # Check veterinarian overlap
            if rec.vet_employee_id:
                vet_overlap = self.search([
                    ("id", "!=", rec.id),
                    ("vet_employee_id", "=", rec.vet_employee_id.id),
                    ("start_datetime", "<=", rec.end_datetime),
                    ("end_datetime", ">=", rec.start_datetime),
                    ("state", "not in", ["cancelled"])
                ], limit=1)
                if vet_overlap:
                    raise ValidationError(_('Veterinarian %s is already booked during this time period.') % rec.vet_employee_id.name)
            
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

    def set_to_draft(self):
        for rec in self:
            rec.state = 'draft'

    def _get_primary_type_label(self):
        """Human-readable appointment type for notifications."""
        self.ensure_one()
        labels = dict(self._fields['primary_type']._description_selection(self.env))
        return labels.get(self.primary_type) or self.title or 'pet care'

    def action_send_notification(self):
        """Create and send notification for this appointment"""
        for rec in self:
            # Determine notification type and priority based on appointment state and timing
            now = fields.Datetime.now()
            time_diff = (rec.start_datetime - now).total_seconds() / 3600  # hours
            
            if rec.state == 'draft':
                notification_type = 'appointment_reminder'
                priority = 'medium'
                message = f"Appointment scheduled: {rec.pet_id.name} has a {rec._get_primary_type_label()} appointment on {rec.start_datetime.strftime('%B %d, %Y at %I:%M %p')}."
            elif rec.state == 'confirmed':
                if time_diff <= 24:  # Within 24 hours
                    notification_type = 'appointment_reminder'
                    priority = 'high'
                    message = f"REMINDER: {rec.pet_id.name}'s {rec._get_primary_type_label()} appointment is tomorrow at {rec.start_datetime.strftime('%I:%M %p')}. Please arrive 10 minutes early."
                else:
                    notification_type = 'appointment_reminder'
                    priority = 'medium'
                    message = f"Confirmed: {rec.pet_id.name}'s {rec._get_primary_type_label()} appointment is scheduled for {rec.start_datetime.strftime('%B %d, %Y at %I:%M %p')}."
            elif rec.state == 'in_progress':
                notification_type = 'general'
                priority = 'medium'
                message = f"In Progress: {rec.pet_id.name}'s {rec._get_primary_type_label()} appointment is currently in progress with {rec.vet_employee_id.name if rec.vet_employee_id else 'staff'}."
            elif rec.state == 'done':
                notification_type = 'general'
                priority = 'low'
                message = f"Completed: {rec.pet_id.name}'s {rec._get_primary_type_label()} appointment was completed on {rec.start_datetime.strftime('%B %d, %Y')}. Follow-up: {rec.follow_up_date.strftime('%B %d, %Y') if rec.follow_up_date else 'Not required'}."
            elif rec.state == 'cancelled':
                notification_type = 'general'
                priority = 'low'
                message = f"Cancelled: {rec.pet_id.name}'s {rec._get_primary_type_label()} appointment scheduled for {rec.start_datetime.strftime('%B %d, %Y at %I:%M %p')} has been cancelled."
            elif rec.state == 'rescheduled':
                notification_type = 'general'
                priority = 'medium'
                message = f"Rescheduled: {rec.pet_id.name}'s {rec._get_primary_type_label()} appointment has been rescheduled. New time: {rec.start_datetime.strftime('%B %d, %Y at %I:%M %p')}."
            else:
                notification_type = 'general'
                priority = 'low'
                message = f"Update: {rec.pet_id.name}'s {rec._get_primary_type_label()} appointment status is {rec.state}."
            
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
                    'message': f"Reminder: {rec.pet_id.name}'s {rec._get_primary_type_label()} appointment is scheduled for {rec.start_datetime.strftime('%B %d, %Y at %I:%M %p')}. Please arrive 10 minutes early.",
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
            if rec.is_medical or rec.primary_type in ['checkup', 'emergency', 'home_visit', 'surgery', 'dental', 'comprehensive']:
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

    @api.model
    def _map_primary_type_to_visit_type(self, primary_type):
        mapping = {
            'comprehensive': 'checkup',
        }
        visit_types = dict(self.env['pet.medical.visit'].VISIT_TYPE_SELECTION)
        if primary_type in visit_types:
            return primary_type
        return mapping.get(primary_type, 'other')

    def _vet_partner_id(self, employee=None):
        """Map hr.employee to res.partner for legacy vet_id fields on visits/vaccinations."""
        employee = employee or self.vet_employee_id
        if not employee:
            return False
        if employee.work_contact_id:
            return employee.work_contact_id.id
        if employee.user_id and employee.user_id.partner_id:
            return employee.user_id.partner_id.id
        return False

    def _format_appointment_title(self, name, start_datetime=None):
        """Build default title: APT26-0001 | 08/07/2026 14:30"""
        start_dt = start_datetime or fields.Datetime.now()
        local_dt = fields.Datetime.context_timestamp(self, start_dt)
        stamp = local_dt.strftime('%d/%m/%Y %H:%M')
        ref = name if name and name != _('New') else _('Appointment')
        return f'{ref} | {stamp}'

    @api.onchange('start_datetime')
    def _onchange_start_datetime_title(self):
        """Refresh draft title when start time changes on a new appointment."""
        if not self._origin.id and self.start_datetime:
            self.title = self._format_appointment_title(self.name or _('New'), self.start_datetime)

    def _create_medical_visit(self):
        """Create medical visit entry"""
        if not self.medical_visit_id:
            visit_vals = {
                'pet_id': self.pet_id.id,
                'date': self.start_datetime,
                'visit_type': self._map_primary_type_to_visit_type(self.primary_type),
                'reason': self.title,
                'vet_employee_id': self.vet_employee_id.id if self.vet_employee_id else False,
                'vet_id': self._vet_partner_id(),
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
                'vet_employee_id': self.vet_employee_id.id if self.vet_employee_id else False,
                'vet_id': self._vet_partner_id(),
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
            groomer_id = self.vet_employee_id.id if self.vet_employee_id else False
            if not groomer_id:
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
            trainer_id = self.vet_employee_id.id if self.vet_employee_id else False
            if not trainer_id:
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
            if not vals.get('title'):
                vals['title'] = self._format_appointment_title(
                    vals.get('name', _('New')),
                    vals.get('start_datetime'),
                )
            if not vals.get('vet_employee_id') and self.env.user.employee_id:
                vals['vet_employee_id'] = self.env.user.employee_id.id
            
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

        # Propagate a changed veterinarian to already-created facility records
        if 'vet_employee_id' in vals:
            for rec in self:
                vet = rec.vet_employee_id.id if rec.vet_employee_id else False
                partner = rec._vet_partner_id()
                if rec.medical_visit_id:
                    rec.medical_visit_id.write({'vet_employee_id': vet, 'vet_id': partner})
                if rec.vaccination_id:
                    rec.vaccination_id.write({'vet_employee_id': vet, 'vet_id': partner})

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

    def _get_generic_service_product(self):
        """Find or create a generic service product used for sale order lines
        that have no dedicated product (grooming, training, boarding, discounts...).
        invoice_policy='order' guarantees confirmed lines are immediately invoiceable."""
        Product = self.env['product.product'].sudo()
        product = Product.search([('default_code', '=', 'PET-SERVICE')], limit=1)
        if not product:
            product = Product.create({
                'name': 'Pet Care Service',
                'default_code': 'PET-SERVICE',
                'type': 'service',
                'invoice_policy': 'order',
                'list_price': 0.0,
                'taxes_id': [(6, 0, [])],
            })
        return product

    def _prepare_sale_order_lines(self):
        """Build sale.order.line values mirroring the billable services.
        Every line carries a product (dedicated when available, else generic)."""
        self.ensure_one()
        generic = self._get_generic_service_product()
        lines = []

        def add(name, price, product=None, qty=1.0, discount=0.0):
            lines.append({
                'product_id': (product.id if product else generic.id),
                'name': name,
                'product_uom_qty': qty or 1.0,
                'price_unit': price,
                'discount': discount or 0.0,
                'tax_ids': [(6, 0, [])],
            })

        # Medical visit: bill priced product/service lines even before completion.
        # Prefer completed behavior (discount + cost fallback) when completed.
        if self.medical_visit_id:
            visit = self.medical_visit_id
            visit_lines = visit.line_ids.filtered(lambda line: line.price_subtotal > 0)
            if visit_lines:
                for line in visit_lines:
                    add(line.name, line.price_unit,
                        product=line.product_id or None,
                        qty=line.quantity or 1.0,
                        discount=line.discount or 0.0)
                if visit.status == 'completed' and visit.discount_amount:
                    add(_('Visit discount'), -abs(visit.discount_amount))
            elif visit.status == 'completed' and visit.cost:
                add(f"Medical Visit - {visit.reason or 'Consultation'}", visit.cost)

        # Vaccination - only if administered
        if self.vaccination_id and self.vaccination_id.cost and self.vaccination_id.state == 'administered':
            add(f"Vaccination - {self.vaccination_id.vaccine_id.name if self.vaccination_id.vaccine_id else 'Vaccine'}",
                self.vaccination_id.cost)

        # Direct Vaccine (if selected separately)
        if self.vaccine_id and self.vaccine_id.cost:
            add(f"Vaccine - {self.vaccine_id.name}", self.vaccine_id.cost)

        # Grooming Session - only if completed
        if self.grooming_session_id and self.grooming_session_id.total_cost and self.grooming_session_id.state == 'completed':
            add(f"Grooming - {self.grooming_session_id.service_id.name if self.grooming_session_id.service_id else 'Grooming Service'}",
                self.grooming_session_id.total_cost)
        elif self.service_id and self.service_id.base_price and self.grooming_session_id and self.grooming_session_id.state == 'completed':
            add(f"Grooming Service - {self.service_id.name}", self.service_id.base_price)

        # Training Session - only if completed
        if self.training_session_id and self.training_session_id.session_cost and self.training_session_id.state == 'completed':
            add(f"Training - {self.training_session_id.program_id.name if self.training_session_id.program_id else 'Training Program'}",
                self.training_session_id.session_cost)
        elif self.program_id and self.program_id.base_price and self.training_session_id and self.training_session_id.state == 'completed':
            add(f"Training Program - {self.program_id.name}", self.program_id.base_price)

        # Boarding Stay - only if checked out (completed)
        if self.boarding_stay_id and self.boarding_stay_id.total_cost and self.boarding_stay_id.state == 'checked_out':
            add(f"Boarding - {self.boarding_stay_id.kennel_id.name if self.boarding_stay_id.kennel_id else 'Boarding Stay'}",
                self.boarding_stay_id.total_cost)

        # Additional manual service lines (skip invoice-synced to avoid double-billing)
        for line in self.extra_service_line_ids:
            if line.invoice_synced:
                continue
            if line.price_subtotal:
                add(line.name or (line.product_id.display_name if line.product_id else _('Service')),
                    line.price_unit,
                    product=line.product_id or None,
                    qty=line.quantity or 1.0,
                    discount=line.discount or 0.0)

        # Fallback: use appointment cost if nothing else
        if not lines and self.cost > 0:
            add(f"Appointment - {self.title or 'Pet Care Services'}", self.cost)

        return lines

    def _resync_draft_sale_order(self):
        """Rebuild the sale order lines from current services when the order is
        still an editable quotation (not confirmed/invoiced)."""
        if self.env.context.get('skip_appointment_so_resync'):
            return
        for rec in self:
            order = rec.sale_order_id
            if not order or rec.invoice_id:
                continue
            if order.state not in ('draft', 'sent'):
                raise UserError(_(
                    'Cannot rebuild sale order %(order)s because it is already confirmed. '
                    'Edit the quotation before confirming, or set line quantities to 0 on a '
                    'confirmed order instead of deleting lines.',
                    order=order.name,
                ))
            line_vals = rec._prepare_sale_order_lines()
            commands = [(5, 0, 0)] + [(0, 0, lv) for lv in line_vals]
            order.sudo().write({'order_line': commands})
            for so_line, lv in zip(order.order_line, line_vals):
                so_line.write({'price_unit': lv['price_unit'], 'tax_ids': [(6, 0, [])]})

    def _ensure_sale_order(self):
        """Create (once) the sale order/quotation for this appointment."""
        self.ensure_one()
        if self.sale_order_id:
            return self.sale_order_id
        if not self.owner_id:
            raise ValidationError(_('Cannot create a sale order without a customer/owner on the pet.'))
        line_vals = self._prepare_sale_order_lines()
        if not line_vals:
            # Invoice-first: editable placeholder so billing can proceed before services complete
            generic = self._get_generic_service_product()
            line_vals = [{
                'product_id': generic.id,
                'name': self.title or self.name or _('Pet Care Service'),
                'product_uom_qty': 1.0,
                'price_unit': self.cost or 0.0,
                'discount': 0.0,
                'tax_ids': [(6, 0, [])],
            }]
        order = self.env['sale.order'].sudo().create({
            'partner_id': self.owner_id.id,
            'origin': self.name,
            'client_order_ref': self.name,
            'company_id': self.company_id.id,
            'order_line': [(0, 0, lv) for lv in line_vals],
        })
        # Preserve the exact appointment pricing (avoid pricelist recompute surprises)
        for so_line, lv in zip(order.order_line, line_vals):
            so_line.write({'price_unit': lv['price_unit'], 'tax_ids': [(6, 0, [])]})
        self.sale_order_id = order.id
        return order

    def _sync_services_from_invoice(self):
        """Recreate invoice-synced extra_service_line_ids from invoice (or SO) lines.

        Only previous invoice-synced extras are replaced; manually entered extras stay.
        """
        ServiceLine = self.env['pet.appointment.service.line'].with_context(
            skip_appointment_so_resync=True,
        )
        for rec in self:
            source_lines = self.env['account.move.line']
            if rec.invoice_id:
                # Odoo 19 account.move.line uses display_type='product' for billable lines
                # (section/note/tax/payment_term/cogs are other values).
                source_lines = rec.invoice_id.invoice_line_ids.filtered(
                    lambda l: l.display_type == 'product' and l.product_id
                )
            if not source_lines and rec.sale_order_id:
                # sale.order.line: product lines have display_type False/empty
                source_lines = rec.sale_order_id.order_line.filtered(
                    lambda l: not l.display_type and l.product_id
                )
            if not source_lines:
                continue

            rec.extra_service_line_ids.filtered('invoice_synced').with_context(
                skip_appointment_so_resync=True,
            ).unlink()

            vals_list = []
            for line in source_lines:
                if 'product_uom_qty' in line._fields and 'quantity' not in line._fields:
                    qty = line.product_uom_qty
                else:
                    qty = line.quantity
                vals_list.append({
                    'appointment_id': rec.id,
                    'product_id': line.product_id.id,
                    'name': line.name or line.product_id.display_name,
                    'quantity': qty or 1.0,
                    'price_unit': line.price_unit or 0.0,
                    'discount': getattr(line, 'discount', 0.0) or 0.0,
                    'invoice_synced': True,
                })
            if vals_list:
                ServiceLine.create(vals_list)

    def action_create_invoice(self):
        """Create or open a draft/sent sale order for billing review (no confirm/invoice)."""
        self.ensure_one()
        if self.invoice_id:
            return self.action_view_invoice()
        order = self._ensure_sale_order()
        if order.state in ('draft', 'sent'):
            self._resync_draft_sale_order()
        elif order.state == 'sale':
            raise UserError(_(
                'Sale order %(order)s is already confirmed. Use Confirm & Create Invoice '
                'to generate the invoice, or open the sale order to review it.',
                order=order.name,
            ))
        elif order.state == 'cancel':
            raise UserError(_(
                'Sale order %(order)s is cancelled. Create a new quotation from Sales.',
                order=order.name,
            ))
        return self.action_view_sale_order()

    def action_confirm_and_create_invoice(self):
        """Confirm the sale order, create the invoice, post it, and sync appointment lines."""
        self.ensure_one()
        if self.invoice_id:
            return self.action_view_invoice()
        order = self._ensure_sale_order()
        if order.state in ('draft', 'sent'):
            order.action_confirm()
        elif order.state == 'cancel':
            raise UserError(_(
                'Sale order %(order)s is cancelled and cannot be invoiced.',
                order=order.name,
            ))
        invoices = order._create_invoices()
        if not invoices:
            raise UserError(_(
                'No invoice was created from sale order %(order)s. '
                'Check that the order has billable lines.',
                order=order.name,
            ))
        invoices.action_post()
        self.invoice_id = invoices[0].id
        self._sync_services_from_invoice()
        return self.action_view_invoice()

    def action_view_sale_order(self):
        """Open the sale order for this appointment."""
        self.ensure_one()
        if not self.sale_order_id:
            return self.action_create_invoice()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sale Order'),
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': self.sale_order_id.id,
            'target': 'current',
        }

    def _prepare_invoice_lines(self):
        """Prepare invoice lines based on appointment facilities and services"""
        lines = []
        account_id = self._get_default_account_id()

        # Medical visit lines - explode each visit line when completed
        if self.medical_visit_id and self.medical_visit_id.status == 'completed':
            visit = self.medical_visit_id
            visit_lines = visit.line_ids.filtered(lambda line: line.price_subtotal > 0)
            if visit_lines:
                for line in visit_lines:
                    line_vals = {
                        'name': line.name,
                        'quantity': line.quantity or 1.0,
                        'price_unit': line.price_unit,
                        'account_id': account_id,
                    }
                    if line.product_id:
                        line_vals['product_id'] = line.product_id.id
                    if line.discount:
                        line_vals['discount'] = line.discount
                    lines.append(line_vals)
                if visit.discount_amount:
                    lines.append({
                        'name': _('Visit discount'),
                        'quantity': 1,
                        'price_unit': -abs(visit.discount_amount),
                        'account_id': account_id,
                    })
            elif visit.cost:
                lines.append({
                    'name': f"Medical Visit - {visit.reason or 'Consultation'}",
                    'quantity': 1,
                    'price_unit': visit.cost,
                    'account_id': account_id,
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
        # account.account is multi-company in Odoo 19 (company_ids m2m)
        account = self.env['account.account'].search([
            ('account_type', '=', 'income_other'),
            ('company_ids', 'in', self.company_id.id)
        ], limit=1)
        
        # Fallback to any income account, then any account for this company
        if not account:
            account = self.env['account.account'].search([
                ('account_type', 'in', ('income', 'income_other')),
                ('company_ids', 'in', self.company_id.id)
            ], limit=1)
        if not account:
            account = self.env['account.account'].search([
                ('company_ids', 'in', self.company_id.id)
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
                if rec.sale_order_id:
                    return rec.action_view_sale_order()
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
                if rec.sale_order_id:
                    return rec.action_view_sale_order()
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
        """Assign current user's employee record as veterinarian on this appointment."""
        self.ensure_one()
        employee = self.env.user.employee_id
        if not employee:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('Current user is not linked to an employee record.'),
                    'type': 'error',
                    'sticky': True,
                }
            }
        self.vet_employee_id = employee.id
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': _('Assigned %s as veterinarian to this appointment') % employee.name,
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
        if not self.calendar_event_id:
            event_vals = {
                'name': f"Pet Appointment: {self.title}",
                'start': self.start_datetime,
                'stop': self.end_datetime,
                'description': f"Pet: {self.pet_id.sudo().name}\nOwner: {self.owner_id.sudo().name}\nNotes: {self.notes or ''}",
                'partner_ids': [(6, 0, [self.owner_id.id])],
                'user_id': self.vet_employee_id.user_id.id if self.vet_employee_id and self.vet_employee_id.user_id else self.env.user.id,
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
        if not self.calendar_event_id:
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
