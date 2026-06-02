"""Species mapping between clinic (x_species) and Pet Management (pet.species)."""
from odoo import api, fields, models


class PetClinicSpeciesMap(models.Model):
    _name = 'pet.clinic.species.map'
    _description = 'Clinic / Pet Management Species Map'
    _rec_name = 'display_name'

    pet_species_id = fields.Many2one(
        'pet.species', string='Pet Management Species', required=True, ondelete='cascade',
    )
    x_species_id = fields.Many2one(
        'x_species', string='Clinic Species', required=True, ondelete='cascade',
    )
    display_name = fields.Char(compute='_compute_display_name', store=True)

    _sql_constraints = [
        (
            'pet_clinic_species_map_pet_uniq',
            'unique(pet_species_id)',
            'Each Pet Management species can only be mapped once.',
        ),
        (
            'pet_clinic_species_map_x_uniq',
            'unique(x_species_id)',
            'Each clinic species can only be mapped once.',
        ),
    ]

    @api.depends('pet_species_id.name', 'x_species_id.x_name')
    def _compute_display_name(self):
        for rec in self:
            pet = rec.pet_species_id.name or '?'
            clinic = rec.x_species_id.x_name or '?'
            rec.display_name = f'{pet} ↔ {clinic}'

    @api.model
    def pet_species_for_x_species(self, x_species):
        """Return pet.species for an x_species record (mapped or by name)."""
        if not x_species:
            return self.env['pet.species']
        mapping = self.search([('x_species_id', '=', x_species.id)], limit=1)
        if mapping:
            return mapping.pet_species_id
        return self.env['pet.species'].search(
            [('name', '=ilike', x_species.x_name)], limit=1,
        )

    @api.model
    def x_species_for_pet_species(self, pet_species):
        """Return x_species for a pet.species record (mapped or by name)."""
        if not pet_species:
            return self.env['x_species']
        mapping = self.search([('pet_species_id', '=', pet_species.id)], limit=1)
        if mapping:
            return mapping.x_species_id
        return self.env['x_species'].search(
            [('x_name', '=ilike', pet_species.name)], limit=1,
        )
