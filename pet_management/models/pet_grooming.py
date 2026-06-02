from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import timedelta

class PetGroomingEquipment(models.Model):
    _name = 'pet.grooming.equipment'
    _description = 'Grooming Equipment'
    _order = 'name'

    name = fields.Char(string="Name", required=True, help="Equipment name")
    description = fields.Text(string="Description", help="Equipment description")
    category = fields.Selection([
        ('tools', 'Grooming Tools'),
        ('products', 'Grooming Products'),
        ('machines', 'Machines & Equipment'),
        ('safety', 'Safety Equipment'),
        ('cleaning', 'Cleaning Supplies')
    ], string="Category", required=True, help="Equipment category")
    active = fields.Boolean(string="Active", default=True, help="Is this equipment active?")

class PetGroomingService(models.Model):
    _name = 'pet.grooming.service'
    _description = 'Grooming Service'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string="Name", required=True, tracking=True, help="Service name")
    code = fields.Char(string="Code", tracking=True, help="Service code for easy identification")
    description = fields.Text(string="Description", help="Detailed description of the service")
    category = fields.Selection([
        ('basic', 'Basic Grooming'),
        ('premium', 'Premium Grooming'),
        ('spa', 'Spa Treatment'),
        ('medical', 'Medical Grooming'),
        ('specialty', 'Specialty Service')
    ], string="Category", required=True, default='basic', tracking=True, help="Service category")
    
    # Pricing & Duration
    base_price = fields.Float(string="Base Price", required=True, default=0.0, tracking=True, help="Base price for this service")
    duration_minutes = fields.Integer(string="Duration (Minutes)", required=True, default=30, tracking=True, help="Duration in minutes")
    duration_display = fields.Char(string="Duration Display", compute='_compute_duration_display', store=True, help="Duration in readable format")
    
    # Service Requirements
    required_equipment_ids = fields.Many2many('pet.grooming.equipment', string='Required Equipment', help="Equipment needed for this service")
    skill_level = fields.Selection([
        ('beginner', 'Beginner'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
        ('expert', 'Expert')
    ], string="Skill Level", required=True, default='beginner', help="Required skill level")
    
    # Pet Requirements
    min_age_months = fields.Integer(help="Minimum age in months for this service")
    max_age_months = fields.Integer(help="Maximum age in months for this service")
    species_restrictions = fields.Selection([
        ('all', 'All Species'),
        ('dogs_only', 'Dogs Only'),
        ('cats_only', 'Cats Only'),
        ('small_animals', 'Small Animals Only')
    ], default='all', help="Species restrictions for this service")
    
    # Service Details
    product_id = fields.Many2one('product.product', help="Related product for invoicing")
    preparation_notes = fields.Text(help="Preparation instructions for the groomer")
    aftercare_notes = fields.Text(help="Aftercare instructions for pet owners")
    contraindications = fields.Text(help="When this service should not be performed")
    
    # Analytics
    session_count = fields.Integer(compute='_compute_session_count', store=True, help="Number of sessions using this service")
    total_revenue = fields.Float(compute='_compute_total_revenue', store=True, help="Total revenue from this service")
    average_rating = fields.Float(compute='_compute_average_rating', store=True, help="Average customer rating")
    
    # Status
    active = fields.Boolean(default=True, tracking=True, help="Is this service active?")
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, help="Company this service belongs to")

    @api.depends('duration_minutes')
    def _compute_duration_display(self):
        for service in self:
            if service.duration_minutes:
                hours = service.duration_minutes // 60
                minutes = service.duration_minutes % 60
                if hours > 0:
                    service.duration_display = f"{hours}h {minutes}m" if minutes > 0 else f"{hours}h"
                else:
                    service.duration_display = f"{minutes}m"
            else:
                service.duration_display = "0m"

    @api.depends('session_count')
    def _compute_session_count(self):
        for service in self:
            service.session_count = self.env['pet.grooming.session'].search_count([('service_id', '=', service.id)])

    @api.depends('session_count')
    def _compute_total_revenue(self):
        for service in self:
            sessions = self.env['pet.grooming.session'].search([('service_id', '=', service.id)])
            service.total_revenue = sum(session.total_cost or 0 for session in sessions)

    @api.depends('session_count')
    def _compute_average_rating(self):
        for service in self:
            sessions = self.env['pet.grooming.session'].search([('service_id', '=', service.id), ('rating', '!=', False)])
            if sessions:
                ratings = [int(session.rating) for session in sessions if session.rating]
                service.average_rating = sum(ratings) / len(ratings) if ratings else 0.0
            else:
                service.average_rating = 0.0

    @api.constrains('duration_minutes')
    def _check_duration(self):
        for service in self:
            if service.duration_minutes and service.duration_minutes <= 0:
                raise ValidationError(_('Duration must be greater than 0 minutes.'))

    @api.constrains('base_price')
    def _check_price(self):
        for service in self:
            if service.base_price < 0:
                raise ValidationError(_('Base price cannot be negative.'))

    @api.constrains('min_age_months', 'max_age_months')
    def _check_age_range(self):
        for service in self:
            if service.min_age_months and service.max_age_months and service.min_age_months > service.max_age_months:
                raise ValidationError(_('Minimum age cannot be greater than maximum age.'))

    def action_view_sessions(self):
        """Action to view sessions for this service"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Grooming Sessions',
            'res_model': 'pet.grooming.session',
            'view_mode': 'kanban,list,form',
            'domain': [('service_id', '=', self.id)],
            'target': 'current',
        }

class PetGroomingSession(models.Model):
    _name = 'pet.grooming.session'
    _description = 'Grooming Session'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'appointment_datetime desc'

    # Basic Information
    name = fields.Char(string='Session Reference', readonly=True, copy=False, default=lambda s: _('New'))
    pet_id = fields.Many2one('pet.pet', string="Pet", required=True, ondelete='cascade', tracking=True, help="Pet being groomed")
    appointment_id = fields.Many2one('pet.appointment', string='Appointment', help="Related appointment")
    service_id = fields.Many2one('pet.grooming.service', string="Service", required=True, ondelete='restrict', tracking=True, help="Grooming service")
    groomer_id = fields.Many2one(
        'res.partner', string="Groomer",
        domain=lambda self: [('id', '=', self.env.user.partner_id.id)] if self.env.user.has_group('pet_management.group_pet_staff_grooming') else [('is_company','=',False)],
        tracking=True, help="Assigned groomer (staff partner)"
    )
    
    # Scheduling
    appointment_datetime = fields.Datetime(string="Scheduled Date/Time", required=True, tracking=True, help="Scheduled appointment time")
    actual_start_datetime = fields.Datetime(string="Actual Start", help="Actual start time")
    actual_end_datetime = fields.Datetime(string="Actual End", help="Actual end time")
    duration_minutes = fields.Integer(string="Duration (Minutes)", compute='_compute_duration', store=True, help="Actual duration in minutes")
    duration_display = fields.Char(string="Duration Display", compute='_compute_duration', store=True, help="Duration in readable format")
    
    # Session Details
    notes = fields.Text(help="Session notes and observations")
    before_photo = fields.Image(string="Before Photo", help="Photo before grooming")
    after_photo = fields.Image(string="After Photo", help="Photo after grooming")
    special_requests = fields.Text(help="Special requests from pet owner")
    behavior_notes = fields.Text(help="Pet behavior during session")
    
    # Pricing & Payment
    base_price = fields.Float(string="Base Price", related='service_id.base_price', store=True, help="Base service price")
    additional_services_cost = fields.Float(string="Additional Services Cost", default=0.0, help="Cost of additional services")
    total_cost = fields.Float(string="Total Cost", compute='_compute_total_cost', store=True, help="Total session cost")
    payment_status = fields.Selection([
        ('pending', 'Pending'),
        ('partial', 'Partially Paid'),
        ('paid', 'Paid'),
        ('refunded', 'Refunded')
    ], string="Payment Status", default='pending', tracking=True, help="Payment status")
    
    # Customer Feedback
    rating = fields.Selection([
        ('1', 'Very Poor'),
        ('2', 'Poor'),
        ('3', 'Average'),
        ('4', 'Good'),
        ('5', 'Excellent')
    ], help="Customer rating for this session")
    customer_feedback = fields.Text(help="Customer feedback and comments")
    
    # Session Status
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], default='draft', tracking=True, help="Session status")
    state_color = fields.Integer(compute='_compute_state_color', store=True, help="Color code for status display")
    
    # Computed Fields
    days_since_session = fields.Integer(string="Days Since Session", compute='_compute_days_since_session', help="Days since session date")
    is_today = fields.Boolean(string="Is Today", compute='_compute_is_today', search='_search_is_today', help="Is session scheduled for today?")
    is_overdue = fields.Boolean(string="Is Overdue", compute='_compute_is_overdue', search='_search_is_overdue', help="Is session overdue?")
    
    # Company
    company_id = fields.Many2one('res.company', string="Company", required=True, default=lambda s: s.env.company, help="Company")

    @api.model_create_multi
    def create(self, vals_list):
        # Get default grooming session duration from settings
        icp = self.env['ir.config_parameter'].sudo()
        default_duration = float(icp.get_param('pet_management.grooming_session_duration', 2.0))
        
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('pet.grooming.session') or _('New')
            
            # Apply default duration if not specified and we have appointment time
            if 'appointment_datetime' in vals and 'actual_end_datetime' not in vals:
                from datetime import datetime, timedelta
                start_dt = vals['appointment_datetime']
                if isinstance(start_dt, str):
                    start_dt = datetime.fromisoformat(start_dt.replace('Z', '+00:00'))
                vals['actual_end_datetime'] = start_dt + timedelta(hours=default_duration)
                
        return super().create(vals_list)

    @api.depends('actual_start_datetime', 'actual_end_datetime', 'service_id.duration_minutes')
    def _compute_duration(self):
        for session in self:
            if session.actual_start_datetime and session.actual_end_datetime:
                delta = session.actual_end_datetime - session.actual_start_datetime
                session.duration_minutes = int(delta.total_seconds() / 60)
            else:
                session.duration_minutes = session.service_id.duration_minutes if session.service_id else 0
            
            # Format duration display
            if session.duration_minutes:
                hours = session.duration_minutes // 60
                minutes = session.duration_minutes % 60
                if hours > 0:
                    session.duration_display = f"{hours}h {minutes}m" if minutes > 0 else f"{hours}h"
                else:
                    session.duration_display = f"{minutes}m"
            else:
                session.duration_display = "0m"

    @api.depends('base_price', 'additional_services_cost')
    def _compute_total_cost(self):
        for session in self:
            session.total_cost = session.base_price + session.additional_services_cost

    @api.depends('appointment_datetime')
    def _compute_days_since_session(self):
        today = fields.Date.today()
        for session in self:
            if session.appointment_datetime:
                session_date = session.appointment_datetime.date()
                session.days_since_session = (today - session_date).days
            else:
                session.days_since_session = 0

    @api.depends('appointment_datetime')
    def _compute_is_today(self):
        today = fields.Date.today()
        for session in self:
            if session.appointment_datetime:
                session.is_today = session.appointment_datetime.date() == today
            else:
                session.is_today = False

    @api.depends('appointment_datetime', 'state')
    def _compute_is_overdue(self):
        now = fields.Datetime.now()
        for session in self:
            if (session.appointment_datetime and 
                session.appointment_datetime < now and 
                session.state in ['draft', 'confirmed']):
                session.is_overdue = True
            else:
                session.is_overdue = False

    @api.depends('state')
    def _compute_state_color(self):
        color_map = {
            'draft': 1,        # red
            'confirmed': 2,    # orange
            'in_progress': 3,  # yellow
            'completed': 4,    # green
            'cancelled': 0,    # grey
        }
        for session in self:
            session.state_color = color_map.get(session.state, 0)

    @api.constrains('appointment_datetime')
    def _check_appointment_datetime(self):
        # Skip validation during data loading (when name is auto-generated)
        if self.env.context.get('install_mode') or self.env.context.get('import_file'):
            return
            
        for session in self:
            if session.appointment_datetime and session.appointment_datetime < fields.Datetime.now():
                if session.state in ['draft', 'confirmed']:
                    raise ValidationError(_('Cannot schedule grooming session in the past.'))

    @api.constrains('actual_start_datetime', 'actual_end_datetime')
    def _check_actual_times(self):
        for session in self:
            if (session.actual_start_datetime and session.actual_end_datetime and 
                session.actual_start_datetime >= session.actual_end_datetime):
                raise ValidationError(_('Actual end time must be after start time.'))

    # Action Methods
    def action_confirm(self):
        for session in self:
            session.state = 'confirmed'

    def action_start_session(self):
        for session in self:
            session.state = 'in_progress'
            session.actual_start_datetime = fields.Datetime.now()

    def action_complete_session(self):
        for session in self:
            session.state = 'completed'
            session.actual_end_datetime = fields.Datetime.now()

    def action_cancel_session(self):
        for session in self:
            session.state = 'cancelled'

    def name_get(self):
        """Custom name_get to show pet name and service name in Many2one selection"""
        result = []
        for rec in self:
            pet_name = rec.pet_id.name if rec.pet_id else 'Unknown Pet'
            service_name = rec.service_id.name if rec.service_id else 'Unknown Service'
            name = f"{pet_name} - {service_name}"
            result.append((rec.id, name))
        return result

    def action_view_pet(self):
        """Action to view pet details"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Pet Details',
            'res_model': 'pet.pet',
            'view_mode': 'form',
            'res_id': self.pet_id.id,
            'target': 'current',
        }

    @api.model
    def _search_is_today(self, operator, value):
        """Search method for is_today computed field"""
        if operator == '=' and value is True:
            today = fields.Date.today()
            return [('appointment_datetime', '>=', today.strftime('%Y-%m-%d 00:00:00')),
                    ('appointment_datetime', '<=', today.strftime('%Y-%m-%d 23:59:59'))]
        elif operator == '=' and value is False:
            today = fields.Date.today()
            return ['|', '|',
                    ('appointment_datetime', '<', today.strftime('%Y-%m-%d 00:00:00')),
                    ('appointment_datetime', '>', today.strftime('%Y-%m-%d 23:59:59')),
                    ('appointment_datetime', '=', False)]
        return []

    @api.model
    def _search_is_overdue(self, operator, value):
        """Search method for is_overdue computed field"""
        if operator == '=' and value is True:
            now = fields.Datetime.now()
            return [('appointment_datetime', '<', now),
                    ('state', 'in', ['draft', 'confirmed'])]
        elif operator == '=' and value is False:
            now = fields.Datetime.now()
            return ['|', '|',
                    ('appointment_datetime', '>=', now),
                    ('state', 'not in', ['draft', 'confirmed']),
                    ('appointment_datetime', '=', False)]
        return []

    # Advanced Analytics and Reporting
    @api.model
    def get_grooming_analytics(self, date_from=None, date_to=None):
        """Get comprehensive grooming analytics"""
        domain = []
        if date_from:
            domain.append(('appointment_datetime', '>=', date_from))
        if date_to:
            domain.append(('appointment_datetime', '<=', date_to))
        
        sessions = self.search(domain)
        
        return {
            'total_sessions': len(sessions),
            'completed_sessions': len(sessions.filtered(lambda s: s.state == 'completed')),
            'cancelled_sessions': len(sessions.filtered(lambda s: s.state == 'cancelled')),
            'total_revenue': sum(sessions.mapped('total_cost')),
            'average_rating': sessions.filtered(lambda s: s.rating).mapped('rating') and 
                             sum(int(s.rating) for s in sessions.filtered(lambda s: s.rating)) / 
                             len(sessions.filtered(lambda s: s.rating)) or 0,
            'most_popular_service': self._get_most_popular_service(sessions),
            'busiest_groomer': self._get_busiest_groomer(sessions),
            'revenue_by_service': self._get_revenue_by_service(sessions),
            'sessions_by_month': self._get_sessions_by_month(sessions),
        }

    def _get_most_popular_service(self, sessions):
        """Get most popular grooming service"""
        service_counts = {}
        for session in sessions.filtered(lambda s: s.service_id):
            service_name = session.service_id.name
            service_counts[service_name] = service_counts.get(service_name, 0) + 1
        return max(service_counts.items(), key=lambda x: x[1]) if service_counts else None

    def _get_busiest_groomer(self, sessions):
        """Get busiest groomer"""
        groomer_counts = {}
        for session in sessions.filtered(lambda s: s.groomer_id):
            groomer_name = session.groomer_id.name
            groomer_counts[groomer_name] = groomer_counts.get(groomer_name, 0) + 1
        return max(groomer_counts.items(), key=lambda x: x[1]) if groomer_counts else None

    def _get_revenue_by_service(self, sessions):
        """Get revenue breakdown by service"""
        revenue_by_service = {}
        for session in sessions.filtered(lambda s: s.service_id and s.state == 'completed'):
            service_name = session.service_id.name
            revenue_by_service[service_name] = revenue_by_service.get(service_name, 0) + session.total_cost
        return revenue_by_service

    def _get_sessions_by_month(self, sessions):
        """Get session count by month"""
        monthly_counts = {}
        for session in sessions:
            if session.appointment_datetime:
                month_key = session.appointment_datetime.strftime('%Y-%m')
                monthly_counts[month_key] = monthly_counts.get(month_key, 0) + 1
        return monthly_counts

    # Advanced Workflow Actions
    def action_send_grooming_reminder(self):
        """Send grooming reminder to pet owner"""
        for session in self:
            if session.pet_id.owner_id:
                # Create activity for reminder
                self.env['mail.activity'].create({
                    'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                    'summary': f'Grooming Reminder: {session.service_id.name}',
                    'note': f'Reminder: {session.pet_id.name} has a grooming appointment scheduled for {session.appointment_datetime.strftime("%B %d, %Y at %I:%M %p")}',
                    'user_id': self.env.user.id,
                    'res_id': session.pet_id.owner_id.id,
                    'res_model_id': self.env.ref('base.model_res_partner').id,
                })

    def action_reschedule_session(self):
        """Action to reschedule grooming session"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Reschedule Grooming Session',
            'res_model': 'pet.grooming.session',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
            'context': {'default_appointment_datetime': False}
        }

    def action_create_follow_up_appointment(self):
        """Create a follow-up grooming appointment"""
        for session in self:
            if session.pet_id:
                # Create new grooming session
                follow_up_session = self.create({
                    'pet_id': session.pet_id.id,
                    'service_id': session.service_id.id,
                    'groomer_id': session.groomer_id.id if session.groomer_id else False,
                    'appointment_datetime': session.appointment_datetime + timedelta(days=30),  # 30 days later
                    'special_requests': f'Follow-up appointment for {session.service_id.name}',
                    'state': 'draft',
                })
                return {
                    'type': 'ir.actions.act_window',
                    'name': 'Follow-up Grooming Session',
                    'res_model': 'pet.grooming.session',
                    'view_mode': 'form',
                    'res_id': follow_up_session.id,
                    'target': 'current',
                }

    def action_export_grooming_report(self):
        """Export grooming session report"""
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/pet.grooming.session/{self.id}/grooming_report.pdf',
            'target': 'new',
        }

    # Integration Methods
    def action_link_to_appointment(self):
        """Link grooming session to pet appointment"""
        for session in self:
            # Create or link to existing appointment
            appointment = self.env['pet.appointment'].create({
                'pet_id': session.pet_id.id,
                'start_datetime': session.appointment_datetime,
                'end_datetime': session.appointment_datetime + timedelta(minutes=session.duration_minutes or 60),
                'type': 'grooming',
                'title': f'Grooming: {session.service_id.name}',
                'notes': session.notes,
                'resource_id': session.groomer_id.id if session.groomer_id else False,
                'state': 'confirmed',
            })
            return {
                'type': 'ir.actions.act_window',
                'name': 'Linked Appointment',
                'res_model': 'pet.appointment',
                'view_mode': 'form',
                'res_id': appointment.id,
                'target': 'current',
            }

    def action_add_to_medical_history(self):
        """Add grooming session to pet's medical history"""
        for session in self:
            if session.pet_id and session.behavior_notes:
                # Create medical visit record for grooming notes
                medical_visit = self.env['pet.medical.visit'].create({
                    'pet_id': session.pet_id.id,
                    'visit_date': session.appointment_datetime.date(),
                    'visit_type': 'grooming_notes',
                    'diagnosis': f'Grooming Session: {session.service_id.name}',
                    'treatment': session.behavior_notes,
                    'notes': f'Grooming session notes: {session.notes}',
                    'veterinarian_id': session.groomer_id.id if session.groomer_id else False,
                })
