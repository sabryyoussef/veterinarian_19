#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shell validation for appointment billing integrity on pet_spot_elsahel_test.

Run via:
  odoo-bin shell -c .../pet_spot_elsahel_test.conf -d pet_spot_elsahel_test --no-http < this_file
"""
from odoo.exceptions import UserError

print('=== BILLING INTEGRITY VALIDATION (TEST DB) ===')
Partner = env['res.partner']
Pet = env['pet.pet']
Appointment = env['pet.appointment']

partner = Partner.create({'name': 'Integrity Shell Owner', 'email': 'shell-billing@example.com'})
species = env['pet.species'].search([], limit=1) or env['pet.species'].create({'name': 'Dog'})
pet = Pet.create({'name': 'Integrity Shell Pet', 'owner_id': partner.id, 'species_id': species.id})
product = env['product.product'].create({
    'name': 'Shell Consultation', 'type': 'service', 'list_price': 1000.0,
    'invoice_policy': 'order', 'taxes_id': [(6, 0, [])],
})
extra = env['product.product'].create({
    'name': 'Shell Extra', 'type': 'service', 'list_price': 500.0,
    'invoice_policy': 'order', 'taxes_id': [(6, 0, [])],
})
visit = env['pet.medical.visit'].create({'pet_id': pet.id, 'reason': 'shell', 'status': 'scheduled', 'date': '2026-07-10 12:00:00'})
env['pet.medical.visit.line'].create({
    'visit_id': visit.id, 'product_id': product.id, 'name': product.name,
    'line_type': 'service', 'quantity': 1.0, 'price_unit': 1000.0,
})
appt = Appointment.create({
    'pet_id': pet.id, 'title': 'Shell Billing Appt', 'primary_type': 'checkup',
    'start_datetime': '2026-07-10 12:00:00', 'end_datetime': '2026-07-10 12:30:00',
    'state': 'done', 'is_medical': True, 'medical_visit_id': visit.id,
})
env['pet.appointment.service.line'].create({
    'appointment_id': appt.id, 'product_id': extra.id, 'name': 'Extra',
    'quantity': 1.0, 'price_unit': 500.0,
})

print('1) Create SO twice')
appt.action_create_invoice()
so = appt.sale_order_id
assert so and so.appointment_id == appt
appt.action_create_invoice()
assert appt.sale_order_id == so
print('   OK', so.name)

print('2) Confirm & invoice twice')
appt.action_confirm_and_create_invoice()
inv = appt.invoice_id
assert inv and inv.appointment_id == appt and inv.state == 'posted'
appt.action_confirm_and_create_invoice()
assert appt.invoice_id == inv
print('   OK', inv.name, 'payment_status=', appt.payment_status)

print('3) Block second primary via Sales')
try:
    so._create_invoices()
    raise AssertionError('expected UserError')
except UserError as e:
    print('   OK blocked:', str(e)[:120])

print('4) Payment status pending after post')
assert appt.payment_status == 'pending'
print('   OK totals invoiced=', appt.total_invoiced, 'residual=', appt.total_residual)

print('5) Paid draft reset blocked')
# unpaid draft reset by system user is allowed only for accountants path;
# simulate paid-like via payment_state check using reconciled payment if possible
pml = env['account.payment.method.line'].search([
    ('payment_type', '=', 'inbound'), ('company_id', '=', inv.company_id.id),
], limit=1)
if pml:
    wiz = env['account.payment.register'].with_context(active_model='account.move', active_ids=inv.ids).create({
        'amount': inv.amount_residual, 'payment_method_line_id': pml.id,
    })
    wiz.action_create_payments()
    inv.invalidate_recordset()
    try:
        inv.button_draft()
        raise AssertionError('expected UserError')
    except UserError as e:
        print('   OK blocked:', str(e)[:120])
else:
    print('   SKIP no payment method')

print('6) Integrity scan runs')
appt._scan_billing_integrity_issues()
print('   OK')

env.cr.rollback()
print('ALL SHELL CHECKS PASSED (rolled back)')
