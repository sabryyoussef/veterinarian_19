from odoo import models, fields, api

class PetSpecies(models.Model):
    _name = 'pet.species'
    _description = 'Pet Species'
    _order = 'name'

    name = fields.Char(string="Name", required=True, index=True, help="Name of the species (e.g., Dog, Cat, Bird)")
    code = fields.Char(string="Code", help="Short code for the species")
    active = fields.Boolean(string="Active", default=True, help="Whether this species is active")
    color = fields.Integer(string="Color Index", default=1, help="Color index for kanban view display")  # For Odoo kanban color reference
    company_id = fields.Many2one('res.company', string="Company", default=lambda s: s.env.company, help="Company this species belongs to")
    
    # Computed fields
    pet_count = fields.Integer(string="Pet Count", compute='_compute_pet_count', store=True, help="Number of active pets of this species")
    breed_count = fields.Integer(string="Breed Count", compute='_compute_breed_count', store=True, help="Number of breeds for this species")
    vaccine_count = fields.Integer(string="Vaccine Count", compute='_compute_vaccine_count', store=True, help="Number of vaccines available for this species")
    
    # Related fields
    pet_ids = fields.One2many('pet.pet', 'species_id', string='Pets', help="Pets belonging to this species")
    breed_ids = fields.One2many('pet.breed', 'species_id', string='Breeds', help="Breeds of this species")
    vaccine_ids = fields.One2many('pet.vaccine', 'species_id', string='Vaccines', help="Vaccines available for this species")

    _sql_constraints = [
        ('uniq_species_company', 'unique(name, company_id)', 'Species must be unique per company.'),
    ]

    @api.depends('pet_ids')
    def _compute_pet_count(self):
        for species in self:
            species.pet_count = len(species.pet_ids.filtered(lambda p: p.status != 'deceased'))

    @api.depends('breed_ids')
    def _compute_breed_count(self):
        for species in self:
            species.breed_count = len(species.breed_ids)

    @api.depends('vaccine_ids')
    def _compute_vaccine_count(self):
        for species in self:
            species.vaccine_count = len(species.vaccine_ids)

    def action_view_pets(self):
        """Action to view pets of this species"""
        action = self.env.ref('pet_management.action_pet_pet').read()[0]
        action['domain'] = [('species_id', '=', self.id)]
        action['context'] = {'default_species_id': self.id}
        return action

    def action_view_breeds(self):
        """Action to view breeds of this species"""
        action = self.env.ref('pet_management.action_pet_breed').read()[0]
        action['domain'] = [('species_id', '=', self.id)]
        action['context'] = {'default_species_id': self.id}
        return action

    def action_view_vaccines(self):
        """Action to view vaccines for this species"""
        action = self.env.ref('pet_management.action_pet_vaccine').read()[0]
        action['domain'] = [('species_id', '=', self.id)]
        action['context'] = {'default_species_id': self.id}
        return action
