# -*- coding: utf-8 -*-
from datetime import date
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.exceptions import AccessError, UserError, ValidationError


@tagged('post_install', '-at_install', 'pet_clinic_finance')
class TestClinicExpenses(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.env['pet.clinic.finance.setup'].setup_all_companies()
        cls.cash = cls.env['pet.funding.source'].search([
            ('company_id', '=', cls.company.id),
            ('technical_code', '=', 'clinic_cash'),
        ], limit=1)
        cls.instapay = cls.env['pet.funding.source'].search([
            ('company_id', '=', cls.company.id),
            ('technical_code', '=', 'clinic_instapay'),
        ], limit=1)
        cls.sabry_src = cls.env['pet.funding.source'].search([
            ('company_id', '=', cls.company.id),
            ('technical_code', '=', 'sabry'),
            ('active', '=', True),
        ], limit=1)
        cls.ahmed_src = cls.env['pet.funding.source'].search([
            ('company_id', '=', cls.company.id),
            ('technical_code', '=', 'ahmed'),
            ('active', '=', True),
        ], limit=1)
        assert cls.cash and cls.instapay, 'Cash/InstaPay sources must exist after setup'
        assert cls.sabry_src and cls.ahmed_src, 'Partner sources must be active (Sabry/Ahmed)'

        cls.cat_other = cls.env['pet.expense.category'].search([
            ('company_id', '=', cls.company.id),
            ('technical_code', '=', 'other'),
            ('active', '=', True),
        ], limit=1)
        cls.cat_pharmacy = cls.env['pet.expense.category'].search([
            ('company_id', '=', cls.company.id),
            ('technical_code', '=', 'pharmacy'),
            ('active', '=', True),
        ], limit=1)
        cls.cat_general = cls.env['pet.expense.category'].search([
            ('company_id', '=', cls.company.id),
            ('technical_code', '=', 'general'),
            ('active', '=', True),
        ], limit=1)
        cls.cat_lab = cls.env['pet.expense.category'].search([
            ('company_id', '=', cls.company.id),
            ('technical_code', '=', 'laboratory'),
            ('active', '=', True),
        ], limit=1)
        cls.cat_utilities = cls.env['pet.expense.category'].search([
            ('company_id', '=', cls.company.id),
            ('technical_code', '=', 'utilities'),
            ('active', '=', True),
        ], limit=1)

        cls.accountant = cls.env['res.users'].create({
            'name': 'Clinic Finance Accountant',
            'login': 'clinic_finance_accountant_%s' % cls.env.uid,
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('pet_management.group_pet_clinic_accountant').id,
                cls.env.ref('account.group_account_user').id,
            ])],
        })
        cls.reception = cls.env['res.users'].create({
            'name': 'Clinic Finance Reception',
            'login': 'clinic_finance_reception_%s' % cls.env.uid,
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('pet_management.group_pet_clinic_reception').id,
            ])],
        })

        # Opening balances via equity (not expense/income)
        cls._post_opening(cls.cash, 12000.0, 'TEST-OPEN-CASH-12K')
        cls._post_opening(cls.instapay, 5000.0, 'TEST-OPEN-INSTA-5K')

    @classmethod
    def _equity_account(cls):
        return cls.env['account.account'].search([
            ('account_type', '=', 'equity_unaffected'),
            ('company_ids', 'in', cls.company.id),
        ], limit=1) or cls.env['account.account'].search([
            ('code', '=', '301000'),
            ('company_ids', 'in', cls.company.id),
        ], limit=1)

    @classmethod
    def _post_opening(cls, source, amount, ref):
        equity = cls._equity_account()
        assert equity, 'Need equity/opening account'
        existing = cls.env['account.move'].search([('ref', '=', ref), ('company_id', '=', cls.company.id)], limit=1)
        if existing:
            return existing
        move = cls.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': source.journal_id.id,
            'date': date(2026, 7, 1),
            'ref': ref,
            'company_id': cls.company.id,
            'line_ids': [
                (0, 0, {
                    'name': 'Opening',
                    'account_id': source.liquidity_account_id.id,
                    'debit': amount,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': 'Opening',
                    'account_id': equity.id,
                    'debit': 0.0,
                    'credit': amount,
                }),
            ],
        })
        move.action_post()
        return move

    def _expense_total_period(self, d_from, d_to):
        groups = self.env['account.move.line'].read_group(
            [
                ('company_id', '=', self.company.id),
                ('parent_state', '=', 'posted'),
                ('account_id.account_type', 'in', [
                    'expense', 'expense_direct_cost', 'expense_depreciation',
                ]),
                ('date', '>=', d_from),
                ('date', '<=', d_to),
            ],
            ['balance:sum'], [],
        )
        return groups[0].get('balance', 0.0) if groups else 0.0

    def _assert_balanced(self, move):
        self.assertEqual(move.state, 'posted')
        self.assertAlmostEqual(sum(move.line_ids.mapped('debit')), sum(move.line_ids.mapped('credit')))

    def _make_expense(self, amount, description, category, source, post=True):
        exp = self.env['pet.clinic.expense'].with_user(self.accountant).create({
            'date': date(2026, 7, 11),
            'amount': amount,
            'description': description,
            'category_id': category.id,
            'funding_source_id': source.id,
            'company_id': self.company.id,
        })
        if post:
            exp.action_post()
        return exp

    def test_01_cash_expense_posts(self):
        before = self.cash.get_liquidity_balance()
        exp = self._make_expense(190, 'Fan', self.cat_other, self.cash)
        self._assert_balanced(exp.move_id)
        self.assertAlmostEqual(self.cash.get_liquidity_balance(), before - 190)
        credit = exp.move_id.line_ids.filtered(lambda l: l.credit)
        self.assertEqual(credit.account_id, self.cash.liquidity_account_id)

    def test_02_instapay_expense_posts(self):
        before = self.instapay.get_liquidity_balance()
        exp = self._make_expense(750, 'Pharmacy InstaPay', self.cat_pharmacy, self.instapay)
        self._assert_balanced(exp.move_id)
        self.assertAlmostEqual(self.instapay.get_liquidity_balance(), before - 750)

    def test_03_sabry_credits_payable_with_partner(self):
        before_due = self.sabry_src.get_partner_due_balance()
        before_cash = self.cash.get_liquidity_balance()
        exp = self._make_expense(200, 'Orange line', self.cat_utilities, self.sabry_src)
        credit = exp.move_id.line_ids.filtered(lambda l: l.credit)
        self.assertEqual(credit.partner_id, self.sabry_src.partner_id)
        self.assertEqual(credit.account_id, self.sabry_src.payable_account_id)
        self.assertAlmostEqual(self.sabry_src.get_partner_due_balance(), before_due + 200)
        self.assertAlmostEqual(self.cash.get_liquidity_balance(), before_cash)

    def test_04_ahmed_credits_payable_with_partner(self):
        before_due = self.ahmed_src.get_partner_due_balance()
        before_insta = self.instapay.get_liquidity_balance()
        exp = self._make_expense(700, 'Laboratory', self.cat_lab, self.ahmed_src)
        credit = exp.move_id.line_ids.filtered(lambda l: l.credit)
        self.assertEqual(credit.partner_id, self.ahmed_src.partner_id)
        self.assertAlmostEqual(self.ahmed_src.get_partner_due_balance(), before_due + 700)
        self.assertAlmostEqual(self.instapay.get_liquidity_balance(), before_insta)

    def test_05_double_post_idempotent(self):
        exp = self._make_expense(50, 'Idempotent', self.cat_general, self.cash)
        move = exp.move_id
        exp.action_post()
        self.assertEqual(exp.move_id, move)
        self.assertEqual(
            self.env['account.move'].search_count([('ref', '=', exp.name)]),
            1,
        )

    def test_06_reversal_keeps_original(self):
        exp = self._make_expense(80, 'To reverse', self.cat_general, self.cash)
        move = exp.move_id
        before = self.cash.get_liquidity_balance()
        exp.action_cancel()
        self.assertEqual(exp.state, 'cancelled')
        self.assertTrue(exp.reversal_move_id)
        self.assertEqual(move.state, 'posted')
        self.assertTrue(move.exists())
        self.assertAlmostEqual(self.cash.get_liquidity_balance(), before + 80)

    def test_07_reimbursement_reduces_due_no_expense(self):
        self._make_expense(200, 'Sabry due seed', self.cat_utilities, self.sabry_src)
        due_before = self.sabry_src.get_partner_due_balance()
        exp_before = self._expense_total_period(date(2026, 7, 1), date(2026, 7, 31))
        cash_before = self.cash.get_liquidity_balance()
        reimb = self.env['pet.clinic.partner.reimbursement'].with_user(self.accountant).create({
            'date': date(2026, 7, 11),
            'amount': 100,
            'partner_source_id': self.sabry_src.id,
            'pay_from_source_id': self.cash.id,
            'company_id': self.company.id,
        })
        reimb.action_post()
        self._assert_balanced(reimb.move_id)
        self.assertAlmostEqual(self.sabry_src.get_partner_due_balance(), due_before - 100)
        self.assertAlmostEqual(self.cash.get_liquidity_balance(), cash_before - 100)
        exp_after = self._expense_total_period(date(2026, 7, 1), date(2026, 7, 31))
        self.assertAlmostEqual(exp_after, exp_before)

    def test_08_reimbursement_above_due_blocked(self):
        due = self.sabry_src.get_partner_due_balance()
        reimb = self.env['pet.clinic.partner.reimbursement'].with_user(self.accountant).create({
            'date': date(2026, 7, 11),
            'amount': due + 1000,
            'partner_source_id': self.sabry_src.id,
            'pay_from_source_id': self.cash.id,
            'company_id': self.company.id,
        })
        with self.assertRaises(ValidationError):
            reimb.action_post()

    def test_09_wallet_transfer_no_pnl(self):
        exp_before = self._expense_total_period(date(2026, 7, 1), date(2026, 7, 31))
        cash_before = self.cash.get_liquidity_balance()
        insta_before = self.instapay.get_liquidity_balance()
        transfer = self.env['pet.clinic.wallet.transfer'].with_user(self.accountant).create({
            'date': date(2026, 7, 11),
            'amount': 500,
            'from_source_id': self.cash.id,
            'to_source_id': self.instapay.id,
            'company_id': self.company.id,
        })
        transfer.action_post()
        self._assert_balanced(transfer.move_id)
        self.assertAlmostEqual(self.cash.get_liquidity_balance(), cash_before - 500)
        self.assertAlmostEqual(self.instapay.get_liquidity_balance(), insta_before + 500)
        exp_after = self._expense_total_period(date(2026, 7, 1), date(2026, 7, 31))
        self.assertAlmostEqual(exp_after, exp_before)

    def test_10_missing_category_account_error(self):
        cat = self.env['pet.expense.category'].create({
            'name': 'Broken',
            'technical_code': 'broken_test',
            'company_id': self.company.id,
            'active': False,
            'account_id': False,
        })
        exp = self.env['pet.clinic.expense'].with_user(self.accountant).create({
            'date': date(2026, 7, 11),
            'amount': 10,
            'description': 'Bad cat',
            'category_id': cat.id,
            'funding_source_id': self.cash.id,
            'company_id': self.company.id,
        })
        with self.assertRaises(ValidationError):
            exp.action_post()

    def test_11_reception_cannot_post(self):
        exp = self.env['pet.clinic.expense'].with_user(self.reception).create({
            'date': date(2026, 7, 11),
            'amount': 25,
            'description': 'Reception draft',
            'category_id': self.cat_general.id,
            'funding_source_id': self.cash.id,
            'company_id': self.company.id,
        })
        with self.assertRaises(AccessError):
            exp.with_user(self.reception).action_post()

    def test_12_quick_expense_attachments_reassigned(self):
        wiz = self.env['pet.clinic.quick.expense.wizard'].with_user(self.accountant).create({
            'date': date(2026, 7, 11),
            'amount': 15,
            'description': 'With receipt',
            'category_id': self.cat_general.id,
            'funding_source_id': self.cash.id,
            'company_id': self.company.id,
        })
        att = self.env['ir.attachment'].with_user(self.accountant).create({
            'name': 'receipt.png',
            'datas': 'aGVsbG8=',
            'res_model': 'pet.clinic.quick.expense.wizard',
            'res_id': wiz.id,
        })
        wiz.with_user(self.accountant).write({'attachment_ids': [(6, 0, [att.id])]})
        action = wiz.with_user(self.accountant).action_save_and_post()
        expense = self.env['pet.clinic.expense'].browse(action['res_id'])
        self.assertEqual(att.res_model, 'pet.clinic.expense')
        self.assertEqual(att.res_id, expense.id)
        self.assertEqual(expense.state, 'posted')

    def test_13_sample_scenario_totals(self):
        """Exact sample scenario from the approved plan corrections."""
        # Isolate by measuring deltas around this scenario's own postings.
        cash0 = self.cash.get_liquidity_balance()
        insta0 = self.instapay.get_liquidity_balance()
        sabry0 = self.sabry_src.get_partner_due_balance()
        ahmed0 = self.ahmed_src.get_partner_due_balance()
        exp0 = self._expense_total_period(date(2026, 7, 11), date(2026, 7, 11))

        self._make_expense(190, 'Fan', self.cat_other, self.cash)
        self._make_expense(700, 'Supplies', self.cat_general, self.cash)
        self._make_expense(3300, 'Pharmacy Cash', self.cat_pharmacy, self.cash)
        self._make_expense(750, 'Pharmacy Insta', self.cat_pharmacy, self.instapay)
        self._make_expense(200, 'Orange line', self.cat_utilities, self.sabry_src)
        self._make_expense(700, 'Laboratory', self.cat_lab, self.ahmed_src)

        self.assertAlmostEqual(cash0 - self.cash.get_liquidity_balance(), 4190)
        self.assertAlmostEqual(insta0 - self.instapay.get_liquidity_balance(), 750)
        self.assertAlmostEqual(self.sabry_src.get_partner_due_balance() - sabry0, 200)
        self.assertAlmostEqual(self.ahmed_src.get_partner_due_balance() - ahmed0, 700)
        self.assertAlmostEqual(self._expense_total_period(date(2026, 7, 11), date(2026, 7, 11)) - exp0, 5840)
        # Opening cash must not be in expense total for opening day alone differently —
        # opening was on 2026-07-01 against equity.
        opening_expense = self._expense_total_period(date(2026, 7, 1), date(2026, 7, 1))
        # Ensure no expense account lines on opening refs
        open_moves = self.env['account.move'].search([
            ('ref', 'in', ['TEST-OPEN-CASH-12K', 'TEST-OPEN-INSTA-5K']),
            ('company_id', '=', self.company.id),
        ])
        for move in open_moves:
            self.assertFalse(move.line_ids.filtered(
                lambda l: l.account_id.account_type in (
                    'expense', 'expense_direct_cost', 'income', 'income_other',
                )
            ))

        # Reimbursement 100 to Sabry → due increase net 100 from sabry0
        reimb = self.env['pet.clinic.partner.reimbursement'].with_user(self.accountant).create({
            'date': date(2026, 7, 11),
            'amount': 100,
            'partner_source_id': self.sabry_src.id,
            'pay_from_source_id': self.cash.id,
            'company_id': self.company.id,
        })
        reimb.action_post()
        self.assertAlmostEqual(self.sabry_src.get_partner_due_balance() - sabry0, 100)
        # Expense total unchanged by reimbursement
        self.assertAlmostEqual(self._expense_total_period(date(2026, 7, 11), date(2026, 7, 11)) - exp0, 5840)

    def test_14_dashboard_matches_accounting(self):
        data = self.env['pet.clinic.finance'].get_dashboard_data(period='month')
        self.assertIn('liquidity', data['sections'])
        self.assertIn('partner_liability', data['sections'])
        self.assertIn('performance', data['sections'])
        labels = [c['label'] for c in data['sections']['performance']['cards']]
        self.assertTrue(any('Net Profit/Loss' in (l or '') for l in labels))
        self.assertFalse(any('cash profit' in (l or '').lower() for l in labels))
