from datetime import timedelta
from odoo import models, fields, api

class PetVaccination(models.Model):
    _name = 'pet.vaccination'
    _description = 'Pet Vaccination'
    _order = 'date_administered desc'

    pet_id = fields.Many2one('pet.pet', required=True, ondelete='cascade', 
                            help="The pet that received the vaccination")
    appointment_id = fields.Many2one('pet.appointment', string='Appointment', help="Related appointment")
    vaccine_id = fields.Many2one('pet.vaccine', required=True, ondelete='restrict',
                                help="The vaccine administered to the pet")
    date_administered = fields.Date(string="Date Administered", required=True, 
                                  help="Date when the vaccination was given")
    dose_ml = fields.Float(string="Dose (ml)", 
                          help="Amount of vaccine administered in milliliters")
    vet_id = fields.Many2one(
        'res.partner', string="Veterinarian",
        domain=lambda self: [('id', '=', self.env.user.partner_id.id)] if self.env.user.has_group('pet_management.group_pet_staff_health') else [],
        help="Veterinarian who administered the vaccination"
    )
    next_due_date = fields.Date(compute='_compute_next_due', store=True, index=True,
                               help="Next scheduled vaccination date")
    state = fields.Selection([
        ('scheduled', 'Scheduled'),
        ('administered', 'Administered'),
        ('cancelled', 'Cancelled'),
        ('overdue', 'Overdue')
    ], default='administered', required=True, 
    help="Current status of the vaccination")
    
    # New fields for enhanced functionality
    vaccination_type = fields.Selection([
        ('initial', 'Initial'),
        ('booster', 'Booster'),
        ('annual', 'Annual'),
        ('emergency', 'Emergency')
    ], default='initial', required=True,
    help="Type of vaccination being administered")
    
    batch_number = fields.Char(string="Batch Number",
                              help="Manufacturer batch number for tracking")
    expiration_date = fields.Date(help="Expiration date of the vaccine batch")
    cost = fields.Monetary(string="Cost", currency_field='currency_id',
                          help="Cost of the vaccination")
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    payment_status = fields.Selection([
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('partial', 'Partially Paid'),
        ('cancelled', 'Cancelled')
    ], default='pending', 
    help="Payment status for the vaccination")
    
    side_effects = fields.Text(help="Any side effects observed after vaccination")
    notes = fields.Text(help="Additional notes about the vaccination")
    
    # Computed fields
    days_since_vaccination = fields.Integer(compute='_compute_days_since_vaccination',
                                          help="Number of days since vaccination")
    is_overdue = fields.Boolean(compute='_compute_is_overdue', search='_search_is_overdue',
                               help="True if vaccination is overdue")
    state_color = fields.Integer(compute='_compute_state_color', string='State Color', store=True)
    overdue_days = fields.Integer(compute='_compute_overdue_days',
                                help="Number of days overdue")

    @api.depends('date_administered', 'vaccination_type', 'vaccine_id.booster_interval_days')
    def _compute_next_due(self):
        for rec in self:
            if rec.date_administered:
                # Calculate next due date based on vaccination type
                if rec.vaccination_type == 'initial':
                    # Initial vaccinations typically need a booster in 3-4 weeks
                    rec.next_due_date = rec.date_administered + timedelta(days=21)
                elif rec.vaccination_type == 'booster':
                    # Booster shots typically need another booster in 1 year
                    rec.next_due_date = rec.date_administered + timedelta(days=365)
                elif rec.vaccination_type == 'annual':
                    # Annual vaccinations need renewal in 1 year
                    rec.next_due_date = rec.date_administered + timedelta(days=365)
                elif rec.vaccination_type == 'emergency':
                    # Emergency vaccinations may need follow-up based on vaccine type
                    if rec.vaccine_id.booster_interval_days:
                        rec.next_due_date = rec.date_administered + timedelta(days=rec.vaccine_id.booster_interval_days)
                    else:
                        # Default to 30 days for emergency vaccinations
                        rec.next_due_date = rec.date_administered + timedelta(days=30)
                else:
                    # Fallback to vaccine's default interval if available
                    if rec.vaccine_id.booster_interval_days:
                        rec.next_due_date = rec.date_administered + timedelta(days=rec.vaccine_id.booster_interval_days)
                    else:
                        rec.next_due_date = False
            else:
                rec.next_due_date = False

    @api.depends('date_administered')
    def _compute_days_since_vaccination(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.date_administered:
                rec.days_since_vaccination = (today - rec.date_administered).days
            else:
                rec.days_since_vaccination = 0

    @api.depends('next_due_date', 'state')
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.next_due_date and rec.state in ['scheduled', 'administered']:
                rec.is_overdue = rec.next_due_date < today
            else:
                rec.is_overdue = False

    @api.depends('next_due_date', 'is_overdue')
    def _compute_overdue_days(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.is_overdue and rec.next_due_date:
                rec.overdue_days = (today - rec.next_due_date).days
            else:
                rec.overdue_days = 0

    @api.depends('state', 'is_overdue')
    def _compute_state_color(self):
        for rec in self:
            if rec.is_overdue:
                rec.state_color = 1  # red
            elif rec.state == 'administered':
                rec.state_color = 4  # green
            elif rec.state == 'scheduled':
                rec.state_color = 2  # orange
            elif rec.state == 'cancelled':
                rec.state_color = 0  # grey
            else:
                rec.state_color = 0

    def _search_is_overdue(self, operator, value):
        today = fields.Date.context_today(self)
        if operator == '=' and value:
            return [('next_due_date', '<', today), ('state', 'in', ['scheduled', 'administered'])]
        elif operator == '=' and not value:
            return ['|', ('next_due_date', '>=', today), ('state', 'not in', ['scheduled', 'administered'])]
        return []

    # Action methods
    def action_mark_administered(self):
        for rec in self:
            rec.state = 'administered'

    def action_mark_cancelled(self):
        for rec in self:
            rec.state = 'cancelled'

    def action_reschedule(self):
        for rec in self:
            rec.state = 'scheduled'

    def name_get(self):
        """Custom name_get to show pet name and vaccine name in Many2one selection"""
        result = []
        for rec in self:
            pet_name = rec.pet_id.name if rec.pet_id else 'Unknown Pet'
            vaccine_name = rec.vaccine_id.name if rec.vaccine_id else 'Unknown Vaccine'
            name = f"{pet_name} - {vaccine_name}"
            result.append((rec.id, name))
        return result

    def action_view_pet(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Pet',
            'res_model': 'pet.pet',
            'res_id': self.pet_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_vaccine(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Vaccine',
            'res_model': 'pet.vaccine',
            'res_id': self.vaccine_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_send_notification(self):
        """Create and send notification for this vaccination"""
        for rec in self:
            # Determine notification type based on vaccination state
            if rec.state == 'scheduled':
                notification_type = 'vaccination_due'
                priority = 'high' if rec.is_overdue else 'medium'
                message = f"Reminder: {rec.pet_id.name}'s {rec.vaccine_id.name} vaccination is scheduled for {rec.date_administered}."
            elif rec.state == 'administered':
                notification_type = 'vaccination_due'
                priority = 'low'
                message = f"Confirmation: {rec.pet_id.name}'s {rec.vaccine_id.name} vaccination was administered on {rec.date_administered}. Next due: {rec.next_due_date}."
            else:
                notification_type = 'general'
                priority = 'low'
                message = f"Update: {rec.pet_id.name}'s {rec.vaccine_id.name} vaccination status is {rec.state}."
            
            # Create notification
            notification = self.env['pet.notification'].create({
                'name': f'Vaccination Notification - {rec.pet_id.name}',
                'pet_id': rec.pet_id.id,
                'notification_type': notification_type,
                'message': message,
                'priority': priority,
                'status': 'draft',
                'related_vaccination_id': rec.id,
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
        """Create a reminder notification for this vaccination"""
        for rec in self:
            if rec.state != 'scheduled':
                continue
                
            # Check if reminder already exists
            existing = self.env['pet.notification'].search([
                ('related_vaccination_id', '=', rec.id),
                ('notification_type', '=', 'vaccination_due'),
                ('status', 'in', ['draft', 'sent'])
            ])
            
            if not existing:
                notification = self.env['pet.notification'].create({
                    'name': f'Vaccination Reminder - {rec.pet_id.name}',
                    'pet_id': rec.pet_id.id,
                    'notification_type': 'vaccination_due',
                    'message': f"Reminder: {rec.pet_id.name}'s {rec.vaccine_id.name} vaccination is scheduled for {rec.date_administered}. Please ensure your pet is ready.",
                    'priority': 'high' if rec.is_overdue else 'medium',
                    'status': 'draft',
                    'related_vaccination_id': rec.id,
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

    # Legacy methods for backward compatibility
    def set_to_done(self):
        self.action_mark_administered()

    def set_to_cancel(self):
        self.action_mark_cancelled()
    
    def action_assign_current_user_as_vet(self):
        """Assign current user as veterinarian to this vaccination"""
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
        
        # Assign current user's partner as veterinarian
        self.vet_id = user.partner_id.id
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': f'Assigned {user.partner_id.name} as veterinarian to this vaccination',
                'type': 'success',
                'sticky': True,
            }
        }

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to auto-schedule booster vaccinations based on settings"""
        # Get vaccination settings
        icp = self.env['ir.config_parameter'].sudo()
        auto_schedule_boosters = icp.get_param('pet_management.auto_schedule_boosters') in (True, 'True', '1', 1)
        
        vaccinations = super().create(vals_list)
        
        # Auto-schedule booster vaccinations if enabled
        if auto_schedule_boosters:
            for vaccination in vaccinations:
                if vaccination.vaccine_id and vaccination.vaccine_id.booster_interval_days:
                    # Create a booster vaccination record
                    booster_vals = {
                        'pet_id': vaccination.pet_id.id,
                        'vaccine_id': vaccination.vaccine_id.id,
                        'date_administered': vaccination.date_administered + timedelta(days=vaccination.vaccine_id.booster_interval_days),
                        'dose_ml': vaccination.dose_ml,
                        'vet_id': vaccination.vet_id.id if vaccination.vet_id else False,
                        'vaccination_type': 'booster',
                        'state': 'scheduled',
                        'batch_number': vaccination.batch_number,
                        'expiration_date': vaccination.expiration_date,
                        'cost': vaccination.cost,
                        'payment_status': 'pending',
                    }
                    self.create(booster_vals)
        
        return vaccinations
