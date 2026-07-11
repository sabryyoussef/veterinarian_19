# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError, ValidationError


@tagged('post_install', '-at_install', 'pet_intake')
class TestAppointmentIntakeUX(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.species = cls.env['pet.species'].search([], limit=1)
        if not cls.species:
            cls.species = cls.env['pet.species'].create({'name': 'Dog'})
        cls.breed = cls.env['pet.breed'].search([('species_id', '=', cls.species.id)], limit=1)
        if not cls.breed:
            cls.breed = cls.env['pet.breed'].create({
                'name': 'Mixed',
                'species_id': cls.species.id,
            })
        cls.owner_one = cls.env['res.partner'].create({
            'name': 'Intake Owner One Pet',
            'phone': '01000000001',
            'email': 'one-pet@example.com',
        })
        cls.pet_only = cls.env['pet.pet'].create({
            'name': 'Solo Pet',
            'owner_id': cls.owner_one.id,
            'species_id': cls.species.id,
            'breed_id': cls.breed.id,
            'allergies': 'Chicken',
        })
        cls.owner_multi = cls.env['res.partner'].create({
            'name': 'Intake Owner Multi',
            'phone': '01000000002',
        })
        cls.pet_a = cls.env['pet.pet'].create({
            'name': 'Multi A',
            'owner_id': cls.owner_multi.id,
            'species_id': cls.species.id,
        })
        cls.pet_b = cls.env['pet.pet'].create({
            'name': 'Multi B',
            'owner_id': cls.owner_multi.id,
            'species_id': cls.species.id,
        })
        cls.owner_none = cls.env['res.partner'].create({
            'name': 'Intake Owner No Pets',
            'phone': '01000000003',
        })
        cls.Appointment = cls.env['pet.appointment']
        cls.Wizard = cls.env['pet.appointment.pet.quick.wizard']
        # Avoid calendar sync side-effects when creating appointments without a pet/owner partner.
        cls.env['ir.config_parameter'].sudo().set_param(
            'pet_management.enable_calendar_integration', 'False'
        )

    def _appt_vals(self, **extra):
        vals = {
            'title': 'Intake test',
            'start_datetime': '2026-07-11 12:00:00',
            'end_datetime': '2026-07-11 12:30:00',
            'sync_to_calendar': False,
        }
        vals.update(extra)
        return vals
    def test_01_medical_visit_line_requires_visit(self):
        visit = self.env['pet.medical.visit'].create({
            'pet_id': self.pet_only.id,
            'reason': 'Line guard test',
            'date': '2026-07-11 10:00:00',
        })
        line = self.env['pet.medical.visit.line'].create({
            'visit_id': visit.id,
            'name': 'Exam',
            'line_type': 'service',
            'quantity': 1.0,
            'price_unit': 100.0,
        })
        self.assertTrue(line.visit_id)
        with self.assertRaises(ValidationError):
            self.env['pet.medical.visit.line'].create({
                'name': 'Orphan line',
                'line_type': 'service',
                'quantity': 1.0,
                'price_unit': 50.0,
            })

    def test_02_appointment_defaults_emergency_medical(self):
        defaults = self.Appointment.default_get(['primary_type', 'is_medical'])
        self.assertEqual(defaults.get('primary_type'), 'emergency')
        self.assertTrue(defaults.get('is_medical'))
        appt = self.Appointment.create(self._appt_vals(
            pet_id=self.pet_only.id,
            title='Default type test',
            start_datetime='2026-07-11 11:00:00',
            end_datetime='2026-07-11 11:30:00',
        ))
        self.assertEqual(appt.primary_type, 'emergency')
        self.assertTrue(appt.is_medical)
        self.assertEqual(appt.intake_owner_id, self.owner_one)
        self.assertEqual(appt.owner_phone, '01000000001')
        self.assertEqual(appt.owner_contact_display, '01000000001')
        self.assertEqual(appt.owner_phone, self.owner_one.phone)
        self.assertNotIn('mobile', self.env['res.partner']._fields)
        self.assertNotIn('owner_mobile', self.Appointment._fields)

    def test_03_owner_one_pet_auto_selects(self):
        appt = self.Appointment.new({
            'intake_owner_id': self.owner_one.id,
        })
        appt._onchange_intake_owner_id()
        self.assertEqual(appt.pet_id, self.pet_only)

    def test_04_owner_multi_pet_no_auto_select(self):
        appt = self.Appointment.new({
            'intake_owner_id': self.owner_multi.id,
            'pet_id': self.pet_only.id,
        })
        appt._onchange_intake_owner_id()
        self.assertFalse(appt.pet_id)

    def test_05_owner_change_clears_foreign_pet(self):
        appt = self.Appointment.new({
            'intake_owner_id': self.owner_one.id,
            'pet_id': self.pet_only.id,
        })
        appt.intake_owner_id = self.owner_multi
        appt._onchange_intake_owner_id()
        self.assertFalse(appt.pet_id)

    def test_06_unsaved_appointment_wizard_rejected(self):
        unsaved = self.Appointment.new({
            'intake_owner_id': self.owner_none.id,
            'title': 'Unsaved',
        })
        with self.assertRaises(UserError) as err:
            unsaved.action_open_pet_quick_wizard()
        self.assertIn('Save the appointment', str(err.exception))
        before = self.env['pet.pet'].search_count([('owner_id', '=', self.owner_none.id)])
        with self.assertRaises(UserError) as err2:
            self.Wizard.with_context(default_appointment_id=False).default_get(
                ['appointment_id', 'owner_id', 'name', 'species_id']
            )
        self.assertIn('Save the appointment', str(err2.exception))
        after = self.env['pet.pet'].search_count([('owner_id', '=', self.owner_none.id)])
        self.assertEqual(before, after)

    def test_07_owner_pet_consistency_constraint(self):
        appt = self.Appointment.create(self._appt_vals(
            pet_id=self.pet_only.id,
            intake_owner_id=self.owner_one.id,
            title='Consistency',
            start_datetime='2026-07-11 13:00:00',
            end_datetime='2026-07-11 13:30:00',
        ))
        with self.assertRaises(ValidationError):
            appt.write({
                'intake_owner_id': self.owner_multi.id,
            })

    def test_08_wizard_edit_does_not_duplicate(self):
        appt = self.Appointment.create(self._appt_vals(
            pet_id=self.pet_only.id,
            title='Wizard edit',
            start_datetime='2026-07-11 14:00:00',
            end_datetime='2026-07-11 14:30:00',
        ))
        before = self.env['pet.pet'].search_count([('owner_id', '=', self.owner_one.id)])
        wiz = self.Wizard.create({
            'appointment_id': appt.id,
            'owner_id': self.owner_one.id,
            'pet_id': self.pet_only.id,
            'name': 'Solo Pet Updated',
            'species_id': self.species.id,
            'breed_id': self.breed.id,
            'allergies': 'Chicken',
            'chronic_conditions': '',
            'dietary_restrictions': '',
            'behavior_notes': '',
        })
        wiz.action_save()
        after = self.env['pet.pet'].search_count([('owner_id', '=', self.owner_one.id)])
        self.assertEqual(before, after)
        self.assertEqual(self.pet_only.name, 'Solo Pet Updated')
        self.assertEqual(self.pet_only.allergies, 'Chicken')
        self.assertEqual(self.pet_only.chronic_conditions, 'No')

    def test_09_wizard_create_on_saved_appointment_without_pet(self):
        appt = self.Appointment.create(self._appt_vals(
            intake_owner_id=self.owner_none.id,
            title='Wizard create no pet',
            start_datetime='2026-07-11 15:00:00',
            end_datetime='2026-07-11 15:30:00',
        ))
        self.assertFalse(appt.pet_id)
        before = self.env['pet.pet'].search_count([('owner_id', '=', self.owner_none.id)])
        action = appt.action_open_pet_quick_wizard()
        self.assertEqual(action['res_model'], 'pet.appointment.pet.quick.wizard')
        wiz = self.Wizard.create({
            'appointment_id': appt.id,
            'owner_id': self.owner_none.id,
            'pet_id': False,
            'name': 'Brand New Pet',
            'species_id': self.species.id,
            'allergies': '',
            'chronic_conditions': '',
            'dietary_restrictions': '',
            'behavior_notes': '',
        })
        wiz.action_save()
        after = self.env['pet.pet'].search_count([('owner_id', '=', self.owner_none.id)])
        self.assertEqual(after, before + 1)
        self.assertEqual(appt.pet_id.name, 'Brand New Pet')
        self.assertEqual(appt.pet_id.owner_id, self.owner_none)
        self.assertEqual(appt.pet_id.allergies, 'No')
        self.assertEqual(appt.pet_id.chronic_conditions, 'No')

    def test_10_wizard_preserves_existing_health_notes(self):
        self.assertEqual(self.pet_only.allergies, 'Chicken')
        appt = self.Appointment.create(self._appt_vals(
            pet_id=self.pet_only.id,
            title='Health preserve',
            start_datetime='2026-07-11 16:00:00',
            end_datetime='2026-07-11 16:30:00',
        ))
        wiz = self.Wizard.create({
            'appointment_id': appt.id,
            'owner_id': self.owner_one.id,
            'pet_id': self.pet_only.id,
            'name': self.pet_only.name,
            'species_id': self.species.id,
            'allergies': '',
            'chronic_conditions': 'Arthritis',
            'dietary_restrictions': '',
            'behavior_notes': '',
        })
        wiz.action_save()
        self.assertEqual(self.pet_only.allergies, 'Chicken')
        self.assertEqual(self.pet_only.chronic_conditions, 'Arthritis')

    def test_11_clinical_type_enables_medical(self):
        appt = self.Appointment.new({'primary_type': 'surgery', 'is_medical': False})
        appt._onchange_primary_type_medical()
        self.assertTrue(appt.is_medical)

    def test_12_pet_action_opens_kanban(self):
        self.env.user.group_ids = [(4, self.env.ref('pet_management.group_pet_appointments_user_all').id)]
        action = self.pet_only.action_open_appointments()
        self.assertEqual(action['view_mode'], 'kanban,list,form')
        self.assertEqual(action['context'].get('default_pet_id'), self.pet_only.id)

    def test_13_emergency_maps_to_visit_type(self):
        mapped = self.Appointment._map_primary_type_to_visit_type('emergency')
        self.assertEqual(mapped, 'emergency')

    def test_14_wizard_without_owner_rejected(self):
        appt = self.Appointment.create(self._appt_vals(
            title='No owner',
            start_datetime='2026-07-11 17:00:00',
            end_datetime='2026-07-11 17:30:00',
        ))
        with self.assertRaises(UserError) as err:
            appt.action_open_pet_quick_wizard()
        self.assertIn('Select an owner', str(err.exception))

    def test_15_wizard_edit_always_uses_appointment_pet(self):
        """Saved appointment with pet_id always updates that pet, never creates another."""
        appt = self.Appointment.create(self._appt_vals(
            pet_id=self.pet_only.id,
            title='Force edit linked pet',
            start_datetime='2026-07-11 18:00:00',
            end_datetime='2026-07-11 18:30:00',
        ))
        before = self.env['pet.pet'].search_count([])
        wiz = self.Wizard.create({
            'appointment_id': appt.id,
            'owner_id': self.owner_one.id,
            'pet_id': False,  # even if wizard pet cleared, appointment pet wins
            'name': 'Still Solo',
            'species_id': self.species.id,
            'allergies': 'Chicken',
            'chronic_conditions': '',
            'dietary_restrictions': '',
            'behavior_notes': '',
        })
        wiz.action_save()
        self.assertEqual(self.env['pet.pet'].search_count([]), before)
        self.assertEqual(appt.pet_id, self.pet_only)
        self.assertEqual(self.pet_only.name, 'Still Solo')

    def _no_pet_draft(self, title='No-pet draft'):
        return self.Appointment.create(self._appt_vals(
            intake_owner_id=self.owner_none.id,
            title=title,
            start_datetime='2026-07-12 10:00:00',
            end_datetime='2026-07-12 10:30:00',
            is_medical=True,
            primary_type='emergency',
        ))

    def _assert_pet_required(self, method, *args, **kwargs):
        with self.assertRaises(UserError) as err:
            method(*args, **kwargs)
        self.assertIn(
            'Select or create a pet before confirming or billing this appointment.',
            str(err.exception),
        )

    def test_16_draft_without_pet_can_be_created(self):
        appt = self._no_pet_draft('Create without pet')
        self.assertTrue(appt.id)
        self.assertEqual(appt.state, 'draft')
        self.assertFalse(appt.pet_id)
        self.assertEqual(appt.intake_owner_id, self.owner_none)

    def test_17_saved_no_pet_opens_wizard(self):
        appt = self._no_pet_draft('Wizard after save')
        action = appt.action_open_pet_quick_wizard()
        self.assertEqual(action['res_model'], 'pet.appointment.pet.quick.wizard')

    def test_18_no_pet_cannot_confirm(self):
        appt = self._no_pet_draft('Block confirm')
        self._assert_pet_required(appt.set_to_confirmed)
        self.assertEqual(appt.state, 'draft')
        self.assertFalse(appt.medical_visit_id)
        self.assertFalse(appt.sale_order_id)

    def test_19_no_pet_cannot_start(self):
        appt = self._no_pet_draft('Block start')
        self._assert_pet_required(appt.set_to_in_progress)
        self.assertEqual(appt.state, 'draft')

    def test_20_no_pet_cannot_complete(self):
        appt = self._no_pet_draft('Block complete')
        self._assert_pet_required(appt.set_to_done)
        self.assertEqual(appt.state, 'draft')

    def test_21_no_pet_cannot_create_medical_visit(self):
        appt = self._no_pet_draft('Block medical visit')
        self._assert_pet_required(appt.action_create_medical_visit)
        self.assertFalse(appt.medical_visit_id)

    def test_22_no_pet_cannot_create_sale_order(self):
        appt = self._no_pet_draft('Block sale order')
        self._assert_pet_required(appt.action_create_or_open_sale_order)
        self.assertFalse(appt.sale_order_id)

    def test_23_no_pet_cannot_create_invoice(self):
        appt = self._no_pet_draft('Block invoice')
        self._assert_pet_required(appt.action_confirm_and_create_invoice)
        self.assertFalse(appt.invoice_id)
        self.assertFalse(appt.sale_order_id)

    def test_24_no_pet_direct_state_write_blocked(self):
        appt = self._no_pet_draft('Block write state')
        self._assert_pet_required(appt.write, {'state': 'confirmed'})
        self.assertEqual(appt.state, 'draft')

    def test_25_with_pet_confirm_creates_medical_visit(self):
        appt = self.Appointment.create(self._appt_vals(
            pet_id=self.pet_only.id,
            title='Confirm with pet',
            start_datetime='2026-07-12 11:00:00',
            end_datetime='2026-07-12 11:30:00',
            is_medical=True,
            primary_type='emergency',
            auto_create_facility=True,
        ))
        appt.set_to_confirmed()
        self.assertEqual(appt.state, 'confirmed')
        self.assertTrue(appt.medical_visit_id)
        self.assertEqual(appt.medical_visit_id.pet_id, self.pet_only)

    def test_26_wizard_then_confirm_workflow(self):
        appt = self._no_pet_draft('Wizard then confirm')
        self._assert_pet_required(appt.set_to_confirmed)
        wiz = self.Wizard.create({
            'appointment_id': appt.id,
            'owner_id': self.owner_none.id,
            'pet_id': False,
            'name': 'Guard Flow Pet',
            'species_id': self.species.id,
            'allergies': '',
            'chronic_conditions': '',
            'dietary_restrictions': '',
            'behavior_notes': '',
        })
        wiz.action_save()
        self.assertTrue(appt.pet_id)
        appt.set_to_confirmed()
        self.assertEqual(appt.state, 'confirmed')
        self.assertTrue(appt.medical_visit_id)

    def test_27_calendar_sync_no_pet_uses_intake_owner(self):
        """Owner-first draft must not create calendar.attendee with empty partner_id."""
        self.env['ir.config_parameter'].sudo().set_param(
            'pet_management.enable_calendar_integration', 'True'
        )
        appt = self.Appointment.create(self._appt_vals(
            intake_owner_id=self.owner_none.id,
            title='Calendar sync no pet',
            start_datetime='2026-07-13 10:00:00',
            end_datetime='2026-07-13 10:30:00',
            sync_to_calendar=True,
        ))
        self.assertFalse(appt.pet_id)
        self.assertFalse(appt.owner_id)
        self.assertTrue(appt.calendar_event_id)
        partners = appt.calendar_event_id.partner_ids
        self.assertIn(self.owner_none, partners)
        # No attendee rows without partner_id
        bad = self.env['calendar.attendee'].search([
            ('event_id', '=', appt.calendar_event_id.id),
            ('partner_id', '=', False),
        ])
        self.assertFalse(bad)

    def test_28_calendar_sync_without_any_owner_skips_attendees(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'pet_management.enable_calendar_integration', 'True'
        )
        appt = self.Appointment.create(self._appt_vals(
            title='Calendar sync no owner',
            start_datetime='2026-07-13 11:00:00',
            end_datetime='2026-07-13 11:30:00',
            sync_to_calendar=True,
        ))
        self.assertTrue(appt.calendar_event_id)
        self.assertFalse(appt.calendar_event_id.partner_ids)
        bad = self.env['calendar.attendee'].search([
            ('event_id', '=', appt.calendar_event_id.id),
            ('partner_id', '=', False),
        ])
        self.assertFalse(bad)

    def test_29_wizard_saves_gender_dob_and_age(self):
        appt = self.Appointment.create(self._appt_vals(
            intake_owner_id=self.owner_none.id,
            title='Wizard gender dob',
            start_datetime='2026-07-14 10:00:00',
            end_datetime='2026-07-14 10:30:00',
        ))
        wiz = self.Wizard.create({
            'appointment_id': appt.id,
            'owner_id': self.owner_none.id,
            'pet_id': False,
            'name': 'Age Gender Pet',
            'species_id': self.species.id,
            'gender': 'female',
            'dob': '2024-01-15',
            'allergies': '',
            'chronic_conditions': '',
            'dietary_restrictions': '',
            'behavior_notes': '',
        })
        self.assertTrue(wiz.age_display)
        self.assertNotEqual(wiz.age_display, 'N/A')
        wiz.action_save()
        pet = appt.pet_id
        self.assertEqual(pet.gender, 'female')
        self.assertEqual(str(pet.dob), '2024-01-15')
        self.assertTrue(pet.age_display)
        self.assertEqual(appt.pet_gender, 'female')
        self.assertEqual(appt.pet_age_display, pet.age_display)

    def test_30_wizard_age_years_sets_dob(self):
        wiz = self.Wizard.new({
            'age_years_input': 2.0,
        })
        wiz._onchange_age_years_input()
        self.assertTrue(wiz.dob)
        wiz._compute_age_display()
        self.assertRegex(wiz.age_display or '', r'\d+ y')

    def test_31_medical_visit_create_sale_order_via_appointment(self):
        """Sale order creation is driven from medical visit, linked to appointment."""
        appt = self.Appointment.create(self._appt_vals(
            pet_id=self.pet_only.id,
            title='Visit billing SO',
            start_datetime='2026-07-15 11:00:00',
            end_datetime='2026-07-15 11:30:00',
            is_medical=True,
            primary_type='emergency',
            auto_create_facility=True,
        ))
        appt.set_to_confirmed()
        visit = appt.medical_visit_id
        self.assertTrue(visit)
        self.assertFalse(appt.sale_order_id)
        action = visit.action_create_sale_order()
        self.assertTrue(appt.sale_order_id)
        self.assertEqual(action.get('res_id'), appt.sale_order_id.id)
        self.assertEqual(visit.appointment_sale_order_id, appt.sale_order_id)

    def test_32_medical_visit_create_sale_order_requires_appointment(self):
        visit = self.env['pet.medical.visit'].create({
            'pet_id': self.pet_only.id,
            'reason': 'Orphan visit billing',
            'status': 'scheduled',
            'date': '2026-07-15 12:00:00',
        })
        with self.assertRaises(UserError):
            visit.action_create_sale_order()

    def test_33_appointment_can_set_missing_owner_phone_and_email(self):
        """Reception can fill phone/email on the appointment after creating a contact without them."""
        owner = self.env['res.partner'].create({
            'name': 'No Contact Owner',
        })
        self.assertFalse(owner.phone)
        self.assertFalse(owner.email)
        appt = self.Appointment.create(self._appt_vals(
            intake_owner_id=owner.id,
            title='Fill contact details',
            start_datetime='2026-07-16 10:00:00',
            end_datetime='2026-07-16 10:30:00',
        ))
        self.assertFalse(appt.owner_phone)
        self.assertFalse(appt.owner_email)
        appt.write({
            'owner_phone': '01099998888',
            'owner_email': 'nocontact@example.com',
        })
        self.assertEqual(appt.owner_phone, '01099998888')
        self.assertEqual(appt.owner_email, 'nocontact@example.com')
        self.assertEqual(owner.phone, '01099998888')
        self.assertEqual(owner.email, 'nocontact@example.com')
        self.assertEqual(appt.owner_contact_display, '01099998888')

    def test_34_default_get_fills_available_start_and_end(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'pet_management.appointment_duration_default', '0.5'
        )
        defaults = self.Appointment.default_get(['start_datetime', 'end_datetime', 'vet_employee_id'])
        self.assertTrue(defaults.get('start_datetime'))
        self.assertTrue(defaults.get('end_datetime'))
        start = fields.Datetime.to_datetime(defaults['start_datetime'])
        end = fields.Datetime.to_datetime(defaults['end_datetime'])
        self.assertEqual(end - start, timedelta(minutes=30))
        self.assertEqual(start.second, 0)
        self.assertEqual(start.minute % 15, 0)

    def test_35_start_change_moves_end_preserving_duration(self):
        appt = self.Appointment.create(self._appt_vals(
            pet_id=self.pet_only.id,
            title='Move start keeps duration',
            start_datetime='2026-07-16 11:00:00',
            end_datetime='2026-07-16 12:00:00',
            vet_employee_id=False,
        ))
        appt.write({'start_datetime': '2026-07-16 14:00:00'})
        self.assertEqual(str(appt.start_datetime), '2026-07-16 14:00:00')
        self.assertEqual(str(appt.end_datetime), '2026-07-16 15:00:00')

    def test_36_next_available_slot_skips_vet_overlap(self):
        emp = self.env.user.employee_id
        if not emp:
            emp = self.env['hr.employee'].create({
                'name': 'Slot Vet',
                'user_id': self.env.user.id,
            })
        busy = self.Appointment.create(self._appt_vals(
            pet_id=self.pet_only.id,
            title='Busy slot',
            start_datetime='2026-07-17 10:00:00',
            end_datetime='2026-07-17 11:00:00',
            vet_employee_id=emp.id,
        ))
        start, end = self.Appointment._find_next_available_slot(
            start_from=fields.Datetime.to_datetime('2026-07-17 10:15:00'),
            vet_id=emp.id,
            duration=timedelta(hours=1),
        )
        self.assertGreaterEqual(start, busy.end_datetime)
        self.assertEqual(end - start, timedelta(hours=1))
        self.assertFalse(self.Appointment._appointment_slot_busy(
            start, end, vet_id=emp.id,
        ))

    def test_37_calendar_resync_on_reschedule(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'pet_management.enable_calendar_integration', 'True'
        )
        appt = self.Appointment.create(self._appt_vals(
            pet_id=self.pet_only.id,
            intake_owner_id=self.owner_one.id,
            title='Reschedule sync',
            start_datetime='2026-07-18 10:00:00',
            end_datetime='2026-07-18 10:30:00',
            sync_to_calendar=True,
        ))
        self.assertTrue(appt.calendar_event_id)
        event = appt.calendar_event_id
        appt.write({
            'start_datetime': '2026-07-18 14:00:00',
            'title': 'Reschedule sync moved',
        })
        self.assertEqual(event.start, fields.Datetime.to_datetime('2026-07-18 14:00:00'))
        self.assertEqual(event.stop, fields.Datetime.to_datetime('2026-07-18 14:30:00'))
        self.assertIn('Reschedule sync moved', event.name)

    def test_38_calendar_deactivate_on_cancel(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'pet_management.enable_calendar_integration', 'True'
        )
        appt = self.Appointment.create(self._appt_vals(
            pet_id=self.pet_only.id,
            title='Cancel sync',
            start_datetime='2026-07-18 16:00:00',
            end_datetime='2026-07-18 16:30:00',
            sync_to_calendar=True,
            state='confirmed',
        ))
        event = appt.calendar_event_id
        self.assertTrue(event)
        self.assertTrue(event.active)
        appt.write({'state': 'cancelled'})
        self.assertFalse(event.active)

    def test_39_calendar_event_gets_appointment_type(self):
        if 'appointment.type' not in self.env:
            self.skipTest('appointment module not installed')
        self.env['ir.config_parameter'].sudo().set_param(
            'pet_management.enable_calendar_integration', 'True'
        )
        self.env['appointment.type'].ensure_clinic_pet_appointment_types()
        appt = self.Appointment.create(self._appt_vals(
            pet_id=self.pet_only.id,
            title='Typed emergency',
            primary_type='emergency',
            start_datetime='2026-07-19 09:00:00',
            end_datetime='2026-07-19 09:30:00',
            sync_to_calendar=True,
        ))
        self.assertTrue(appt.calendar_event_id)
        self.assertTrue(appt.calendar_event_id.appointment_type_id)
        self.assertEqual(
            appt.calendar_event_id.appointment_type_id.pet_primary_type,
            'emergency',
        )
        self.assertEqual(appt.calendar_event_id.pet_appointment_id, appt)

    def test_40_appointment_booking_creates_pet_appointment(self):
        if 'appointment.type' not in self.env:
            self.skipTest('appointment module not installed')
        self.env['appointment.type'].ensure_clinic_pet_appointment_types()
        atype = self.env['appointment.type'].search([
            ('pet_primary_type', '=', 'checkup'),
        ], limit=1)
        self.assertTrue(atype)
        customer = self.env['res.partner'].create({'name': 'Booking Customer'})
        event = self.env['calendar.event'].create({
            'name': 'Website Checkup Booking',
            'start': '2026-07-20 10:00:00',
            'stop': '2026-07-20 11:00:00',
            'appointment_type_id': atype.id,
            'appointment_status': 'booked',
            'partner_ids': [(6, 0, [customer.id])],
            'user_id': self.env.user.id,
        })
        self.assertTrue(event.pet_appointment_id)
        appt = event.pet_appointment_id
        self.assertEqual(appt.primary_type, 'checkup')
        self.assertEqual(appt.intake_owner_id, customer)
        self.assertEqual(appt.calendar_event_id, event)
        self.assertEqual(str(appt.start_datetime), '2026-07-20 10:00:00')
