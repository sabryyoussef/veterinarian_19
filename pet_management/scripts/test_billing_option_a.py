#!/usr/bin/env python3
"""Validate Option A appointment billing on pet_spot_elsahel_test (run via odoo shell)."""
from odoo.exceptions import UserError


def run(env):
    PetAppointment = env['pet.appointment'].sudo()
    appointment = PetAppointment.search([
        ('state', 'in', ['confirmed', 'in_progress', 'done']),
        ('sale_order_id', '=', False),
        ('invoice_id', '=', False),
    ], limit=1)
    if not appointment:
        pet = env['pet.pet'].sudo().search([('owner_id', '!=', False)], limit=1)
        visit = env['pet.medical.visit'].sudo().create({
            'pet_id': pet.id, 'reason': 'Option A billing test',
            'status': 'scheduled', 'cost': 1000.0,
        })
        appointment = PetAppointment.create({
            'pet_id': pet.id, 'title': 'Option A billing test', 'primary_type': 'checkup',
            'start_datetime': '2026-07-10 10:00:00', 'end_datetime': '2026-07-10 11:00:00',
            'state': 'done', 'is_medical': True, 'medical_visit_id': visit.id, 'cost': 1000.0,
        })

    print('--- 1. Create Sale Order (draft) ---')
    action = appointment.action_create_invoice()
    order = appointment.sale_order_id
    assert order.state in ('draft', 'sent') and not appointment.invoice_id
    assert action.get('res_model') == 'sale.order'
    print(f'OK: {order.name} state={order.state}')

    print('--- 2. Edit SO lines on draft ---')
    order.write({'order_line': [(2, order.order_line[:1].id, 0)]})
    generic = appointment._get_generic_service_product()
    order.write({'order_line': [(0, 0, {
        'product_id': generic.id, 'name': 'Edited draft line',
        'product_uom_qty': 1.0, 'price_unit': 1000.0,
    })]})
    print('OK: draft line delete/add saved')

    print('--- 3. Confirm & Create Invoice ---')
    appointment.action_confirm_and_create_invoice()
    assert order.state == 'sale' and appointment.invoice_id.state == 'posted'
    print(f'OK: invoice={appointment.invoice_id.name}')

    print('--- 4. Confirmed SO delete blocked ---')
    try:
        with env.cr.savepoint():
            order.write({'order_line': [(2, order.order_line[:1].id, 0)]})
        raise AssertionError('expected UserError')
    except UserError as exc:
        assert 'remove one of its lines' in str(exc)
    print('OK: standard Odoo guard')

    env.cr.rollback()
    print('ALL CHECKS PASSED')
    return 0
