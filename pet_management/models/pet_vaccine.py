from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import timedelta

class PetVaccine(models.Model):
    _name = 'pet.vaccine'
    _description = 'Vaccine Catalog'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name, species_id'

    # Basic Information
    name = fields.Char(string="Name", required=True, tracking=True, help="Vaccine name (e.g., Rabies, DHPP, FVRCP)")
    code = fields.Char(string="Code", help="Internal vaccine code for identification")
    species_id = fields.Many2one('pet.species', string="Species", required=True, tracking=True, help="Species this vaccine is designed for")
    manufacturer = fields.Char(string="Manufacturer", tracking=True, help="Vaccine manufacturer")
    lot_number = fields.Char(string="Lot Number", help="Current lot number")
    expiration_date = fields.Date(string="Expiration Date", help="Vaccine expiration date")
    
    # Product Integration
    product_id = fields.Many2one('product.product', string="Product", help="Related product for inventory management")
    cost = fields.Float(string="Cost", help="Cost per dose")
    currency_id = fields.Many2one('res.currency', string="Currency", help="Currency for cost")
    
    # Dosage Information
    dose_ml_default = fields.Float(string="Default Dose (ml)", help="Default dose in milliliters")
    dose_ml_min = fields.Float(string="Min Dose (ml)", help="Minimum dose in milliliters")
    dose_ml_max = fields.Float(string="Max Dose (ml)", help="Maximum dose in milliliters")
    administration_route = fields.Selection([
        ('subcutaneous', 'Subcutaneous (SC)'),
        ('intramuscular', 'Intramuscular (IM)'),
        ('intranasal', 'Intranasal'),
        ('oral', 'Oral'),
        ('intravenous', 'Intravenous (IV)'),
        ('other', 'Other')
    ], string='Administration Route', default='subcutaneous', help="How the vaccine is administered")
    
    # Timing Information
    booster_interval_days = fields.Integer(string="Booster Interval (days)", help="Days between booster shots")
    initial_age_weeks = fields.Integer(string="Initial Age (weeks)", help="Minimum age in weeks for first dose")
    max_age_weeks = fields.Integer(string="Max Age (weeks)", help="Maximum age in weeks for administration")
    requires_multiple_doses = fields.Boolean(string="Requires Multiple Doses", help="Whether this vaccine requires multiple doses")
    dose_interval_days = fields.Integer(string="Dose Interval (days)", help="Days between multiple doses")
    
    # Safety & Contraindications
    contraindications = fields.Text(string="Contraindications", help="Medical conditions that prevent vaccination")
    side_effects = fields.Text(string="Side Effects", help="Common side effects")
    storage_requirements = fields.Text(string="Storage Requirements", help="Storage temperature and conditions")
    handling_notes = fields.Text(string="Handling Notes", help="Special handling instructions")
    
    # Regulatory Information
    fda_approved = fields.Boolean(string="FDA Approved", help="FDA approval status")
    fda_approval_date = fields.Date(string="FDA Approval Date", help="FDA approval date")
    license_number = fields.Char(string="License Number", help="Vaccine license number")
    batch_tracking = fields.Boolean(string="Batch Tracking", help="Whether batch tracking is required")
    
    # Usage Tracking
    vaccination_count = fields.Integer(string="Vaccination Count", compute='_compute_vaccination_count', store=True, help="Number of times this vaccine has been administered")
    last_used_date = fields.Date(string="Last Used Date", compute='_compute_last_used_date', store=True, help="Date this vaccine was last used")
    active = fields.Boolean(string="Active", default=True, tracking=True, help="Whether this vaccine is active")
    
    # Visual & Organization
    color = fields.Integer(string="Color Index", help="Color for kanban view")
    priority = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical')
    ], string='Priority', default='medium', help="Vaccine priority level")
    
    # Additional Information
    notes = fields.Text(string="Notes", help="Additional notes about the vaccine")
    company_id = fields.Many2one('res.company', string="Company", help="Company")
    
    # Computed Fields
    is_expired = fields.Boolean(string="Is Expired", compute='_compute_is_expired', store=True, help="Whether the vaccine has expired")
    days_until_expiry = fields.Integer(string="Days Until Expiry", compute='_compute_days_until_expiry', store=True, help="Days until vaccine expires")
    usage_frequency = fields.Selection([
        ('rare', 'Rare'),
        ('occasional', 'Occasional'),
        ('common', 'Common'),
        ('frequent', 'Frequent')
    ], string="Usage Frequency", compute='_compute_usage_frequency', store=True, help="How frequently this vaccine is used")
    
    # Related Records
    vaccination_ids = fields.One2many('pet.vaccination', 'vaccine_id', string='Vaccinations', help="Vaccination records using this vaccine")

    _sql_constraints = [
        ('uniq_vaccine_company', 'unique(name, species_id, company_id)', 'Vaccine must be unique for species/company.'),
        ('check_dose_range', 'CHECK(dose_ml_min <= dose_ml_max)', 'Minimum dose must be less than or equal to maximum dose.'),
        ('check_booster_interval', 'CHECK(booster_interval_days > 0)', 'Booster interval must be positive.'),
        ('check_age_range', 'CHECK(initial_age_weeks <= max_age_weeks)', 'Initial age must be less than or equal to maximum age.'),
    ]

    @api.depends('vaccination_ids')
    def _compute_vaccination_count(self):
        """Calculate number of vaccinations using this vaccine"""
        for record in self:
            record.vaccination_count = len(record.vaccination_ids)

    @api.depends('vaccination_ids.date_administered')
    def _compute_last_used_date(self):
        """Calculate the last date this vaccine was used"""
        for record in self:
            if record.vaccination_ids:
                record.last_used_date = max(record.vaccination_ids.mapped('date_administered'))
            else:
                record.last_used_date = False

    @api.depends('expiration_date')
    def _compute_is_expired(self):
        """Check if vaccine has expired"""
        today = fields.Date.today()
        for record in self:
            record.is_expired = record.expiration_date and record.expiration_date < today

    @api.depends('expiration_date')
    def _compute_days_until_expiry(self):
        """Calculate days until vaccine expires"""
        today = fields.Date.today()
        for record in self:
            if record.expiration_date:
                delta = record.expiration_date - today
                record.days_until_expiry = delta.days
            else:
                record.days_until_expiry = 0

    @api.depends('vaccination_count')
    def _compute_usage_frequency(self):
        """Calculate usage frequency based on vaccination count"""
        for record in self:
            if record.vaccination_count == 0:
                record.usage_frequency = 'rare'
            elif record.vaccination_count <= 5:
                record.usage_frequency = 'occasional'
            elif record.vaccination_count <= 20:
                record.usage_frequency = 'common'
            else:
                record.usage_frequency = 'frequent'

    def action_view_vaccinations(self):
        """Action to view vaccinations using this vaccine"""
        return {
            'type': 'ir.actions.act_window',
            'name': f'Vaccinations - {self.name}',
            'res_model': 'pet.vaccination',
            'view_mode': 'list,kanban,form',
            'domain': [('vaccine_id', '=', self.id)],
            'context': {'default_vaccine_id': self.id},
            'target': 'current',
        }

    def action_create_vaccination(self):
        """Action to create a new vaccination with this vaccine"""
        return {
            'type': 'ir.actions.act_window',
            'name': f'New Vaccination - {self.name}',
            'res_model': 'pet.vaccination',
            'view_mode': 'form',
            'context': {
                'default_vaccine_id': self.id,
                'default_dose_ml': self.dose_ml_default,
            },
            'target': 'current',
        }

    def action_check_expiry(self):
        """Check for vaccines approaching expiry"""
        today = fields.Date.today()
        expiring_soon = self.search([
            ('expiration_date', '<=', today + timedelta(days=30)),
            ('expiration_date', '>', today),
            ('active', '=', True)
        ])
        
        if expiring_soon:
            message = f"Found {len(expiring_soon)} vaccines expiring within 30 days:\n"
            for vaccine in expiring_soon:
                message += f"- {vaccine.name} ({vaccine.species_id.name}): {vaccine.expiration_date}\n"
            raise UserError(message)
        else:
            raise UserError("No vaccines are expiring within the next 30 days.")

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to set default values"""
        for vals in vals_list:
            if not vals.get('code'):
                vals['code'] = self._generate_vaccine_code(vals.get('name', ''))
        return super().create(vals_list)

    def _generate_vaccine_code(self, name):
        """Generate a unique vaccine code"""
        if not name:
            return ''
        
        # Create code from name (first 3 letters + random numbers)
        code_prefix = name[:3].upper()
        existing_codes = self.search([('code', 'like', f'{code_prefix}%')]).mapped('code')
        
        counter = 1
        while True:
            code = f"{code_prefix}{counter:03d}"
            if code not in existing_codes:
                return code
            counter += 1
