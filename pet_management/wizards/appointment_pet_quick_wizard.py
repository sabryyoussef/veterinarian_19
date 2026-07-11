# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class PetAppointmentPetQuickWizard(models.TransientModel):
    _name = 'pet.appointment.pet.quick.wizard'
    _description = 'Appointment Pet / Health Quick Details'

    appointment_id = fields.Many2one('pet.appointment', required=True, ondelete='cascade')
    owner_id = fields.Many2one('res.partner', string='Owner', required=True)
    pet_id = fields.Many2one('pet.pet', string='Pet')
    name = fields.Char(string='Pet Name', required=True)
    species_id = fields.Many2one('pet.species', string='Species', required=True)
    breed_id = fields.Many2one(
        'pet.breed', string='Breed',
        domain="[('species_id', '=', species_id)]",
    )
    allergies = fields.Text(string='Allergies')
    chronic_conditions = fields.Text(string='Chronic Conditions')
    dietary_restrictions = fields.Text(string='Dietary Restrictions')
    behavior_notes = fields.Text(string='Behavior Notes')

    @api.model
    def _require_saved_appointment(self, appointment):
        if not appointment or not appointment.exists():
            raise UserError(_(
                "Save the appointment before creating or editing pet health details."
            ))
        return appointment

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        appt_id = res.get('appointment_id') or self.env.context.get('default_appointment_id')
        # create() may call default_get only for other missing fields while appointment_id
        # is already provided in vals — do not raise in that path.
        opening_wizard = (
            'appointment_id' in fields_list
            or 'default_appointment_id' in self.env.context
        )
        if opening_wizard and (not appt_id or not isinstance(appt_id, int)):
            raise UserError(_(
                "Save the appointment before creating or editing pet health details."
            ))
        if not appt_id or not isinstance(appt_id, int):
            return res
        appointment = self._require_saved_appointment(
            self.env['pet.appointment'].browse(appt_id)
        )
        res['appointment_id'] = appointment.id
        owner = appointment.intake_owner_id or appointment.owner_id
        if not owner and self.env.context.get('default_owner_id'):
            owner = self.env['res.partner'].browse(self.env.context['default_owner_id'])
        if not owner:
            raise UserError(_("Select an owner before creating a pet."))
        res['owner_id'] = owner.id
        pet = appointment.pet_id
        if pet:
            res.update({
                'pet_id': pet.id,
                'name': pet.name,
                'species_id': pet.species_id.id,
                'breed_id': pet.breed_id.id if pet.breed_id else False,
                'allergies': pet.allergies or '',
                'chronic_conditions': pet.chronic_conditions or '',
                'dietary_restrictions': pet.dietary_restrictions or '',
                'behavior_notes': pet.behavior_notes or '',
            })
        return res

    @api.onchange('species_id')
    def _onchange_species_id(self):
        if self.breed_id and self.breed_id.species_id != self.species_id:
            self.breed_id = False

    @api.model
    def _health_value_for_save(self, submitted, existing):
        """Blank → 'No' only when the pet field is currently empty. Never overwrite real notes."""
        submitted = (submitted or '').strip()
        existing = (existing or '').strip()
        if submitted:
            return submitted
        if not existing:
            return _('No')
        return existing

    def action_save(self):
        self.ensure_one()
        appointment = self._require_saved_appointment(self.appointment_id)
        if not self.owner_id:
            raise UserError(_("Select an owner before creating a pet."))
        if appointment.intake_owner_id and appointment.intake_owner_id != self.owner_id:
            raise ValidationError(_("Wizard owner must match the appointment owner."))

        # Always edit the appointment's current pet when one is already linked.
        existing_pet = appointment.pet_id or self.pet_id
        health_vals = {
            'allergies': self._health_value_for_save(
                self.allergies, existing_pet.allergies if existing_pet else ''),
            'chronic_conditions': self._health_value_for_save(
                self.chronic_conditions, existing_pet.chronic_conditions if existing_pet else ''),
            'dietary_restrictions': self._health_value_for_save(
                self.dietary_restrictions, existing_pet.dietary_restrictions if existing_pet else ''),
            'behavior_notes': self._health_value_for_save(
                self.behavior_notes, existing_pet.behavior_notes if existing_pet else ''),
        }
        pet_vals = {
            'name': self.name,
            'species_id': self.species_id.id,
            'breed_id': self.breed_id.id if self.breed_id else False,
            'owner_id': self.owner_id.id,
            **health_vals,
        }

        if existing_pet:
            if existing_pet.owner_id != self.owner_id:
                raise ValidationError(
                    _("Cannot reassign this pet to a different owner from the wizard.")
                )
            existing_pet.write(pet_vals)
            pet = existing_pet
        else:
            pet = self.env['pet.pet'].create(pet_vals)

        appt_vals = {'pet_id': pet.id}
        if not appointment.intake_owner_id:
            appt_vals['intake_owner_id'] = self.owner_id.id
        appointment.write(appt_vals)
        return {'type': 'ir.actions.act_window_close'}
