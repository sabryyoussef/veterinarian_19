from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import timedelta

class PetTrainingProgram(models.Model):
    _name = 'pet.training.program'
    _description = 'Training Program'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string="Name", required=True, tracking=True, help="Training program name")
    code = fields.Char(string="Code", readonly=True, copy=False, index=True, default=lambda s: _('New'), help="Unique program code")
    description = fields.Text(string="Description", help="Detailed description of the training program")
    
    level = fields.Selection([
        ('beginner', 'Beginner'),
        ('basic', 'Basic'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
        ('expert', 'Expert')
    ], string="Level", required=True, tracking=True, help="Training difficulty level")
    
    category = fields.Selection([
        ('obedience', 'Obedience Training'),
        ('behavioral', 'Behavioral Training'),
        ('socialization', 'Socialization'),
        ('agility', 'Agility Training'),
        ('therapy', 'Therapy Training'),
        ('service', 'Service Dog Training'),
        ('protection', 'Protection Training'),
        ('tricks', 'Trick Training'),
        ('puppy', 'Puppy Training'),
        ('senior', 'Senior Dog Training')
    ], string="Category", required=True, tracking=True, help="Training program category")
    
    duration_sessions = fields.Integer(string="Duration Sessions", required=True, tracking=True, help="Number of sessions in the program")
    session_duration_minutes = fields.Integer(string="Session Duration (minutes)", default=60, help="Duration of each session in minutes")
    total_duration_display = fields.Char(string="Total Duration", compute='_compute_total_duration', store=True, help="Total program duration")
    
    target_species_ids = fields.Many2many('pet.species', string='Target Species', help="Species this training program is designed for")
    target_species_display = fields.Char(string="Target Species Display", compute='_compute_target_species_display', store=True, help="Display format for target species")
    
    min_age_months = fields.Integer(string="Min Age (months)", default=3, help="Minimum age in months")
    max_age_months = fields.Integer(string="Max Age (months)", help="Maximum age in months (0 = no limit)")
    
    prerequisites = fields.Text(string="Prerequisites", help="Prerequisites or requirements for enrollment")
    learning_objectives = fields.Text(string="Learning Objectives", help="What pets will learn in this program")
    training_methods = fields.Text(string="Training Methods", help="Training methods and techniques used")
    
    equipment_needed = fields.Text(string="Equipment Needed", help="Equipment required for this program")
    space_requirements = fields.Text(string="Space Requirements", help="Space and facility requirements")
    
    max_class_size = fields.Integer(string="Max Class Size", default=8, help="Maximum number of pets per class")
    min_class_size = fields.Integer(string="Min Class Size", default=1, help="Minimum number of pets to start class")
    
    base_price = fields.Monetary(string="Base Price", currency_field='currency_id', help="Base price for the complete program")
    currency_id = fields.Many2one('res.currency', string="Currency", default=lambda self: self.env.company.currency_id)
    
    # Analytics Fields
    enrollment_count = fields.Integer(string="Enrollment Count", compute='_compute_enrollment_stats', store=True, help="Number of pets enrolled")
    completion_rate = fields.Float(string="Completion Rate", compute='_compute_enrollment_stats', store=True, help="Program completion rate (%)")
    average_rating = fields.Float(string="Average Rating", compute='_compute_rating_stats', store=True, help="Average program rating")
    total_revenue = fields.Monetary(string="Total Revenue", compute='_compute_revenue_stats', store=True, currency_field='currency_id', help="Total revenue generated")
    
    # Related Records
    session_ids = fields.One2many('pet.training.session', 'program_id', string='Training Sessions')
    
    active = fields.Boolean(string="Active", default=True, tracking=True, help="Is this program active?")
    company_id = fields.Many2one('res.company', string="Company", required=True, default=lambda s: s.env.company)
    
    @api.depends('duration_sessions', 'session_duration_minutes')
    def _compute_total_duration(self):
        for record in self:
            if record.duration_sessions and record.session_duration_minutes:
                total_minutes = record.duration_sessions * record.session_duration_minutes
                hours = total_minutes // 60
                minutes = total_minutes % 60
                if hours > 0:
                    record.total_duration_display = f"{hours}h {minutes}m" if minutes > 0 else f"{hours}h"
                else:
                    record.total_duration_display = f"{minutes}m"
            else:
                record.total_duration_display = "Not specified"
    
    @api.depends('target_species_ids')
    def _compute_target_species_display(self):
        for record in self:
            if record.target_species_ids:
                species_names = record.target_species_ids.mapped('name')
                if len(species_names) == 1:
                    record.target_species_display = species_names[0]
                elif len(species_names) == 2:
                    record.target_species_display = f"{species_names[0]} & {species_names[1]}"
                else:
                    record.target_species_display = f"{species_names[0]} + {len(species_names) - 1} more"
            else:
                record.target_species_display = "All Species"
    
    @api.depends('session_ids')
    def _compute_enrollment_stats(self):
        for record in self:
            sessions = record.session_ids
            # Count unique pets enrolled in this program
            unique_pets = sessions.mapped('pet_id')
            record.enrollment_count = len(unique_pets)
            if sessions:
                completed_sessions = sessions.filtered(lambda s: s.state == 'done')
                record.completion_rate = (len(completed_sessions) / len(sessions)) * 100
            else:
                record.completion_rate = 0.0
    
    @api.depends('session_ids')
    def _compute_rating_stats(self):
        for record in self:
            # For now, we'll use a placeholder since the session model doesn't have rating yet
            # This can be enhanced when we add rating to the session model
            record.average_rating = 0.0
    
    @api.depends('session_ids')
    def _compute_revenue_stats(self):
        for record in self:
            # For now, we'll use base_price * enrollment_count as revenue estimate
            # This can be enhanced when we add proper cost tracking to sessions
            record.total_revenue = record.base_price * record.enrollment_count
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code', _('New')) == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('pet.training.program') or _('New')
        return super().create(vals_list)
    
    @api.constrains('duration_sessions', 'session_duration_minutes', 'min_age_months', 'max_age_months')
    def _check_program_constraints(self):
        for record in self:
            if record.duration_sessions <= 0:
                raise ValidationError(_('Duration sessions must be greater than 0.'))
            if record.session_duration_minutes <= 0:
                raise ValidationError(_('Session duration must be greater than 0 minutes.'))
            if record.min_age_months < 0:
                raise ValidationError(_('Minimum age cannot be negative.'))
            if record.max_age_months and record.max_age_months < record.min_age_months:
                raise ValidationError(_('Maximum age must be greater than minimum age.'))
    
    def name_get(self):
        """Custom name_get to show program name and level in Many2one selection"""
        result = []
        for rec in self:
            name = f"{rec.name} ({rec.level})"
            result.append((rec.id, name))
        return result

    def action_view_sessions(self):
        """Action to view all training sessions for this program"""
        return {
            'type': 'ir.actions.act_window',
            'name': f'Training Sessions - {self.name}',
            'res_model': 'pet.training.session',
            'view_mode': 'kanban,list,form',
            'domain': [('program_id', '=', self.id)],
            'context': {'default_program_id': self.id}
        }
    
    def action_view_enrollments(self):
        """Action to view all training sessions for this program (as enrollments)"""
        return {
            'type': 'ir.actions.act_window',
            'name': f'Training Sessions - {self.name}',
            'res_model': 'pet.training.session',
            'view_mode': 'kanban,list,form',
            'domain': [('program_id', '=', self.id)],
            'context': {'default_program_id': self.id}
        }
    
    def action_duplicate_program(self):
        """Action to duplicate this training program"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Duplicate Training Program',
            'res_model': 'pet.training.program',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_name': f"{self.name} (Copy)",
                'default_level': self.level,
                'default_category': self.category,
                'default_duration_sessions': self.duration_sessions,
                'default_session_duration_minutes': self.session_duration_minutes,
                'default_target_species_ids': [(6, 0, self.target_species_ids.ids)],
                'default_min_age_months': self.min_age_months,
                'default_max_age_months': self.max_age_months,
                'default_prerequisites': self.prerequisites,
                'default_learning_objectives': self.learning_objectives,
                'default_training_methods': self.training_methods,
                'default_equipment_needed': self.equipment_needed,
                'default_space_requirements': self.space_requirements,
                'default_max_class_size': self.max_class_size,
                'default_min_class_size': self.min_class_size,
                'default_base_price': self.base_price,
            }
        }

class PetTrainingSession(models.Model):
    _name = 'pet.training.session'
    _description = 'Training Session'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'session_datetime desc'

    name = fields.Char(string="Name", readonly=True, copy=False, index=True, default=lambda s: _('New'), help="Session reference")
    
    # Core Fields
    pet_id = fields.Many2one('pet.pet', string="Pet", required=True, ondelete='cascade', tracking=True, help="Pet being trained")
    appointment_id = fields.Many2one('pet.appointment', string='Appointment', help="Related appointment")
    program_id = fields.Many2one('pet.training.program', string="Program", required=True, tracking=True, help="Training program")
    trainer_id = fields.Many2one(
        'res.partner',
        string="Trainer",
        domain=lambda self: [('id', '=', self.env.user.partner_id.id)] if self.env.user.has_group('pet_management.group_pet_staff_training') else [('is_company','=',False)],
        tracking=True, help="Trainer conducting the session (staff partner)"
    )
    
    # Session Details
    session_datetime = fields.Datetime(string="Session Date/Time", required=True, tracking=True, help="Scheduled session date and time")
    actual_start_datetime = fields.Datetime(string="Actual Start", help="Actual session start time")
    actual_end_datetime = fields.Datetime(string="Actual End", help="Actual session end time")
    duration_minutes = fields.Integer(string="Duration (minutes)", compute='_compute_duration', store=True, help="Session duration in minutes")
    duration_display = fields.Char(string="Duration Display", compute='_compute_duration', store=True, help="Session duration display")
    
    # Session Content
    session_notes = fields.Text(string="Session Notes", help="General session notes and observations")
    progress_notes = fields.Text(string="Progress Notes", help="Pet's progress and improvements")
    behavior_notes = fields.Text(string="Behavior Notes", help="Behavioral observations during session")
    training_exercises = fields.Text(string="Training Exercises", help="Exercises performed during session")
    homework_assigned = fields.Text(string="Homework Assigned", help="Homework or practice assigned to pet owner")
    
    # Session Management
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('no_show', 'No Show')
    ], string="State", default='draft', tracking=True, help="Session status")
    
    state_color = fields.Integer(compute='_compute_state_color', string='State Color', store=True)
    
    # Session Evaluation
    pet_performance = fields.Selection([
        ('excellent', 'Excellent'),
        ('good', 'Good'),
        ('fair', 'Fair'),
        ('poor', 'Poor'),
        ('needs_work', 'Needs Work')
    ], string="Pet Performance", help="Pet's performance during session")
    
    owner_participation = fields.Selection([
        ('excellent', 'Excellent'),
        ('good', 'Good'),
        ('fair', 'Fair'),
        ('poor', 'Poor')
    ], string="Owner Participation", help="Owner's participation level")
    
    session_rating = fields.Selection([
        ('1', 'Very Poor'),
        ('2', 'Poor'),
        ('3', 'Average'),
        ('4', 'Good'),
        ('5', 'Excellent')
    ], string='Session Rating', help="Overall session rating")
    
    feedback_notes = fields.Text(string="Feedback Notes", help="Trainer feedback and recommendations")
    owner_feedback = fields.Text(string="Owner Feedback", help="Owner feedback about the session")
    
    # Session Logistics
    location = fields.Char(string="Location", help="Training location")
    weather_conditions = fields.Selection([
        ('sunny', 'Sunny'),
        ('cloudy', 'Cloudy'),
        ('rainy', 'Rainy'),
        ('snowy', 'Snowy'),
        ('windy', 'Windy'),
        ('hot', 'Hot'),
        ('cold', 'Cold')
    ], string="Weather Conditions", help="Weather conditions during session")
    
    equipment_used = fields.Text(string="Equipment Used", help="Equipment used during session")
    special_requirements = fields.Text(string="Special Requirements", help="Special requirements or accommodations")
    
    # Analytics Fields
    days_since_session = fields.Integer(string="Days Since Session", compute='_compute_days_since_session', store=True, help="Days since session")
    is_today = fields.Boolean(string="Is Today", compute='_compute_is_today', search='_search_is_today', help="Is session today?")
    is_overdue = fields.Boolean(string="Is Overdue", compute='_compute_is_overdue', search='_search_is_overdue', help="Is session overdue?")
    is_upcoming = fields.Boolean(string="Is Upcoming", compute='_compute_is_upcoming', search='_search_is_upcoming', help="Is session upcoming?")
    
    # Related Information
    owner_id = fields.Many2one('res.partner', string="Owner", related='pet_id.owner_id', store=True, help="Pet owner")
    program_level = fields.Selection(string="Program Level", related='program_id.level', store=True, help="Program difficulty level")
    program_category = fields.Selection(string="Program Category", related='program_id.category', store=True, help="Program category")
    
    # Cost and Payment
    session_cost = fields.Monetary(string="Session Cost", currency_field='currency_id', help="Cost for this session")
    currency_id = fields.Many2one('res.currency', string="Currency", default=lambda self: self.env.company.currency_id)
    payment_status = fields.Selection([
        ('pending', 'Pending'),
        ('partial', 'Partial'),
        ('paid', 'Paid'),
        ('refunded', 'Refunded')
    ], string="Payment Status", default='pending', tracking=True, help="Payment status")
    
    # Company and Integration
    company_id = fields.Many2one('res.company', string="Company", required=True, default=lambda s: s.env.company)
    
    @api.depends('session_datetime')
    def _compute_days_since_session(self):
        today = fields.Date.context_today(self)
        for record in self:
            if record.session_datetime:
                session_date = fields.Date.to_date(record.session_datetime)
                record.days_since_session = (today - session_date).days
            else:
                record.days_since_session = 0
    
    @api.depends('session_datetime')
    def _compute_is_today(self):
        today = fields.Date.context_today(self)
        for record in self:
            if record.session_datetime:
                session_date = fields.Date.to_date(record.session_datetime)
                record.is_today = session_date == today
            else:
                record.is_today = False
    
    @api.depends('session_datetime', 'state')
    def _compute_is_overdue(self):
        now = fields.Datetime.now()
        for record in self:
            if record.session_datetime and record.state in ['draft', 'confirmed']:
                record.is_overdue = record.session_datetime < now
            else:
                record.is_overdue = False
    
    @api.depends('session_datetime', 'state')
    def _compute_is_upcoming(self):
        now = fields.Datetime.now()
        for record in self:
            if record.session_datetime and record.state in ['draft', 'confirmed']:
                record.is_upcoming = record.session_datetime > now
            else:
                record.is_upcoming = False
    
    @api.depends('actual_start_datetime', 'actual_end_datetime')
    def _compute_duration(self):
        for record in self:
            if record.actual_start_datetime and record.actual_end_datetime:
                duration = record.actual_end_datetime - record.actual_start_datetime
                record.duration_minutes = int(duration.total_seconds() / 60)
                
                hours = record.duration_minutes // 60
                minutes = record.duration_minutes % 60
                if hours > 0:
                    record.duration_display = f"{hours}h {minutes}m" if minutes > 0 else f"{hours}h"
                else:
                    record.duration_display = f"{minutes}m"
            else:
                record.duration_minutes = 0
                record.duration_display = "Not recorded"

    @api.depends('state')
    def _compute_state_color(self):
        color_map = {
            'draft': 1,        # red
            'confirmed': 2,    # orange
            'in_progress': 3,  # yellow
            'completed': 4,    # green
            'cancelled': 0,    # grey
            'no_show': 0,      # grey
        }
        for rec in self:
            rec.state_color = color_map.get(rec.state, 0)

    @api.model_create_multi
    def create(self, vals_list):
        # Get default training session duration from settings
        icp = self.env['ir.config_parameter'].sudo()
        default_duration = float(icp.get_param('pet_management.training_session_duration', 1.0))
        
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('pet.training.session') or _('New')
            
            # Apply default duration if not specified and we have session time
            if 'session_datetime' in vals and 'actual_end_datetime' not in vals:
                from datetime import datetime, timedelta
                start_dt = vals['session_datetime']
                if isinstance(start_dt, str):
                    start_dt = datetime.fromisoformat(start_dt.replace('Z', '+00:00'))
                vals['actual_end_datetime'] = start_dt + timedelta(hours=default_duration)
                
        return super().create(vals_list)

    @api.constrains('session_datetime', 'actual_start_datetime', 'actual_end_datetime')
    def _check_datetime_constraints(self):
        for record in self:
            if record.session_datetime and record.session_datetime < fields.Datetime.now() and record.state == 'draft':
                if not self.env.context.get('install_mode') and not self.env.context.get('import_file'):
                    raise ValidationError(_('Cannot schedule training session in the past.'))
            
            if record.actual_start_datetime and record.actual_end_datetime:
                if record.actual_start_datetime >= record.actual_end_datetime:
                    raise ValidationError(_('Actual start time must be before end time.'))

    @api.model
    def _search_is_today(self, operator, value):
        today = fields.Date.context_today(self)
        if operator == '=' and value is True:
            return [('session_datetime', '>=', today.strftime('%Y-%m-%d 00:00:00')),
                    ('session_datetime', '<=', today.strftime('%Y-%m-%d 23:59:59'))]
        elif operator == '=' and value is False:
            return ['|', '|',
                    ('session_datetime', '<', today.strftime('%Y-%m-%d 00:00:00')),
                    ('session_datetime', '>', today.strftime('%Y-%m-%d 23:59:59')),
                    ('session_datetime', '=', False)]
        return []

    @api.model
    def _search_is_overdue(self, operator, value):
        now = fields.Datetime.now()
        if operator == '=' and value is True:
            return [('session_datetime', '<', now),
                    ('state', 'in', ['draft', 'confirmed'])]
        elif operator == '=' and value is False:
            return ['|', '|',
                    ('session_datetime', '>=', now),
                    ('state', 'not in', ['draft', 'confirmed']),
                    ('session_datetime', '=', False)]
        return []

    @api.model
    def _search_is_upcoming(self, operator, value):
        now = fields.Datetime.now()
        if operator == '=' and value is True:
            return [('session_datetime', '>', now),
                    ('state', 'in', ['draft', 'confirmed'])]
        elif operator == '=' and value is False:
            return ['|', '|',
                    ('session_datetime', '<=', now),
                    ('state', 'not in', ['draft', 'confirmed']),
                    ('session_datetime', '=', False)]
        return []

    # Workflow Actions
    def action_confirm_session(self):
        """Confirm the training session"""
        for session in self:
            session.state = 'confirmed'
            session.message_post(body=_('Training session confirmed.'))

    def action_start_session(self):
        """Start the training session"""
        for session in self:
            session.state = 'in_progress'
            session.actual_start_datetime = fields.Datetime.now()
            session.message_post(body=_('Training session started.'))

    def action_complete_session(self):
        """Complete the training session"""
        for session in self:
            session.state = 'completed'
            session.actual_end_datetime = fields.Datetime.now()
            session.message_post(body=_('Training session completed.'))

    def action_cancel_session(self):
        """Cancel the training session"""
        for session in self:
            session.state = 'cancelled'
            session.message_post(body=_('Training session cancelled.'))

    def action_no_show(self):
        """Mark session as no show"""
        for session in self:
            session.state = 'no_show'
            session.message_post(body=_('Pet owner did not show up for session.'))

    def action_reschedule_session(self):
        """Reschedule the training session"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Reschedule Training Session',
            'res_model': 'pet.training.session',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
            'context': {'default_session_datetime': False}
        }

    def name_get(self):
        """Custom name_get to show pet name and program name in Many2one selection"""
        result = []
        for rec in self:
            pet_name = rec.pet_id.name if rec.pet_id else 'Unknown Pet'
            program_name = rec.program_id.name if rec.program_id else 'Unknown Program'
            name = f"{pet_name} - {program_name}"
            result.append((rec.id, name))
        return result

    def action_view_pet(self):
        """View the pet details"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Pet Details',
            'res_model': 'pet.pet',
            'view_mode': 'form',
            'res_id': self.pet_id.id,
            'target': 'current',
        }

    def action_view_program(self):
        """View the training program details"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Training Program Details',
            'res_model': 'pet.training.program',
            'view_mode': 'form',
            'res_id': self.program_id.id,
            'target': 'current',
        }
