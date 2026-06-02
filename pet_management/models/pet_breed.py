from odoo import models, fields, api

class PetBreed(models.Model):
    _name = 'pet.breed'
    _description = 'Pet Breed'
    _order = 'species_id, name'

    name = fields.Char(string="Name", required=True, index=True, help="Name of the breed (e.g., Labrador Retriever, Persian)")
    species_id = fields.Many2one('pet.species', string="Species", required=True, ondelete='restrict', help="The species this breed belongs to")
    description = fields.Text(string="Description", help="Detailed description of the breed characteristics")
    active = fields.Boolean(string="Active", default=True, help="Whether this breed is active")
    color = fields.Integer(string="Color Index", default=1, help="Color index for kanban view display")  # For Odoo kanban color reference
    company_id = fields.Many2one('res.company', string="Company", default=lambda s: s.env.company, help="Company this breed belongs to")
    
    # Breed characteristics
    size = fields.Selection([
        ('tiny', 'Tiny'), ('small', 'Small'), ('medium', 'Medium'), 
        ('large', 'Large'), ('giant', 'Giant')
    ], string='Size Category', help="General size category of the breed")
    temperament = fields.Selection([
        ('calm', 'Calm'), ('energetic', 'Energetic'), ('aggressive', 'Aggressive'),
        ('friendly', 'Friendly'), ('shy', 'Shy'), ('playful', 'Playful')
    ], string='Temperament', help="Typical temperament of the breed")
    care_level = fields.Selection([
        ('low', 'Low'), ('medium', 'Medium'), ('high', 'High')
    ], string='Care Level', default='medium', help="Level of care required for this breed")
    life_expectancy_min = fields.Integer(string="Min Life Expectancy (years)", help="Minimum typical life expectancy in years")
    life_expectancy_max = fields.Integer(string="Max Life Expectancy (years)", help="Maximum typical life expectancy in years")
    average_weight_min = fields.Float(string="Min Average Weight (kg)", help="Minimum typical weight in kilograms")
    average_weight_max = fields.Float(string="Max Average Weight (kg)", help="Maximum typical weight in kilograms")
    
    # Computed fields
    pet_count = fields.Integer(string="Pet Count", compute='_compute_pet_count', store=True, help="Number of active pets of this breed")
    vaccination_count = fields.Integer(string="Vaccination Count", compute='_compute_vaccination_count', store=True, help="Total number of vaccinations for pets of this breed")
    medical_visit_count = fields.Integer(string="Medical Visit Count", compute='_compute_medical_visit_count', store=True, help="Total number of medical visits for pets of this breed")
    
    # Related fields
    pet_ids = fields.One2many('pet.pet', 'breed_id', string='Pets', help="Pets belonging to this breed")
    vaccination_ids = fields.One2many('pet.vaccination', 'pet_id', string='Vaccinations', help="Vaccinations for pets of this breed")
    medical_visit_ids = fields.One2many('pet.medical.visit', 'pet_id', string='Medical Visits', help="Medical visits for pets of this breed")

    _sql_constraints = [
        ('uniq_breed_species_company', 'unique(name, species_id, company_id)', 'Breed must be unique for species/company.'),
        ('check_life_expectancy', 'CHECK (life_expectancy_max IS NULL OR life_expectancy_min IS NULL OR life_expectancy_max >= life_expectancy_min)', 'Max life expectancy must be >= min life expectancy.'),
        ('check_weight_range', 'CHECK (average_weight_max IS NULL OR average_weight_min IS NULL OR average_weight_max >= average_weight_min)', 'Max weight must be >= min weight.'),
    ]

    @api.depends('pet_ids')
    def _compute_pet_count(self):
        for breed in self:
            breed.pet_count = len(breed.pet_ids.filtered(lambda p: p.status != 'deceased'))

    @api.depends('pet_ids.vaccination_ids')
    def _compute_vaccination_count(self):
        for breed in self:
            breed.vaccination_count = len(breed.pet_ids.mapped('vaccination_ids'))

    @api.depends('pet_ids.medical_visit_ids')
    def _compute_medical_visit_count(self):
        for breed in self:
            breed.medical_visit_count = len(breed.pet_ids.mapped('medical_visit_ids'))

    def action_view_pets(self):
        """Action to view pets of this breed"""
        action = self.env.ref('pet_management.action_pet_pet').read()[0]
        action['domain'] = [('breed_id', '=', self.id)]
        action['context'] = {'default_breed_id': self.id}
        return action

    def action_view_vaccinations(self):
        """Action to view vaccinations for this breed"""
        action = self.env.ref('pet_management.action_pet_vaccination').read()[0]
        action['domain'] = [('pet_id.breed_id', '=', self.id)]
        return action

    def action_view_medical_visits(self):
        """Action to view medical visits for this breed"""
        action = self.env.ref('pet_management.action_pet_medical_visit').read()[0]
        action['domain'] = [('pet_id.breed_id', '=', self.id)]
        return action
