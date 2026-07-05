from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class PetBoardingStay(models.Model):
    _name = 'pet.boarding.stay'
    _description = 'Boarding Stay'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'check_in desc'

    pet_id = fields.Many2one('pet.pet', string="Pet", required=True, ondelete='cascade', index=True, tracking=True, help="The pet for this boarding stay")
    appointment_id = fields.Many2one('pet.appointment', string='Appointment', help="Related appointment")
    owner_id = fields.Many2one(related='pet_id.owner_id', string="Owner", store=True, readonly=True, help="Pet owner")
    kennel_id = fields.Many2one('pet.kennel', string="Kennel", required=True, ondelete='restrict', tracking=True, help="Assigned kennel for the stay")
    check_in = fields.Datetime(string="Check In", required=True, tracking=True, help="Check-in date and time")
    check_out = fields.Datetime(string="Check Out", required=True, tracking=True, help="Check-out date and time")
    reason = fields.Char(string="Reason", required=True, tracking=True, help="Reason for boarding stay")
    
    # Enhanced Fields
    staff_id = fields.Many2one(
        'res.partner', string="Staff",
        domain=lambda self: [('id', '=', self.env.user.partner_id.id)] if self.env.user.has_group('pet_management.group_pet_staff_boarding') else [('is_company','=',False)],
        help="Assigned caretaker/staff member"
    )
    cost_per_day = fields.Float(string="Cost Per Day", related='kennel_id.daily_rate', store=True, help="Daily boarding cost from kennel")
    external_costs = fields.Float(string="External Costs", default=0.0, help="Additional external costs (medications, special services, etc.)")
    external_cost_label = fields.Char(string="External Cost Label", help="Description of external costs")
    total_cost = fields.Float(string="Total Cost", compute='_compute_total_cost', store=True, help="Total boarding cost including external costs")
    payment_status = fields.Selection([
        ('pending', 'Pending'), ('paid', 'Paid'), ('partial', 'Partial'), ('cancelled', 'Cancelled')
    ], string='Payment Status', default='pending', help="Payment status for the stay")
    
    # Care Instructions
    feeding_notes = fields.Text(string="Feeding Notes", help="Special feeding instructions and dietary requirements")
    walk_schedule = fields.Text(string="Walk Schedule", help="Walking schedule and exercise requirements")
    incident_log = fields.Text(string="Incident Log", help="Incidents and observations during the stay")
    special_instructions = fields.Text(string="Special Instructions", help="Special care instructions from the owner")
    health_notes = fields.Text(string="Health Notes", help="Health observations during the stay")
    
    # Contact Information
    emergency_contact = fields.Char(string="Emergency Contact", help="Emergency contact during the stay")
    pickup_person = fields.Char(string="Pickup Person", help="Person authorized to pick up the pet")
    
    # Enhanced State
    state = fields.Selection([
        ('draft', 'Draft'), ('confirmed', 'Confirmed'), ('checked_in', 'Checked In'), 
        ('checked_out', 'Checked Out'), ('cancelled', 'Cancelled')
    ], string="Status", default='draft', index=True, tracking=True, help="Current status of the boarding stay")
    
    company_id = fields.Many2one('res.company', string="Company", required=True, default=lambda s: s.env.company, help="Company this stay belongs to")

    # Enhanced Computed Fields
    duration_days = fields.Float(string="Duration (Days)", compute='_compute_duration', store=True, help="Duration of stay in days")
    duration_display = fields.Char(string="Duration Display", compute='_compute_duration', store=True, help="Duration in readable format")
    days_remaining = fields.Integer(string="Days Remaining", compute='_compute_days_remaining', store=False, help="Days remaining until check-out")
    is_overdue = fields.Boolean(string="Is Overdue", compute='_compute_is_overdue', search='_search_is_overdue', store=False, help="Whether stay is overdue")
    is_current = fields.Boolean(string="Is Current", compute='_compute_is_current', store=False, help="Whether pet is currently boarding")
    state_color = fields.Integer(compute='_compute_state_color', string='State Color', store=True, help="Color index for status display")

    @api.depends('check_in', 'check_out')
    def _compute_duration(self):
        for rec in self:
            if rec.check_in and rec.check_out:
                delta = rec.check_out - rec.check_in
                rec.duration_days = delta.total_seconds() / 86400.0
                days = int(rec.duration_days)
                hours = int((rec.duration_days - days) * 24)
                if days > 0:
                    rec.duration_display = f"{days}d {hours}h" if hours > 0 else f"{days}d"
                else:
                    rec.duration_display = f"{hours}h"
            else:
                rec.duration_days = 0.0
                rec.duration_display = "0d"

    @api.depends('check_out', 'state')
    def _compute_days_remaining(self):
        today = fields.Datetime.now()
        for rec in self:
            if rec.check_out and rec.state in ['confirmed', 'checked_in']:
                delta = rec.check_out - today
                rec.days_remaining = max(0, delta.days)
            else:
                rec.days_remaining = 0

    @api.depends('check_out', 'state')
    def _compute_is_overdue(self):
        today = fields.Datetime.now()
        for rec in self:
            rec.is_overdue = (
                rec.check_out and 
                rec.check_out < today and 
                rec.state in ['confirmed', 'checked_in']
            )

    @api.depends('check_in', 'check_out', 'state')
    def _compute_is_current(self):
        today = fields.Datetime.now()
        for rec in self:
            rec.is_current = (
                rec.check_in and 
                rec.check_out and 
                rec.check_in <= today and 
                rec.check_out >= today and 
                rec.state == 'checked_in'
            )

    @api.depends('duration_days', 'cost_per_day', 'kennel_id.daily_rate', 'external_costs')
    def _compute_total_cost(self):
        for rec in self:
            base_cost = 0.0
            if rec.duration_days and rec.cost_per_day:
                base_cost = rec.duration_days * rec.cost_per_day
            
            external_cost = rec.external_costs or 0.0
            rec.total_cost = base_cost + external_cost

    @api.constrains('check_in', 'check_out')
    def _check_dates(self):
        for rec in self:
            if rec.check_in and rec.check_out and rec.check_out <= rec.check_in:
                raise ValidationError(_('Check-out must be after check-in.'))

    @api.constrains("kennel_id", "check_in", "check_out")
    def _check_overlap(self):
        for rec in self:
            overlap = self.search([
                ("id", "!=", rec.id),
                ("kennel_id", "=", rec.kennel_id.id),
                ("check_in", "<=", rec.check_out),
                ("check_out", ">=", rec.check_in),
            ], limit=1)
            if overlap:
                raise ValidationError("This kennel is already booked during the selected period.")

    @api.depends('state')
    def _compute_state_color(self):
        color_map = {
            'draft': 1,        # blue
            'confirmed': 2,    # orange
            'checked_in': 3,   # green
            'checked_out': 4,  # green
            'cancelled': 0,    # grey
        }
        for rec in self:
            rec.state_color = color_map.get(rec.state, 1)

    def _search_is_overdue(self, operator, value):
        """Search method for is_overdue field"""
        now = fields.Datetime.now()
        if operator == '=' and value:
            return [
                ('check_out', '<', now),
                ('state', 'in', ['confirmed', 'checked_in'])
            ]
        elif operator == '=' and not value:
            return [
                '|',
                ('check_out', '=', False),
                '|',
                ('check_out', '>=', now),
                ('state', 'not in', ['confirmed', 'checked_in'])
            ]
        return []

    def set_to_confirmed(self):
        for rec in self:
            rec.state = 'confirmed'

    def set_to_checked_in(self):
        for rec in self:
            rec.state = 'checked_in'

    def set_to_checked_out(self):
        for rec in self:
            rec.state = 'checked_out'

    def set_to_cancel(self):
        for rec in self:
            rec.state = 'cancelled'

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

    def name_get(self):
        """Custom name_get to show pet name and reason in Many2one selection"""
        result = []
        for rec in self:
            name = f"{rec.pet_id.name if rec.pet_id else 'Unknown Pet'} - {rec.reason or 'No Reason'}"
            result.append((rec.id, name))
        return result

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to trigger kennel occupancy update and apply boarding settings"""
        # Get boarding settings
        icp = self.env['ir.config_parameter'].sudo()
        check_out_advance = int(icp.get_param('pet_management.boarding_check_out_advance', 2))
        
        for vals in vals_list:
            # Apply check-in advance hours if not specified
            if 'check_in' in vals and 'check_out' not in vals:
                from datetime import datetime, timedelta
                check_in_dt = vals['check_in']
                if isinstance(check_in_dt, str):
                    check_in_dt = datetime.fromisoformat(check_in_dt.replace('Z', '+00:00'))
                # Default check-out is check-in + 1 day + advance hours
                vals['check_out'] = check_in_dt + timedelta(days=1, hours=check_out_advance)
                
        results = super().create(vals_list)
        for result in results:
            if result.kennel_id:
                result.kennel_id._compute_occupancy()
                result.kennel_id._compute_availability()
        return results

    def write(self, vals):
        """Override write to trigger kennel occupancy update"""
        result = super().write(vals)
        # Trigger update for affected kennels
        for rec in self:
            if rec.kennel_id:
                rec.kennel_id._compute_occupancy()
                rec.kennel_id._compute_availability()
        return result

    def unlink(self):
        """Override unlink to trigger kennel occupancy update"""
        kennels_to_update = self.mapped('kennel_id')
        result = super().unlink()
        # Trigger update for affected kennels
        for kennel in kennels_to_update:
            if kennel:
                kennel._compute_occupancy()
                kennel._compute_availability()
        return result

    def action_assign_staff_to_current_user(self):
        """Assign current user as staff to this boarding stay"""
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
        
        # Assign current user's partner as staff
        self.staff_id = user.partner_id.id
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': f'Assigned {user.partner_id.name} as staff to this boarding stay',
                'type': 'success',
                'sticky': True,
            }
        }
