from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError  # type: ignore
from datetime import datetime, timedelta
import statistics

class PetWeightHistory(models.Model):
    _name = 'pet.weight.history'
    _description = 'Pet Weight History'
    _order = 'date desc, id desc'
    _rec_name = 'display_name'

    # Basic Fields
    pet_id = fields.Many2one('pet.pet', required=True, ondelete='cascade', index=True,
                            help="The pet this weight record belongs to")
    date = fields.Date(required=True, default=fields.Date.today,
                      help="Date when the weight was recorded")
    weight_kg = fields.Float(required=True, digits='Stock Weight',
                            help="Weight in kilograms")
    weight_lbs = fields.Float(compute='_compute_weight_lbs', store=True,
                             help="Weight in pounds (automatically calculated)")
    notes = fields.Text(help="Additional notes about this weight measurement")
    
    # Health Indicators
    bmi = fields.Float(compute='_compute_bmi', store=True, digits=(5, 2),
                      help="Body Mass Index based on weight and breed standards")
    health_status = fields.Selection([
        ('underweight', 'Underweight'),
        ('healthy', 'Healthy'),
        ('overweight', 'Overweight'),
        ('obese', 'Obese'),
        ('unknown', 'Unknown')
    ], compute='_compute_health_status', store=True,
       help="Health status based on weight compared to breed standards")
    
    # Comparison Fields
    previous_weight = fields.Float(compute='_compute_previous_weight', store=True,
                                  help="Previous weight measurement")
    weight_change = fields.Float(compute='_compute_weight_change', store=True,
                                help="Weight change from previous measurement")
    weight_change_percent = fields.Float(compute='_compute_weight_change_percent', store=True,
                                        help="Percentage change from previous weight")
    days_since_previous = fields.Integer(compute='_compute_days_since_previous', store=True,
                                        help="Days since the previous weight measurement")
    
    # Trend Analysis
    trend_direction = fields.Selection([
        ('increasing', 'Increasing'),
        ('decreasing', 'Decreasing'),
        ('stable', 'Stable'),
        ('unknown', 'Unknown')
    ], compute='_compute_trend_direction', store=False,
       help="Weight trend direction over the last 7 days")
    trend_strength = fields.Selection([
        ('weak', 'Weak'),
        ('moderate', 'Moderate'),
        ('strong', 'Strong'),
        ('unknown', 'Unknown')
    ], compute='_compute_trend_strength', store=False,
       help="Strength of the weight trend")
    
    # Alert Fields
    is_concerning = fields.Boolean(compute='_compute_is_concerning', store=True,
                                  help="True if this weight measurement raises health concerns")
    alert_message = fields.Text(compute='_compute_alert_message',
                               help="Alert message for concerning weight changes")
    
    # Metadata
    recorded_by = fields.Many2one('res.users', default=lambda self: self.env.user,
                                 help="User who recorded this weight measurement")
    measurement_method = fields.Selection([
        ('scale', 'Digital Scale'),
        ('manual', 'Manual Estimate'),
        ('veterinary', 'Veterinary Scale'),
        ('other', 'Other')
    ], default='scale', help="Method used to measure the weight")
    
    # Display Name
    display_name = fields.Char(string="Display Name", compute='_compute_display_name', store=True)

    _sql_constraints = [
        ('uniq_weight_per_day', 'unique(pet_id, date)', 'Only one weight entry per day per pet.'),
        ('positive_weight', 'CHECK(weight_kg > 0)', 'Weight must be positive.'),
        ('valid_date', 'CHECK(date <= CURRENT_DATE)', 'Weight date cannot be in the future.'),
    ]

    @api.depends('weight_kg')
    def _compute_weight_lbs(self):
        """Convert kg to pounds"""
        for record in self:
            record.weight_lbs = record.weight_kg * 2.20462 if record.weight_kg else 0.0

    @api.depends('pet_id', 'weight_kg')
    def _compute_bmi(self):
        """Calculate BMI based on weight and breed standards"""
        for record in self:
            if record.pet_id and record.pet_id.breed_id and record.weight_kg:
                # Get breed's average weight range
                avg_weight = (record.pet_id.breed_id.average_weight_min + 
                             record.pet_id.breed_id.average_weight_max) / 2
                if avg_weight > 0:
                    # Simple BMI calculation (weight / average_weight^2 * 100)
                    record.bmi = (record.weight_kg / (avg_weight ** 2)) * 100
                else:
                    record.bmi = 0.0
            else:
                record.bmi = 0.0

    @api.depends('pet_id', 'weight_kg', 'bmi')
    def _compute_health_status(self):
        """Determine health status based on weight"""
        for record in self:
            if not record.pet_id or not record.weight_kg:
                record.health_status = 'healthy'  # Default to healthy instead of unknown
                continue
                
            # If no breed information, default to healthy
            if not record.pet_id.breed_id:
                record.health_status = 'healthy'
                continue
                
            breed = record.pet_id.breed_id
            min_weight = breed.average_weight_min
            max_weight = breed.average_weight_max
            
            # If breed doesn't have weight standards, default to healthy
            if min_weight == 0 or max_weight == 0:
                record.health_status = 'healthy'
                continue
                
            # Calculate healthy weight range (20% tolerance)
            healthy_min = min_weight * 0.8
            healthy_max = max_weight * 1.2
            
            if record.weight_kg < healthy_min:
                record.health_status = 'underweight'
            elif record.weight_kg > healthy_max * 1.2:
                record.health_status = 'obese'
            elif record.weight_kg > healthy_max:
                record.health_status = 'overweight'
            else:
                record.health_status = 'healthy'

    @api.depends('pet_id', 'date')
    def _compute_previous_weight(self):
        """Get the previous weight measurement"""
        for record in self:
            # Skip computation for new records
            if not record.id:
                record.previous_weight = 0.0
                continue
                
            if record.pet_id and record.date:
                previous = self.search([
                    ('pet_id', '=', record.pet_id.id),
                    ('date', '<', record.date),
                    ('id', '!=', record.id)
                ], limit=1, order='date desc')
                record.previous_weight = previous.weight_kg if previous else 0.0
            else:
                record.previous_weight = 0.0

    @api.depends('weight_kg', 'previous_weight')
    def _compute_weight_change(self):
        """Calculate weight change from previous measurement"""
        for record in self:
            if record.previous_weight > 0:
                record.weight_change = record.weight_kg - record.previous_weight
            else:
                record.weight_change = 0.0

    @api.depends('weight_kg', 'previous_weight', 'weight_change')
    def _compute_weight_change_percent(self):
        """Calculate percentage weight change"""
        for record in self:
            if record.previous_weight > 0 and record.weight_change != 0:
                record.weight_change_percent = (record.weight_change / record.previous_weight) * 100
            else:
                record.weight_change_percent = 0.0

    @api.depends('pet_id', 'date')
    def _compute_days_since_previous(self):
        """Calculate days since previous measurement"""
        for record in self:
            # Skip computation for new records
            if not record.id:
                record.days_since_previous = 0
                continue
                
            if record.pet_id and record.date:
                previous = self.search([
                    ('pet_id', '=', record.pet_id.id),
                    ('date', '<', record.date),
                    ('id', '!=', record.id)
                ], limit=1, order='date desc')
                if previous:
                    delta = record.date - previous.date
                    record.days_since_previous = delta.days
                else:
                    record.days_since_previous = 0
            else:
                record.days_since_previous = 0

    @api.depends('pet_id', 'date', 'weight_kg', 'weight_change_percent')
    def _compute_trend_direction(self):
        """Calculate weight trend direction based on recent changes"""
        for record in self:
            # For new records or records without sufficient data, use weight change
            if not record.id:
                # Use weight change percentage if available
                if hasattr(record, 'weight_change_percent') and record.weight_change_percent:
                    if record.weight_change_percent > 2:
                        record.trend_direction = 'increasing'
                    elif record.weight_change_percent < -2:
                        record.trend_direction = 'decreasing'
                    else:
                        record.trend_direction = 'stable'
                else:
                    record.trend_direction = 'stable'  # Default to stable instead of unknown
                continue
                
            # For existing records, try to get historical data
            if record.pet_id and record.date:
                try:
                    # Get last 7 days of weight data
                    week_ago = record.date - timedelta(days=7)
                    recent_weights = self.search([
                        ('pet_id', '=', record.pet_id.id),
                        ('date', '>=', week_ago),
                        ('date', '<=', record.date),
                        ('id', '!=', record.id)
                    ], order='date')
                    
                    if len(recent_weights) >= 2:
                        # Simple trend calculation
                        first_half = recent_weights[:len(recent_weights)//2]
                        second_half = recent_weights[len(recent_weights)//2:]
                        
                        if first_half and second_half:
                            first_avg = sum(w.weight_kg for w in first_half) / len(first_half)
                            second_avg = sum(w.weight_kg for w in second_half) / len(second_half)
                            
                            if second_avg > first_avg * 1.02:  # 2% increase
                                record.trend_direction = 'increasing'
                            elif second_avg < first_avg * 0.98:  # 2% decrease
                                record.trend_direction = 'decreasing'
                            else:
                                record.trend_direction = 'stable'
                        else:
                            record.trend_direction = 'stable'
                    else:
                        # Fallback to weight change percentage
                        if record.weight_change_percent > 2:
                            record.trend_direction = 'increasing'
                        elif record.weight_change_percent < -2:
                            record.trend_direction = 'decreasing'
                        else:
                            record.trend_direction = 'stable'
                except:
                    # If any error occurs, use weight change percentage
                    if record.weight_change_percent > 2:
                        record.trend_direction = 'increasing'
                    elif record.weight_change_percent < -2:
                        record.trend_direction = 'decreasing'
                    else:
                        record.trend_direction = 'stable'
            else:
                record.trend_direction = 'stable'

    @api.depends('trend_direction', 'weight_change_percent')
    def _compute_trend_strength(self):
        """Calculate trend strength based on percentage change"""
        for record in self:
            if record.trend_direction == 'unknown':
                record.trend_strength = 'weak'  # Default to weak instead of unknown
            else:
                abs_change = abs(record.weight_change_percent or 0)
                if abs_change >= 10:
                    record.trend_strength = 'strong'
                elif abs_change >= 5:
                    record.trend_strength = 'moderate'
                else:
                    record.trend_strength = 'weak'

    @api.depends('health_status', 'weight_change_percent')
    def _compute_is_concerning(self):
        """Determine if this weight measurement is concerning"""
        for record in self:
            concerning = False
            
            # Health status concerns
            if record.health_status in ['underweight', 'overweight', 'obese']:
                concerning = True
            
            # Rapid weight change concerns
            if abs(record.weight_change_percent) > 15:
                concerning = True
                
            record.is_concerning = concerning

    @api.depends('is_concerning', 'health_status', 'weight_change_percent')
    def _compute_alert_message(self):
        """Generate alert message for concerning measurements"""
        for record in self:
            messages = []
            
            if record.health_status == 'underweight':
                messages.append("Pet is underweight for its breed standards.")
            elif record.health_status == 'overweight':
                messages.append("Pet is overweight for its breed standards.")
            elif record.health_status == 'obese':
                messages.append("Pet is obese for its breed standards.")
            
            if abs(record.weight_change_percent) > 15:
                messages.append(f"Rapid weight change of {abs(record.weight_change_percent):.1f}%.")
            
            record.alert_message = " ".join(messages) if messages else ""

    @api.depends('pet_id', 'date', 'weight_kg')
    def _compute_display_name(self):
        """Generate display name for the record"""
        for record in self:
            if record.pet_id and record.date and record.weight_kg:
                record.display_name = f"{record.pet_id.name} - {record.date} ({record.weight_kg}kg)"
            else:
                record.display_name = "Weight Record"

    @api.constrains('weight_kg', 'date')
    def _check_weight_data(self):
        """Validate weight data"""
        for record in self:
            if record.weight_kg <= 0:
                raise ValidationError(_("Weight must be greater than 0."))
            
            if record.date > fields.Date.today():
                raise ValidationError(_("Weight date cannot be in the future."))

    def _validate_deceased_pets(self):
        """Validate that no weight records exist for deceased pets"""
        deceased_pets = self.filtered(lambda r: r.pet_id.status == 'deceased')
        if deceased_pets:
            pet_names = ', '.join(deceased_pets.mapped('pet_id.name'))
            raise ValidationError(_("Cannot add weight records for deceased pets: %s") % pet_names)

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to add validation and automatic updates"""
        records = super().create(vals_list)
        
        # Update pet's latest weight (skip during data loading)
        if not self.env.context.get('install_mode'):
            for record in records:
                if record.pet_id:
                    record.pet_id._compute_latest_weight()
        
        return records

    def write(self, vals):
        """Override write to update pet's latest weight"""
        result = super().write(vals)
        
        for record in self:
            if record.pet_id and not self.env.context.get('install_mode'):
                record.pet_id._compute_latest_weight()
        
        return result

    def unlink(self):
        """Override unlink to update pet's latest weight"""
        pets_to_update = self.mapped('pet_id')
        result = super().unlink()
        
        for pet in pets_to_update:
            if not self.env.context.get('install_mode'):
                pet._compute_latest_weight()
        
        return result

    # Action Methods
    def action_view_pet(self):
        """View the pet record"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pet'),
            'res_model': 'pet.pet',
            'res_id': self.pet_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_create_follow_up(self):
        """Create a follow-up weight measurement"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Weight Measurement'),
            'res_model': 'pet.weight.history',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_pet_id': self.pet_id.id,
                'default_date': (self.date + timedelta(days=7)).strftime('%Y-%m-%d'),
            }
        }

    def action_view_weight_chart(self):
        """View weight chart for this pet"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Weight Chart - %s') % self.pet_id.name,
            'res_model': 'pet.weight.history',
            'view_mode': 'graph',
            'domain': [('pet_id', '=', self.pet_id.id)],
            'context': {
                'group_by': 'date',
                'graph_mode': 'line',
            },
            'target': 'current',
        }
