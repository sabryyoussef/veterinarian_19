# -*- coding: utf-8 -*-
"""Phase 16 shell validator for TEST DB only (layered totals, scan idempotency, repair)."""
print('=== Phase 16 billing validator (TEST) ===')

Appt = env['pet.appointment']
Issue = env['pet.billing.integrity.issue']

# Complimentary policy
partner = env['res.partner'].create({'name': 'P16 Comp Owner'})
species = env['pet.species'].search([], limit=1) or env['pet.species'].create({'name': 'Dog'})
pet = env['pet.pet'].create({'name': 'P16 Comp Pet', 'owner_id': partner.id, 'species_id': species.id})
comp = Appt.create({
    'pet_id': pet.id,
    'title': 'Complimentary visit',
    'primary_type': 'checkup',
    'start_datetime': '2026-07-10 14:00:00',
    'end_datetime': '2026-07-10 14:15:00',
    'state': 'done',
    'is_complimentary': True,
    'complimentary_reason': 'Warranty redo',
})
assert comp.amount_total == 0.0
assert comp.payment_status == 'paid'
print('   OK complimentary policy')

# Layered totals on a normal billed appointment
product = env['product.product'].create({
    'name': 'P16 Layered', 'type': 'service', 'list_price': 1200.0,
    'invoice_policy': 'order', 'taxes_id': [(6, 0, [])],
})
visit = env['pet.medical.visit'].create({
    'pet_id': pet.id, 'reason': 'layered', 'status': 'completed', 'date': '2026-07-10 15:00:00',
})
env['pet.medical.visit.line'].create({
    'visit_id': visit.id, 'product_id': product.id, 'name': product.name,
    'line_type': 'service', 'quantity': 1.0, 'price_unit': 1200.0,
})
appt = Appt.create({
    'pet_id': pet.id, 'title': 'Layered', 'primary_type': 'checkup',
    'start_datetime': '2026-07-10 15:00:00', 'end_datetime': '2026-07-10 15:30:00',
    'state': 'done', 'is_medical': True, 'medical_visit_id': visit.id,
})
appt.action_create_invoice()
appt.action_confirm_and_create_invoice()
appt.invalidate_recordset()
assert abs(appt.service_total - 1200.0) < 0.05
assert abs(appt.sale_order_total - 1200.0) < 0.05
assert abs(appt.total_invoiced - 1200.0) < 0.05
assert abs(appt.billing_variance) < 0.05
print('   OK layered totals', appt.service_total, appt.sale_order_total, appt.total_invoiced)

# Idempotent scan
before = Issue.search_count([])
Appt._scan_billing_integrity_issues()
mid = Issue.search_count([])
Appt._scan_billing_integrity_issues()
after = Issue.search_count([])
assert mid == after, 'scan created duplicates'
print('   OK idempotent scan count', before, '->', after)

# Metadata repair
inv_total = appt.invoice_id.amount_total
wiz = env['pet.appointment.billing.repair.wizard'].create({
    'appointment_id': appt.id,
    'repair_mode': 'both',
    'note': 'phase16 validator',
})
wiz.action_apply_metadata_repair()
assert abs(appt.invoice_id.amount_total - inv_total) < 0.01
print('   OK metadata repair left invoice at', inv_total)

print('=== Phase 16 validator PASS ===')
