# -*- coding: utf-8 -*-
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestExamTokenIdempotency(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Token = cls.env['petspot.portal.token'].sudo()
        cls.partner = cls.env['res.partner'].create({'name': 'Idempotency Owner', 'phone': '01099998877'})
        species = cls.env['pet.species'].search([], limit=1)
        if not species:
            species = cls.env['pet.species'].create({'name': 'Dog'})
        cls.pet = cls.env['pet.pet'].create({
            'name': 'Idempotency Pet',
            'owner_id': cls.partner.id,
            'species_id': species.id,
        })
        start = fields.Datetime.now()
        cls.appointment = cls.env['pet.appointment'].create({
            'pet_id': cls.pet.id,
            'title': 'Idempotency Appt',
            'primary_type': 'checkup',
            'start_datetime': start,
            'end_datetime': start + timedelta(minutes=30),
            'state': 'confirmed',
        })

    def _mint_vet(self):
        return self.Token.mint_from_api({
            'role': 'vet',
            'appointment_id': self.appointment.id,
            'phone': '01099998877',
        })

    def test_mint_vet_same_appointment_returns_same_token(self):
        first = self._mint_vet()
        second = self._mint_vet()
        self.assertTrue(first.get('token_id'))
        self.assertEqual(first['token_id'], second['token_id'])
        self.assertEqual(first['url'], second['url'])
        open_count = self.Token.search_count([
            ('appointment_id', '=', self.appointment.id),
            ('role', '=', 'vet'),
            ('state', '=', 'open'),
        ])
        self.assertEqual(open_count, 1)

    def test_create_exam_token_and_notify_reuses_open_token(self):
        book = self.Token.create_patient_token({
            'appointment_id': self.appointment.id,
            'pet_id': self.pet.id,
            'partner_id': self.partner.id,
            'prefill_phone': '01099998877',
        })
        with patch.object(type(book), 'petspot_notify_whatsapp_group', lambda s, m: True), \
             patch.object(type(book), 'petspot_notify_chatwoot', lambda s, c, m: True), \
             patch.object(type(book), 'petspot_notify_whatsapp_button', lambda s, *a, **k: True):
            t1 = book.create_exam_token_and_notify()
            t2 = book.create_exam_token_and_notify()
        self.assertTrue(t1)
        self.assertEqual(t1.id, t2.id)
        open_count = self.Token.search_count([
            ('appointment_id', '=', self.appointment.id),
            ('role', '=', 'vet'),
            ('state', '=', 'open'),
        ])
        self.assertEqual(open_count, 1)

    def test_patient_book_mint_still_creates_tokens(self):
        p1 = self.Token.mint_from_api({'role': 'patient', 'phone': '01011112233'})
        p2 = self.Token.mint_from_api({'role': 'patient', 'phone': '01011112233'})
        self.assertNotEqual(p1['token_id'], p2['token_id'])
