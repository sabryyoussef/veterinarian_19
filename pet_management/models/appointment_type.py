# -*- coding: utf-8 -*-
"""Link Odoo Appointment types to pet.appointment primary types."""
from odoo import api, fields, models, _


class AppointmentType(models.Model):
    _inherit = 'appointment.type'

    pet_primary_type = fields.Selection(
        selection=[
            ('checkup', 'Regular Exam'),
            ('emergency', 'Emergency Exam'),
            ('home_visit', 'Home Visit'),
            ('surgery', 'Surgery'),
            ('dental', 'Dental'),
            ('comprehensive', 'Comprehensive Care'),
            ('other', 'Other'),
            ('grooming', 'Grooming'),
        ],
        string='Pet Clinic Primary Type',
        index=True,
        help='When set, bookings of this type create/update a pet.appointment '
             'and calendar events synced from the clinic use this Appointment type.',
    )

    @api.model
    def ensure_clinic_pet_appointment_types(self):
        """Idempotent clinic appointment types used for Calendar/Appointment linking."""
        specs = [
            ('emergency', 'Clinic Emergency', 10),
            ('checkup', 'Clinic Checkup', 20),
            ('home_visit', 'Clinic Home Visit', 30),
            ('surgery', 'Clinic Surgery', 40),
            ('dental', 'Clinic Dental', 50),
            ('comprehensive', 'Clinic Comprehensive Care', 60),
            ('grooming', 'Clinic Grooming', 70),
            ('other', 'Clinic Other', 80),
        ]
        Type = self.sudo()
        # Bind existing unlabeled type named like Checkup if present
        existing_checkup = Type.search([
            ('pet_primary_type', '=', False),
            ('name', 'ilike', 'checkup'),
        ], limit=1)
        if existing_checkup:
            existing_checkup.pet_primary_type = 'checkup'

        created_or_updated = Type.browse()
        for primary, name, seq in specs:
            rec = Type.search([('pet_primary_type', '=', primary)], limit=1)
            vals = {
                'name': name,
                'pet_primary_type': primary,
                'schedule_based_on': 'users',
                'appointment_duration': 1.0,
                'sequence': seq,
                'staff_user_ids': [(4, self.env.user.id)],
                'appointment_tz': self.env.user.tz or 'Africa/Cairo',
            }
            if rec:
                # Do not overwrite staff list on every upgrade — only ensure mapping/name.
                rec.write({
                    'pet_primary_type': primary,
                    'sequence': seq,
                })
            else:
                rec = Type.create(vals)
            created_or_updated |= rec
        return created_or_updated
