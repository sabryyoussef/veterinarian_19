"""Shared sync helpers for x_pets <-> pet.pet (Phase 1)."""
from odoo import fields, models

SYNC_SKIP = 'pet_clinic_sync_skip'

GENDER_CLINIC_TO_PM = {
    'Male': 'male',
    'Female': 'female',
}
GENDER_PM_TO_CLINIC = {
    'male': 'Male',
    'female': 'Female',
}


class PetClinicSyncMixin(models.AbstractModel):
    _name = 'pet.clinic.sync.mixin'
    _description = 'Pet Clinic Sync Helpers'

    def _pm_gender_from_clinic(self, x_gender):
        return GENDER_CLINIC_TO_PM.get(x_gender, 'unknown')

    def _clinic_gender_from_pm(self, gender):
        return GENDER_PM_TO_CLINIC.get(gender, False)

    def _pm_neutered_from_clinic(self, reproductive_status):
        return reproductive_status in ('Spayed', 'Neutered')

    def _pm_status_from_clinic(self, x_active):
        return 'active' if x_active else 'inactive'

    def _pm_breed_from_clinic_line(self, species_line):
        """Find or create pet.breed from x_species_line."""
        if not species_line:
            return self.env['pet.breed']
        Breed = self.env['pet.breed']
        pet_species = self.env['pet.clinic.species.map'].pet_species_for_x_species(
            species_line.x_species_id,
        )
        if not pet_species:
            return self.env['pet.breed']
        breed = Breed.search([
            ('name', '=ilike', species_line.x_name),
            ('species_id', '=', pet_species.id),
        ], limit=1)
        if breed:
            return breed
        return Breed.create({
            'name': species_line.x_name,
            'species_id': pet_species.id,
            'company_id': self.env.company.id,
        })

    def _clinic_breed_line_from_pm(self, pet_breed, x_species):
        """Find or create x_species_line from pet.breed."""
        if not pet_breed or not x_species:
            return self.env['x_species_line']
        Line = self.env['x_species_line']
        line = Line.search([
            ('x_name', '=ilike', pet_breed.name),
            ('x_species_id', '=', x_species.id),
        ], limit=1)
        if line:
            return line
        return Line.create({
            'x_name': pet_breed.name,
            'x_species_id': x_species.id,
        })
