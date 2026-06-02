from odoo import api, fields, models

from .pet_clinic_sync_mixin import SYNC_SKIP


class PetPet(models.Model):
    _name = 'pet.pet'
    _inherit = ['pet.pet', 'pet.clinic.sync.mixin']

    x_pets_id = fields.Many2one(
        'x_pets',
        string='Clinic Pet',
        copy=False,
        index=True,
        ondelete='set null',
    )
    x_pets_active = fields.Boolean(related='x_pets_id.x_active', readonly=True)

    _sql_constraints = [
        (
            'pet_pet_x_pets_company_uniq',
            'unique(x_pets_id, company_id)',
            'Each clinic pet can only be linked to one Pet Management record per company.',
        ),
    ]

    @api.model
    def _vals_from_x_pets(self, x_pet):
        species = self.env['pet.clinic.species.map'].pet_species_for_x_species(
            x_pet.x_species,
        )
        breed = self._pm_breed_from_clinic_line(x_pet.x_breed)
        vals = {
            'name': x_pet.x_name or 'Unnamed',
            'owner_id': x_pet.x_owner.id,
            'species_id': species.id if species else False,
            'breed_id': breed.id if breed else False,
            'dob': x_pet.x_date_of_birth,
            'gender': self._pm_gender_from_clinic(x_pet.x_gender),
            'neutered': self._pm_neutered_from_clinic(x_pet.x_reproductive_status),
            'status': self._pm_status_from_clinic(x_pet.x_active),
            'microchip_no': x_pet.x_microchip_number or False,
            'x_pets_id': x_pet.id,
        }
        if x_pet.x_avatar_image:
            vals['image_1920'] = x_pet.x_avatar_image
        return vals

    def _vals_to_x_pets(self):
        self.ensure_one()
        x_species = self.env['pet.clinic.species.map'].x_species_for_pet_species(
            self.species_id,
        )
        breed_line = self._clinic_breed_line_from_pm(self.breed_id, x_species)
        vals = {
            'x_name': self.name,
            'x_owner': self.owner_id.id,
            'x_species': x_species.id if x_species else False,
            'x_breed': breed_line.id if breed_line else False,
            'x_date_of_birth': self.dob,
            'x_active': self.status == 'active',
        }
        gender = self._clinic_gender_from_pm(self.gender)
        if gender:
            vals['x_gender'] = gender
        if self.microchip_no and self.microchip_no not in ('New',):
            vals['x_microchip_number'] = self.microchip_no
        if self.neutered and self.gender == 'female':
            vals['x_reproductive_status'] = 'Spayed'
        elif self.neutered and self.gender == 'male':
            vals['x_reproductive_status'] = 'Neutered'
        if self.image_1920:
            vals['x_avatar_image'] = self.image_1920
        return vals

    def _sync_to_x_pets(self):
        XPets = self.env['x_pets'].with_context(**{SYNC_SKIP: True})
        for pet in self:
            if not pet.owner_id:
                continue
            if pet.x_pets_id:
                pet.x_pets_id.write(pet._vals_to_x_pets())
            else:
                x_pet = XPets.create(pet._vals_to_x_pets())
                pet.with_context(**{SYNC_SKIP: True}).write({'x_pets_id': x_pet.id})

    @api.model_create_multi
    def create(self, vals_list):
        pets = super().create(vals_list)
        if not self.env.context.get(SYNC_SKIP):
            pets._sync_to_x_pets()
        return pets

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get(SYNC_SKIP):
            sync_fields = {
                'name', 'owner_id', 'species_id', 'breed_id', 'dob', 'gender',
                'neutered', 'status', 'microchip_no', 'image_1920',
            }
            if sync_fields.intersection(vals):
                self._sync_to_x_pets()
        return res

    def action_open_clinic_pet(self):
        self.ensure_one()
        if not self.x_pets_id:
            self._sync_to_x_pets()
        if not self.x_pets_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': self.x_pets_id.x_name,
            'res_model': 'x_pets',
            'res_id': self.x_pets_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def sync_from_clinic_pets(self, x_pets=None):
        """Create or update pet.pet records from x_pets (bulk / post_init)."""
        if x_pets is None:
            x_pets = self.env['x_pets'].search([])
        created = updated = 0
        for x_pet in x_pets:
            if not x_pet.x_owner:
                continue
            vals = self._vals_from_x_pets(x_pet)
            if not vals.get('species_id'):
                continue
            pet = self.search([('x_pets_id', '=', x_pet.id)], limit=1)
            if pet:
                pet.with_context(**{SYNC_SKIP: True}).write(vals)
                updated += 1
            else:
                self.with_context(**{SYNC_SKIP: True}).create(vals)
                created += 1
        return created, updated
