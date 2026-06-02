from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import timedelta

class PetDietPlan(models.Model):
    _name = 'pet.diet.plan'
    _description = 'Diet Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_date desc'

    name = fields.Char(string="Name", required=True, tracking=True, help="Diet plan name")
    code = fields.Char(string="Code", readonly=True, copy=False, index=True, default=lambda s: _('New'), help="Unique diet plan code")
    
    # Core Fields
    pet_id = fields.Many2one('pet.pet', string="Pet", required=True, ondelete='cascade', tracking=True, help="Pet this diet plan is for")
    veterinarian_id = fields.Many2one(
        'res.partner', string="Veterinarian", domain=lambda self: [('id', '=', self.env.user.partner_id.id)] if self.env.user.has_group('pet_management.group_pet_staff_diet') else [('is_company','=',False)],
        tracking=True, help="Veterinarian who prescribed this diet"
    )
    
    # Diet Plan Details
    start_date = fields.Date(string="Start Date", required=True, tracking=True, help="When the diet plan starts")
    end_date = fields.Date(string="End Date", tracking=True, help="When the diet plan ends (optional)")
    duration_days = fields.Integer(string="Duration Days", compute='_compute_duration', store=True, help="Duration of the diet plan in days")
    is_current = fields.Boolean(string="Is Current", compute='_compute_is_current', search='_search_is_current', help="Is this the current active diet plan?")
    is_expired = fields.Boolean(string="Is Expired", compute='_compute_is_expired', search='_search_is_expired', help="Has this diet plan expired?")
    
    # Diet Plan Type and Purpose
    diet_type = fields.Selection([
        ('weight_loss', 'Weight Loss'),
        ('weight_gain', 'Weight Gain'),
        ('maintenance', 'Weight Maintenance'),
        ('medical', 'Medical Diet'),
        ('puppy_kitten', 'Puppy/Kitten'),
        ('senior', 'Senior Diet'),
        ('allergy', 'Allergy Management'),
        ('digestive', 'Digestive Health'),
        ('dental', 'Dental Health'),
        ('performance', 'Performance Diet'),
        ('recovery', 'Recovery Diet'),
        ('custom', 'Custom Diet')
    ], string="Diet Type", required=True, tracking=True, help="Type of diet plan")
    
    diet_purpose = fields.Text(string="Diet Purpose", help="Purpose and goals of this diet plan")
    medical_conditions = fields.Text(string="Medical Conditions", help="Medical conditions this diet addresses")
    allergies_considered = fields.Text(string="Allergies Considered", help="Allergies and restrictions considered in this diet")
    
    # Nutritional Information
    target_weight = fields.Float(string="Target Weight", help="Target weight for the pet (kg)")
    current_weight = fields.Float(string="Current Weight", related='pet_id.latest_weight_kg', help="Pet's current weight")
    daily_calories = fields.Float(string="Daily Calories", help="Target daily calorie intake")
    protein_percentage = fields.Float(string="Protein Percentage", help="Protein percentage in diet")
    fat_percentage = fields.Float(string="Fat Percentage", help="Fat percentage in diet")
    fiber_percentage = fields.Float(string="Fiber Percentage", help="Fiber percentage in diet")
    
    # Feeding Schedule
    feeding_frequency = fields.Selection([
        ('1', 'Once daily'),
        ('2', 'Twice daily'),
        ('3', 'Three times daily'),
        ('4', 'Four times daily'),
        ('5', 'Five times daily'),
        ('6', 'Six times daily'),
        ('free_feed', 'Free feeding'),
        ('custom', 'Custom schedule')
    ], string="Feeding Frequency", default='2', help="How often the pet should be fed")
    
    feeding_schedule_notes = fields.Text(string="Feeding Schedule Notes", help="Special feeding schedule instructions")
    
    # Diet Plan Management
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], string="State", default='draft', tracking=True, help="Diet plan status")
    
    state_color = fields.Integer(compute='_compute_state_color', string='State Color', store=True)
    
    # Progress Tracking
    progress_notes = fields.Text(help="Progress notes and observations")
    weight_progress = fields.Text(compute='_compute_weight_progress', help="Weight progress tracking")
    adherence_rating = fields.Selection([
        ('excellent', 'Excellent'),
        ('good', 'Good'),
        ('fair', 'Fair'),
        ('poor', 'Poor')
    ], help="How well the pet owner is following the diet plan")
    
    # Cost and Logistics
    estimated_monthly_cost = fields.Monetary(currency_field='currency_id', help="Estimated monthly cost of this diet")
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    supplier_recommendations = fields.Text(help="Recommended suppliers or brands")
    
    # Follow-up and Reviews
    next_review_date = fields.Date(help="When to review this diet plan")
    review_frequency_days = fields.Integer(default=30, help="How often to review this diet (days)")
    last_review_date = fields.Date(help="Last review date")
    review_notes = fields.Text(help="Notes from the last review")
    
    # Related Records
    line_ids = fields.One2many('pet.diet.plan.line', 'plan_id', string='Diet Plan Lines')
    
    # Analytics Fields
    days_active = fields.Integer(compute='_compute_days_active', store=True, help="Number of days this diet has been active")
    weight_change = fields.Float(compute='_compute_weight_change', help="Weight change since diet started (kg)")
    adherence_percentage = fields.Float(help="Adherence percentage (0-100)")
    
    # Company and Integration
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)
    
    # Related Information
    owner_id = fields.Many2one('res.partner', related='pet_id.owner_id', store=True, help="Pet owner")
    species_id = fields.Many2one('pet.species', related='pet_id.species_id', store=True, help="Pet species")
    breed_id = fields.Many2one('pet.breed', related='pet_id.breed_id', store=True, help="Pet breed")
    
    @api.depends('start_date', 'end_date')
    def _compute_duration(self):
        for record in self:
            if record.start_date and record.end_date:
                duration = record.end_date - record.start_date
                record.duration_days = duration.days
            elif record.start_date:
                # If no end date, calculate from start to today
                today = fields.Date.context_today(self)
                duration = today - record.start_date
                record.duration_days = max(0, duration.days)
            else:
                record.duration_days = 0
    
    @api.depends('start_date', 'end_date', 'state')
    def _compute_is_current(self):
        today = fields.Date.context_today(self)
        for record in self:
            if record.state == 'active':
                if record.start_date and record.start_date <= today:
                    if not record.end_date or record.end_date >= today:
                        record.is_current = True
                    else:
                        record.is_current = False
                else:
                    record.is_current = False
            else:
                record.is_current = False
    
    @api.depends('end_date', 'state')
    def _compute_is_expired(self):
        today = fields.Date.context_today(self)
        for record in self:
            if record.end_date and record.end_date < today and record.state in ['active', 'paused']:
                record.is_expired = True
            else:
                record.is_expired = False
    
    @api.depends('start_date')
    def _compute_days_active(self):
        today = fields.Date.context_today(self)
        for record in self:
            if record.start_date and record.state == 'active':
                duration = today - record.start_date
                record.days_active = max(0, duration.days)
            else:
                record.days_active = 0
    
    @api.depends('start_date', 'pet_id')
    def _compute_weight_change(self):
        for record in self:
            if record.start_date and record.pet_id:
                # Get weight at start of diet
                start_weight = self.env['pet.weight.history'].search([
                    ('pet_id', '=', record.pet_id.id),
                    ('date', '<=', record.start_date)
                ], order='date desc', limit=1)
                
                # Get current weight
                current_weight = record.pet_id.latest_weight_kg
                
                if start_weight and current_weight:
                    record.weight_change = current_weight - start_weight.weight_kg
                else:
                    record.weight_change = 0.0
            else:
                record.weight_change = 0.0
    
    @api.depends('start_date', 'pet_id')
    def _compute_weight_progress(self):
        for record in self:
            if record.start_date and record.pet_id:
                # Get weight records for this pet since diet start
                weight_records = self.env['pet.weight.history'].search([
                    ('pet_id', '=', record.pet_id.id),
                    ('date', '>=', record.start_date)
                ], order='date')
                
                if weight_records:
                    weights = weight_records.sorted('date')
                    if len(weights) >= 2:
                        progress = f"Started at {weights[0].weight_kg}kg, current: {weights[-1].weight_kg}kg"
                        if len(weights) > 2:
                            progress += f" (change: {weights[-1].weight_kg - weights[0].weight_kg:+.1f}kg)"
                        record.weight_progress = progress
                    else:
                        record.weight_progress = f"Current weight: {weights[0].weight_kg}kg" if weights else "No weight data"
                else:
                    record.weight_progress = "No weight tracking data"
            else:
                record.weight_progress = "No weight tracking data"
    
    @api.depends('state')
    def _compute_state_color(self):
        color_map = {
            'draft': 0,        # grey
            'active': 4,       # green
            'paused': 2,       # orange
            'completed': 4,    # green
            'cancelled': 1,    # red
        }
        for rec in self:
            rec.state_color = color_map.get(rec.state, 0)
    
    @api.model_create_multi
    def create(self, vals_list):
        # Get diet plan settings
        icp = self.env['ir.config_parameter'].sudo()
        default_duration = int(icp.get_param('pet_management.diet_plan_duration_days', 30))
        
        for vals in vals_list:
            if vals.get('code', _('New')) == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('pet.diet.plan') or _('New')
            
            # Apply default duration if not specified
            if 'start_date' in vals and 'end_date' not in vals:
                from datetime import datetime, timedelta
                start_date = vals['start_date']
                if isinstance(start_date, str):
                    start_date = datetime.fromisoformat(start_date).date()
                vals['end_date'] = start_date + timedelta(days=default_duration)
                
        return super().create(vals_list)

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for rec in self:
            if rec.end_date and rec.start_date and rec.end_date < rec.start_date:
                raise ValidationError(_('End date must be after start date.'))
    
    @api.constrains('target_weight')
    def _check_weights(self):
        for rec in self:
            if rec.target_weight and rec.target_weight <= 0:
                raise ValidationError(_('Target weight must be positive.'))
    
    @api.model
    def _search_is_current(self, operator, value):
        today = fields.Date.context_today(self)
        if operator == '=' and value is True:
            return [('state', '=', 'active'),
                    ('start_date', '<=', today),
                    '|', ('end_date', '=', False), ('end_date', '>=', today)]
        elif operator == '=' and value is False:
            return ['|', ('state', '!=', 'active'),
                    '|', ('start_date', '>', today),
                    '&', ('end_date', '!=', False), ('end_date', '<', today)]
        return []
    
    @api.model
    def _search_is_expired(self, operator, value):
        today = fields.Date.context_today(self)
        if operator == '=' and value is True:
            return [('end_date', '<', today),
                    ('state', 'in', ['active', 'paused'])]
        elif operator == '=' and value is False:
            return ['|', ('end_date', '>=', today),
                    ('state', 'not in', ['active', 'paused'])]
        return []
    
    # Workflow Actions
    def action_activate_diet(self):
        """Activate the diet plan"""
        for plan in self:
            # Deactivate other active diets for the same pet
            other_plans = self.env['pet.diet.plan'].search([
                ('pet_id', '=', plan.pet_id.id),
                ('state', '=', 'active'),
                ('id', '!=', plan.id)
            ])
            other_plans.write({'state': 'paused'})
            
            plan.state = 'active'
            plan.message_post(body=_('Diet plan activated.'))
    
    def action_pause_diet(self):
        """Pause the diet plan"""
        for plan in self:
            plan.state = 'paused'
            plan.message_post(body=_('Diet plan paused.'))
    
    def action_complete_diet(self):
        """Complete the diet plan"""
        for plan in self:
            plan.state = 'completed'
            plan.message_post(body=_('Diet plan completed.'))
    
    def action_cancel_diet(self):
        """Cancel the diet plan"""
        for plan in self:
            plan.state = 'cancelled'
            plan.message_post(body=_('Diet plan cancelled.'))
    
    def action_review_diet(self):
        """Review the diet plan"""
        for plan in self:
            plan.last_review_date = fields.Date.context_today(self)
            plan.next_review_date = plan.last_review_date + timedelta(days=plan.review_frequency_days)
            plan.message_post(body=_('Diet plan reviewed.'))
    
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
    
    def action_view_weight_history(self):
        """View weight history for this pet"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Weight History',
            'res_model': 'pet.weight.history',
            'view_mode': 'list,form',
            'domain': [('pet_id', '=', self.pet_id.id)],
            'context': {'default_pet_id': self.pet_id.id}
        }
    
    def action_assign_current_user_as_veterinarian(self):
        """Assign current user as veterinarian to this diet plan"""
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
        self.veterinarian_id = user.partner_id.id
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': f'Assigned {user.partner_id.name} as veterinarian to this diet plan',
                'type': 'success',
                'sticky': True,
            }
        }

class PetDietPlanLine(models.Model):
    _name = 'pet.diet.plan.line'
    _description = 'Diet Plan Line'
    _order = 'sequence, time_of_day'

    plan_id = fields.Many2one('pet.diet.plan', string="Plan", required=True, ondelete='cascade', help="Diet plan this line belongs to")
    sequence = fields.Integer(string="Sequence", default=10, help="Sequence for ordering")
    
    # Feeding Details
    time_of_day = fields.Selection([
        ('morning', 'Morning'),
        ('mid_morning', 'Mid Morning'),
        ('noon', 'Noon'),
        ('afternoon', 'Afternoon'),
        ('evening', 'Evening'),
        ('night', 'Night'),
        ('late_night', 'Late Night'),
        ('custom', 'Custom Time')
    ], string="Time Of Day", required=True, help="When to feed this meal")
    
    custom_time = fields.Char(string="Custom Time", help="Custom feeding time (e.g., '9:30 AM')")
    
    # Food Details
    product_id = fields.Many2one('product.product', string="Product", help="Product/food item")
    food_name = fields.Char(string="Food Name", required=True, help="Name of the food")
    food_category = fields.Selection([
        ('dry_kibble', 'Dry Kibble'),
        ('wet_food', 'Wet Food'),
        ('raw', 'Raw Food'),
        ('treats', 'Treats'),
        ('supplements', 'Supplements'),
        ('medication', 'Medication'),
        ('water', 'Water'),
        ('other', 'Other')
    ], string="Food Category", help="Category of food")
    
    # Quantity and Measurements
    quantity = fields.Float(string="Quantity", required=True, help="Amount of food")
    unit = fields.Selection([
        ('cups', 'Cups'),
        ('grams', 'Grams'),
        ('kg', 'Kilograms'),
        ('oz', 'Ounces'),
        ('ml', 'Milliliters'),
        ('liters', 'Liters'),
        ('pills', 'Pills'),
        ('pieces', 'Pieces'),
        ('tbsp', 'Tablespoons'),
        ('tsp', 'Teaspoons'),
        ('other', 'Other')
    ], string="Unit", default='grams', help="Unit of measurement")
    
    # Nutritional Information
    calories = fields.Float(string="Calories", help="Calories per serving")
    protein_content = fields.Float(string="Protein Content", help="Protein content (%)")
    fat_content = fields.Float(string="Fat Content", help="Fat content (%)")
    fiber_content = fields.Float(string="Fiber Content", help="Fiber content (%)")
    
    # Instructions and Notes
    instructions = fields.Text(string="Instructions", help="Special preparation or feeding instructions")
    notes = fields.Text(string="Notes", help="Additional notes about this meal")
    
    # Status and Tracking
    is_optional = fields.Boolean(string="Is Optional", default=False, help="Is this meal optional?")
    is_treat = fields.Boolean(string="Is Treat", default=False, help="Is this a treat rather than a meal?")
    
    # Related Information
    pet_id = fields.Many2one('pet.pet', related='plan_id.pet_id', store=True, help="Pet this line is for")
