#!/usr/bin/env python3
"""True multi-connection concurrency check against the TEST database only.

Usage (test DB only):
  /home/sabry/odoo_base/base_odoo_19/venv19/bin/python3 \\
    pet_management/scripts/concurrency_invoice_race_test.py

Does not touch production.
"""
from __future__ import annotations

import os
import sys
import threading
import time

# Ensure odoo is importable when run as a script
ODOO_ROOT = '/home/sabry/odoo_base/base_odoo_19/odoo19/odoo19'
if ODOO_ROOT not in sys.path:
    sys.path.insert(0, ODOO_ROOT)

import odoo
from odoo.modules.registry import Registry
from odoo.tools import config

TEST_DB = os.environ.get('PETSPOT_TEST_DB', 'pet_spot_elsahel_test')
CONF = os.environ.get(
    'PETSPOT_TEST_CONF',
    '/home/sabry/odoo_base/base_odoo_19/config/projects/pet_spot_elsahel_test.conf',
)


def main():
    if TEST_DB == 'pet_spot_elsahel' or 'prod' in TEST_DB:
        raise SystemExit('Refusing to run concurrency race against production DB name.')
    config.parse_config(['-c', CONF, '-d', TEST_DB])
    registry = Registry(TEST_DB)
    appt_id = None
    with registry.cursor() as cr:
        env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
        partner = env['res.partner'].create({'name': 'Race Owner %s' % int(time.time())})
        species = env['pet.species'].search([], limit=1) or env['pet.species'].create({'name': 'Dog'})
        pet = env['pet.pet'].create({
            'name': 'Race Pet',
            'owner_id': partner.id,
            'species_id': species.id,
        })
        product = env['product.product'].create({
            'name': 'Race Service',
            'type': 'service',
            'list_price': 900.0,
            'invoice_policy': 'order',
            'taxes_id': [(6, 0, [])],
        })
        visit = env['pet.medical.visit'].create({
            'pet_id': pet.id,
            'reason': 'Race',
            'status': 'completed',
            'date': '2026-07-10 13:00:00',
        })
        env['pet.medical.visit.line'].create({
            'visit_id': visit.id,
            'product_id': product.id,
            'name': product.name,
            'line_type': 'service',
            'quantity': 1.0,
            'price_unit': 900.0,
        })
        appt = env['pet.appointment'].create({
            'pet_id': pet.id,
            'title': 'Race Appointment',
            'primary_type': 'checkup',
            'start_datetime': '2026-07-10 13:00:00',
            'end_datetime': '2026-07-10 13:30:00',
            'state': 'done',
            'is_medical': True,
            'medical_visit_id': visit.id,
        })
        appt.action_create_invoice()
        appt_id = appt.id
        cr.commit()

    barrier = threading.Barrier(2)
    errors = []
    results = []

    def worker(label):
        try:
            with registry.cursor() as cr:
                env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
                appt = env['pet.appointment'].browse(appt_id)
                barrier.wait(timeout=30)
                appt.action_confirm_and_create_invoice()
                cr.commit()
                invs = appt._get_linked_invoices().filtered(
                    lambda m: m.move_type == 'out_invoice' and m.state != 'cancel'
                )
                results.append((label, sorted(invs.ids)))
                print(label, 'invoices', invs.mapped('name'))
        except Exception as exc:  # noqa: BLE001
            errors.append((label, str(exc)))
            print(label, 'ERROR', exc)

    t1 = threading.Thread(target=worker, args=('A',))
    t2 = threading.Thread(target=worker, args=('B',))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    with registry.cursor() as cr:
        env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
        appt = env['pet.appointment'].browse(appt_id)
        invs = appt._get_linked_invoices().filtered(
            lambda m: m.move_type == 'out_invoice' and m.state != 'cancel'
        )
        primaries = invs.filtered(lambda m: not m.is_additional_invoice)
        print('FINAL primary count=', len(primaries), 'names=', primaries.mapped('name'))
        print('errors=', errors)
        print('results=', results)
        if len(primaries) != 1:
            raise SystemExit('FAIL: expected exactly 1 primary invoice')
        print('PASS')


if __name__ == '__main__':
    main()
