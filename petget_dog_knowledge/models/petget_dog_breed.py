from odoo import fields, models

LEVEL = [('low', 'Low'), ('medium', 'Medium'), ('high', 'High')]


class PetgetDogBreed(models.Model):
    _name = 'petget.dog.breed'
    _inherit = ['petget.dog.breed', 'image.mixin']

    # --- Profile ---
    origin_country_ids = fields.Many2many(
        'res.country', string='Country of Origin',
    )
    description = fields.Text(string='Description')
    temperament = fields.Char(string='Temperament')
    weight_min_kg = fields.Float(string='Weight min (kg)')
    weight_max_kg = fields.Float(string='Weight max (kg)')
    height_min_cm = fields.Float(string='Height min (cm)')
    height_max_cm = fields.Float(string='Height max (cm)')
    life_expectancy_min = fields.Integer(string='Lifespan min (years)')
    life_expectancy_max = fields.Integer(string='Lifespan max (years)')

    # --- Care ---
    grooming_need = fields.Selection(LEVEL, string='Grooming Need')
    shedding_level = fields.Selection(LEVEL, string='Shedding')
    exercise_need = fields.Selection(LEVEL, string='Exercise Need')
    trainability = fields.Selection(LEVEL, string='Trainability')
    common_health_issues = fields.Text(string='Common Health Issues')
    care_notes = fields.Text(string='Care Notes')

    # --- Reproduction ---
    first_heat_age_months = fields.Integer(string='First Heat (months)')
    heat_cycle_interval_months = fields.Integer(
        string='Heat Cycle Interval (months)', default=6,
    )
    gestation_days = fields.Integer(string='Gestation (days)', default=63)
    avg_litter_size = fields.Integer(string='Average Litter Size')

    # --- Growth (typical weight by age) ---
    growth_ids = fields.One2many(
        'petget.breed.growth', 'breed_id', string='Growth Milestones',
    )
