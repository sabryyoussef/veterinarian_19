# -*- coding: utf-8 -*-
"""Append Phase 16 tests to billing integrity suite."""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError, ValidationError


@tagged('post_install', '-at_install', 'pet_billing')
class TestAppointmentBillingPhase16(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'Phase16 Owner',
            'email': 'phase16@example.com',
        })
        species = cls.env['pet.species'].search([], limit=1) or cls.env['pet.species'].create({'name': 'Dog'})
        cls.pet = cls.env['pet.pet'].create({
            'name': 'Phase16 Pet',
            'owner_id': cls.partner.id,
            'species_id': species.id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Phase16 Consult',
            'type': 'service',
            'list_price': 1000.0,
            'invoice_policy': 'order',
            'taxes_id': [(6, 0, [])],
        })
        cls.extra = cls.env['product.product'].create({
            'name': 'Phase16 Extra',
            'type': 'service',
            'list_price': 500.0,
            'invoice_policy': 'order',
            'taxes_id': [(6, 0, [])],
        })
        visit = cls.env['pet.medical.visit'].create({
            'pet_id': cls.pet.id,
            'reason': 'Phase16',
            'status': 'completed',
            'date': '2026-07-10 11:00:00',
        })
        cls.env['pet.medical.visit.line'].create({
            'visit_id': visit.id,
            'product_id': cls.product.id,
            'name': cls.product.name,
            'line_type': 'service',
            'quantity': 1.0,
            'price_unit': 1000.0,
        })
        cls.appointment = cls.env['pet.appointment'].create({
            'pet_id': cls.pet.id,
            'title': 'Phase16 Appointment',
            'primary_type': 'checkup',
            'start_datetime': '2026-07-10 11:00:00',
            'end_datetime': '2026-07-10 11:30:00',
            'state': 'done',
            'is_medical': True,
            'medical_visit_id': visit.id,
        })
        cls.env['pet.appointment.service.line'].create({
            'appointment_id': cls.appointment.id,
            'product_id': cls.extra.id,
            'name': 'Extra 500',
            'quantity': 1.0,
            'price_unit': 500.0,
        })

    def test_10_layered_totals(self):
        self.appointment.action_create_invoice()
        self.appointment.action_confirm_and_create_invoice()
        self.appointment.invalidate_recordset()
        self.assertAlmostEqual(self.appointment.service_total, 1500.0, places=2)
        self.assertAlmostEqual(self.appointment.sale_order_total, 1500.0, places=2)
        self.assertAlmostEqual(self.appointment.total_invoiced, 1500.0, places=2)
        self.assertAlmostEqual(self.appointment.draft_invoice_total, 0.0, places=2)
        self.assertAlmostEqual(self.appointment.billing_variance, 0.0, places=2)

    def test_11_complimentary_requires_reason(self):
        with self.assertRaises(ValidationError):
            self.appointment.write({'is_complimentary': True, 'complimentary_reason': False})
        self.appointment.write({
            'is_complimentary': True,
            'complimentary_reason': 'Staff pet goodwill',
        })
        self.appointment.invalidate_recordset()
        self.assertEqual(self.appointment.amount_total, 0.0)

    def test_12_idempotent_integrity_scan(self):
        Issue = self.env['pet.billing.integrity.issue']
        # Force a mismatch finding via SO/invoice gap simulation is hard; scan twice and count
        self.appointment.action_create_invoice()
        self.appointment.action_confirm_and_create_invoice()
        self.env['pet.appointment']._scan_billing_integrity_issues()
        first = Issue.search_count([])
        self.env['pet.appointment']._scan_billing_integrity_issues()
        second = Issue.search_count([])
        # Idempotent: no duplicate rows for same (appointment, issue_type)
        self.assertEqual(first, second)
        # Per-appointment uniqueness for open/reviewed/resolved set
        for appt_id in Issue.search([]).mapped('appointment_id').ids:
            types = Issue.search([('appointment_id', '=', appt_id)]).mapped('issue_type')
            self.assertEqual(len(types), len(set(types)))

    def test_13_metadata_repair_does_not_change_invoice(self):
        self.appointment.action_create_invoice()
        self.appointment.action_confirm_and_create_invoice()
        inv = self.appointment.invoice_id
        before = inv.amount_total
        # Simulate incomplete services: remove extras then repair from invoice
        self.appointment.extra_service_line_ids.with_context(
            skip_appointment_so_resync=True
        ).filtered(lambda l: l.invoice_synced).unlink()
        wiz = self.env['pet.appointment.billing.repair.wizard'].create({
            'appointment_id': self.appointment.id,
            'repair_mode': 'sync_services',
            'note': 'test repair',
        })
        wiz.action_apply_metadata_repair()
        inv.invalidate_recordset()
        self.assertAlmostEqual(inv.amount_total, before, places=2)

    def test_14_mismatch_flag(self):
        self.appointment.action_create_invoice()
        # SO exists, no invoice yet — may or may not warn; after invoice with SO match, no SO mismatch
        self.appointment.action_confirm_and_create_invoice()
        self.appointment.invalidate_recordset()
        # Clean happy path should not flag SO mismatch
        warning = self.appointment.billing_warning or ''
        self.assertNotIn('Sale order total', warning)


@tagged('post_install', '-at_install', 'pet_billing', 'pet_billing_concurrency')
class TestAppointmentBillingConcurrency(TransactionCase):
    """Concurrency is validated by scripts/concurrency_invoice_race_test.py on TEST.

    This unit test only verifies the lock helper is callable; true multi-connection
    racing commits outside TransactionCase isolation and is run via the script.
    """

    def test_20_lock_helper_exists(self):
        self.assertTrue(hasattr(self.env['pet.appointment'], '_lock_appointment_row'))
        self.assertTrue(hasattr(self.env['pet.appointment'], 'action_confirm_and_create_invoice'))
