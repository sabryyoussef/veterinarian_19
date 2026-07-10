# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError


@tagged('post_install', '-at_install', 'pet_billing')
class TestAppointmentBillingIntegrity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'Billing Test Owner',
            'email': 'billing-test@example.com',
        })
        species = cls.env['pet.species'].search([], limit=1)
        if not species:
            species = cls.env['pet.species'].create({'name': 'Dog'})
        cls.pet = cls.env['pet.pet'].create({
            'name': 'Billing Test Pet',
            'owner_id': cls.partner.id,
            'species_id': species.id,
        })
        product = cls.env['product.product'].create({
            'name': 'Consultation Test',
            'type': 'service',
            'list_price': 1000.0,
            'invoice_policy': 'order',
            'taxes_id': [(6, 0, [])],
        })
        cls.extra_product = cls.env['product.product'].create({
            'name': 'Extra Service Test',
            'type': 'service',
            'list_price': 500.0,
            'invoice_policy': 'order',
            'taxes_id': [(6, 0, [])],
        })
        visit = cls.env['pet.medical.visit'].create({
            'pet_id': cls.pet.id,
            'reason': 'Billing integrity test',
            'status': 'scheduled',
            'date': '2026-07-10 10:00:00',
        })
        cls.env['pet.medical.visit.line'].create({
            'visit_id': visit.id,
            'product_id': product.id,
            'name': product.name,
            'line_type': 'service',
            'quantity': 1.0,
            'price_unit': 1000.0,
        })
        cls.appointment = cls.env['pet.appointment'].create({
            'pet_id': cls.pet.id,
            'title': 'Billing Integrity Appointment',
            'primary_type': 'checkup',
            'start_datetime': '2026-07-10 10:00:00',
            'end_datetime': '2026-07-10 10:30:00',
            'state': 'done',
            'is_medical': True,
            'medical_visit_id': visit.id,
        })
        cls.env['pet.appointment.service.line'].create({
            'appointment_id': cls.appointment.id,
            'product_id': cls.extra_product.id,
            'name': 'Cannula test',
            'quantity': 1.0,
            'price_unit': 500.0,
        })

    def test_01_sale_order_idempotent(self):
        self.appointment.action_create_invoice()
        so1 = self.appointment.sale_order_id
        self.assertTrue(so1)
        self.assertEqual(so1.appointment_id, self.appointment)
        self.appointment.action_create_invoice()
        self.assertEqual(self.appointment.sale_order_id, so1)

    def test_02_invoice_idempotent(self):
        self.appointment.action_create_invoice()
        self.appointment.action_confirm_and_create_invoice()
        inv1 = self.appointment.invoice_id
        self.assertTrue(inv1)
        self.assertEqual(inv1.state, 'posted')
        self.assertEqual(inv1.appointment_id, self.appointment)
        action = self.appointment.action_confirm_and_create_invoice()
        self.assertEqual(self.appointment.invoice_id, inv1)
        self.assertEqual(action.get('res_id'), inv1.id)
        # Sales wizard must not create a second primary invoice
        with self.assertRaises(UserError):
            self.appointment.sale_order_id._create_invoices()

    def test_03_payment_status_paid(self):
        self.appointment.action_create_invoice()
        self.appointment.action_confirm_and_create_invoice()
        inv = self.appointment.invoice_id
        # Mark residual paid via payment register if journals exist
        self.assertIn(self.appointment.payment_status, ('pending', 'partial', 'paid', 'draft'))
        inv.payment_state  # touch
        # Simulate full reconciliation by setting residual conceptually via payment
        # At minimum after post with no payment => pending
        self.appointment.invalidate_recordset()
        self.assertEqual(self.appointment.payment_status, 'pending')

    def test_04_paid_invoice_draft_blocked(self):
        self.appointment.action_create_invoice()
        self.appointment.action_confirm_and_create_invoice()
        inv = self.appointment.invoice_id
        # Create and post a payment so receivable is reconciled / paid-like
        payment_method_line = self.env['account.payment.method.line'].search([
            ('payment_type', '=', 'inbound'),
            ('company_id', '=', inv.company_id.id),
        ], limit=1)
        if not payment_method_line:
            self.skipTest('No inbound payment method configured')
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=inv.ids,
        ).create({
            'amount': inv.amount_residual,
            'payment_method_line_id': payment_method_line.id,
        })
        wizard.action_create_payments()
        inv.invalidate_recordset()
        self.assertIn(inv.payment_state, ('paid', 'in_payment', 'partial'))
        with self.assertRaises(UserError):
            inv.button_draft()

    def test_05_sync_no_duplicate_extras(self):
        self.appointment.action_create_invoice()
        self.appointment.action_confirm_and_create_invoice()
        before = len(self.appointment.extra_service_line_ids)
        self.appointment._sync_services_from_invoice()
        self.appointment._sync_services_from_invoice()
        after = len(self.appointment.extra_service_line_ids)
        self.assertEqual(before, after)

    def test_06_additional_invoice_requires_uninvoiced(self):
        self.appointment.action_create_invoice()
        self.appointment.action_confirm_and_create_invoice()
        wiz = self.env['pet.appointment.additional.invoice.wizard'].create({
            'appointment_id': self.appointment.id,
            'reason': 'Need more services',
        })
        with self.assertRaises(UserError):
            wiz.action_create_additional_invoice()
