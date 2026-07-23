# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestBankSmsCounterpartyMapping(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Transaction = cls.env['bank.sms.transaction']
        cls.Mapping = cls.env['bank.sms.counterparty.map']

    def _transaction(self, name, amount=100.0, direction='out'):
        return self.Transaction.create({
            'date': '2026-07-18 10:00:00',
            'direction': direction,
            'txn_type': 'transfer',
            'amount': amount,
            'counterparty': name,
            'body': 'TEST BANK SMS',
        })

    def _mapping(self, masked, real, match_type='exact', priority=10, category=False):
        return self.Mapping.create({
            'masked_name': masked,
            'real_name': real,
            'match_type': match_type,
            'priority': priority,
            'default_category_id': category.id if category else False,
        })

    def test_exact_mapping_applies_to_new_transaction(self):
        self._mapping('MASKED EXACT', 'Real Exact')
        transaction = self._transaction('MASKED EXACT')
        self.assertEqual(transaction.masked_counterparty_name, 'MASKED EXACT')
        self.assertEqual(transaction.real_counterparty_name, 'Real Exact')
        self.assertEqual(transaction.mapping_state, 'mapped')
        self.assertEqual(
            transaction.counterparty_display,
            'Real Exact — MASKED EXACT',
        )

    def test_contains_regex_and_priority(self):
        self._mapping('STORE', 'Contains Store', 'contains', priority=20)
        self._mapping(r'^STORE [A-Z]+$', 'Regex Store', 'regex', priority=30)
        transaction = self._transaction('STORE CAIRO')
        self.assertEqual(transaction.real_counterparty_name, 'Regex Store')

        self._mapping('STORE CAIRO', 'Exact Store', 'exact', priority=30)
        transaction_2 = self._transaction('STORE CAIRO')
        self.assertEqual(transaction_2.real_counterparty_name, 'Exact Store')

    def test_no_mapping_does_not_guess(self):
        transaction = self._transaction('UNKNOWN MASKED NAME')
        self.assertFalse(transaction.real_counterparty_name)
        self.assertFalse(transaction.counterparty_mapping_id)
        self.assertEqual(transaction.mapping_state, 'unmapped')

    def test_conflicting_rules_are_explicit(self):
        self._mapping('CONFLICT', 'First', 'contains', priority=50)
        self._mapping('NAME', 'Second', 'contains', priority=50)
        transaction = self._transaction('CONFLICT NAME')
        self.assertEqual(transaction.mapping_state, 'conflict')
        self.assertFalse(transaction.real_counterparty_name)
        self.assertTrue(transaction.mapping_conflict)

    def test_duplicate_exact_mapping_is_rejected(self):
        self._mapping('DUPLICATE EXACT', 'First')
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self._mapping('DUPLICATE EXACT', 'Second')

    def test_backfill_preserves_original_and_financial_totals(self):
        mapping = self._mapping('OLD MASKED', 'Old Real')
        transaction = self._transaction('OLD MASKED', amount=325.50)
        self.env.cr.execute("""
            UPDATE bank_sms_transaction
               SET masked_counterparty_name = NULL,
                   real_counterparty_name = NULL,
                   counterparty_mapping_id = NULL,
                   mapping_state = 'unmapped'
             WHERE id = %s
        """, [transaction.id])
        transaction.invalidate_recordset()

        before = sum(self.Transaction.search([]).mapped('signed_amount'))
        preview = self.Transaction._backfill_counterparty_mappings(dry_run=True)
        self.assertGreaterEqual(preview['changed'], 1)
        self.assertFalse(transaction.masked_counterparty_name)

        applied = self.Transaction._backfill_counterparty_mappings(dry_run=False)
        transaction.invalidate_recordset()
        after = sum(self.Transaction.search([]).mapped('signed_amount'))
        self.assertGreaterEqual(applied['changed'], 1)
        self.assertEqual(transaction.masked_counterparty_name, 'OLD MASKED')
        self.assertEqual(transaction.counterparty, 'OLD MASKED')
        self.assertEqual(transaction.real_counterparty_name, 'Old Real')
        self.assertEqual(transaction.counterparty_mapping_id, mapping)
        self.assertEqual(before, after)

    def test_mapping_applies_to_new_inbound_message_and_category(self):
        category = self.env['product.product'].create({
            'name': 'Mapped Test Category',
            'type': 'service',
            'can_be_expensed': True,
        })
        masked = 'NEW M****** N***'
        self._mapping(masked, 'New Real', category=category)
        body = (
            'تم إضافة تحويل لحسابكم رقم 1234 بمبلغ 125.00 '
            'من %s رقم مرجعي 987654'
        ) % masked
        log = self.env['sms.message.log'].record_inbound(
            phone='01000000000',
            body=body,
            external_id='TEST-MAPPING-NEW-INBOUND',
            received_at='2026-07-18T10:00:00Z',
        )
        transaction = self.Transaction.search([('sms_log_id', '=', log.id)])
        self.assertEqual(transaction.real_counterparty_name, 'New Real')
        self.assertEqual(transaction.masked_counterparty_name, masked)
        self.assertEqual(transaction.expense_category_id, category)

    def test_masked_name_is_immutable(self):
        transaction = self._transaction('IMMUTABLE MASKED')
        with self.assertRaises(UserError):
            transaction.write({'masked_counterparty_name': 'CHANGED'})
        self.assertEqual(transaction.masked_counterparty_name, 'IMMUTABLE MASKED')

    def test_mapping_access_rights(self):
        user = new_test_user(
            self.env,
            login='bank_sms_mapping_reader',
            groups='base.group_user',
        )
        mapping = self._mapping('ACCESS MASKED', 'Access Real')
        self.assertEqual(mapping.with_user(user).real_name, 'Access Real')
        with self.assertRaises(AccessError):
            self.Mapping.with_user(user).create({
                'masked_name': 'FORBIDDEN',
                'real_name': 'Forbidden',
                'match_type': 'exact',
            })
