# -*- coding: utf-8 -*-
"""Idempotent per-company clinic finance accounting setup.

Company-specific journals/accounts are never created via static XML.
"""
import logging

from odoo import api, models, _

_logger = logging.getLogger(__name__)

INSTAPAY_ACCOUNT_CODE = '101502'
INSTAPAY_ACCOUNT_NAME = 'Clinic InstaPay'
INSTAPAY_JOURNAL_CODE = 'INST'
INSTAPAY_JOURNAL_NAME = 'Clinic InstaPay'

# Clearly named operating expense accounts created only when missing.
EXPENSE_ACCOUNTS_TO_ENSURE = [
    ('621001', 'Clinic Medical Supplies'),
    ('621002', 'Clinic Pharmacy Purchases'),
    ('621003', 'Clinic Laboratory Expenses'),
    ('621004', 'Clinic Utilities'),
    ('621005', 'Clinic Internet and Telephone'),
    ('621006', 'Clinic Maintenance'),
    ('621007', 'Clinic Transportation'),
    ('621008', 'Clinic General Expenses'),
    ('621009', 'Clinic Other Expenses'),
]

PARTNER_BINDINGS = [
    # (funding source xml id suffix / name, exact partner name)
    ('sabry', 'Sabry Youssef'),
    ('ahmed', 'Ahmed Barakat'),
]


class PetClinicFinanceSetup(models.AbstractModel):
    _name = 'pet.clinic.finance.setup'
    _description = 'Clinic Finance Company Setup'

    @api.model
    def _account_by_code(self, company, code):
        Account = self.env['account.account'].with_company(company)
        return Account.search([
            ('code', '=', code),
            ('company_ids', 'in', company.id),
        ], limit=1)

    @api.model
    def _ensure_account(self, company, code, name, account_type, reconcile=False):
        existing = self._account_by_code(company, code)
        if existing:
            return existing
        Account = self.env['account.account'].with_company(company).sudo()
        account = Account.create({
            'code': code,
            'name': name,
            'account_type': account_type,
            'reconcile': reconcile,
            'company_ids': [(6, 0, [company.id])],
        })
        _logger.info(
            'Created account %s (%s) for company %s',
            code, name, company.display_name,
        )
        return account

    @api.model
    def _ensure_instapay_journal(self, company):
        Journal = self.env['account.journal'].with_company(company).sudo()
        journal = Journal.search([
            ('code', '=', INSTAPAY_JOURNAL_CODE),
            ('company_id', '=', company.id),
        ], limit=1)
        account = self._ensure_account(
            company,
            INSTAPAY_ACCOUNT_CODE,
            INSTAPAY_ACCOUNT_NAME,
            'asset_cash',
            reconcile=False,
        )
        if journal:
            if not journal.default_account_id:
                journal.default_account_id = account.id
            elif journal.default_account_id != account:
                _logger.warning(
                    'Journal %s already has default_account_id=%s; expected %s. Leaving as-is.',
                    journal.display_name,
                    journal.default_account_id.display_name,
                    account.display_name,
                )
            return journal
        journal = Journal.create({
            'name': INSTAPAY_JOURNAL_NAME,
            'code': INSTAPAY_JOURNAL_CODE,
            'type': 'bank',
            'company_id': company.id,
            'default_account_id': account.id,
        })
        _logger.info(
            'Created journal %s for company %s',
            INSTAPAY_JOURNAL_CODE, company.display_name,
        )
        return journal

    @api.model
    def _cash_journal(self, company):
        return self.env['account.journal'].with_company(company).search([
            ('code', '=', 'CSH1'),
            ('company_id', '=', company.id),
            ('type', '=', 'cash'),
        ], limit=1)

    @api.model
    def ensure_company_accounting(self, company=None):
        """Ensure InstaPay journal/account and named expense accounts for one company."""
        company = company or self.env.company
        self._ensure_instapay_journal(company)
        for code, name in EXPENSE_ACCOUNTS_TO_ENSURE:
            self._ensure_account(company, code, name, 'expense', reconcile=False)
        return True

    @api.model
    def _find_unique_partner(self, company, name):
        Partner = self.env['res.partner'].sudo()
        partners = Partner.search([
            ('name', '=', name),
            '|',
            ('company_id', '=', False),
            ('company_id', '=', company.id),
        ])
        if len(partners) == 1:
            return partners
        if not partners:
            _logger.warning(
                'Clinic finance: partner %r not found for company %s; leave source inactive.',
                name, company.display_name,
            )
        else:
            _logger.warning(
                'Clinic finance: multiple partners named %r (%s) for company %s; leave source inactive.',
                name, partners.ids, company.display_name,
            )
        return Partner.browse()

    @api.model
    def ensure_funding_sources(self, company=None):
        """Bind / create funding sources for the company (idempotent)."""
        company = company or self.env.company
        self.ensure_company_accounting(company)
        Source = self.env['pet.funding.source'].sudo().with_company(company)
        currency = company.currency_id

        cash_journal = self._cash_journal(company)
        if cash_journal and cash_journal.default_account_id:
            cash = Source.search([
                ('company_id', '=', company.id),
                ('technical_code', '=', 'clinic_cash'),
            ], limit=1)
            vals = {
                'name': 'Clinic Cash',
                'name_ar': 'خزنة العيادة',
                'technical_code': 'clinic_cash',
                'source_type': 'cash',
                'journal_id': cash_journal.id,
                'company_id': company.id,
                'currency_id': currency.id,
                'sequence': 10,
                'active': True,
            }
            if cash:
                cash.write({k: v for k, v in vals.items() if k != 'technical_code'})
            else:
                Source.create(vals)
        else:
            _logger.warning(
                'Clinic finance: cash journal CSH1 missing/incomplete for %s',
                company.display_name,
            )

        inst_journal = self.env['account.journal'].with_company(company).sudo().search([
            ('code', '=', INSTAPAY_JOURNAL_CODE),
            ('company_id', '=', company.id),
        ], limit=1)
        if inst_journal and inst_journal.default_account_id:
            inst = Source.search([
                ('company_id', '=', company.id),
                ('technical_code', '=', 'clinic_instapay'),
            ], limit=1)
            vals = {
                'name': 'Clinic InstaPay',
                'name_ar': 'إنستاباي العيادة',
                'technical_code': 'clinic_instapay',
                'source_type': 'bank',
                'journal_id': inst_journal.id,
                'company_id': company.id,
                'currency_id': currency.id,
                'sequence': 20,
                'active': True,
            }
            if inst:
                inst.write({k: v for k, v in vals.items() if k != 'technical_code'})
            else:
                Source.create(vals)

        for tech, partner_name in PARTNER_BINDINGS:
            partner = self._find_unique_partner(company, partner_name)
            source = Source.search([
                ('company_id', '=', company.id),
                ('technical_code', '=', tech),
            ], limit=1)
            name = 'Sabry' if tech == 'sabry' else 'Ahmed'
            name_ar = 'صبري' if tech == 'sabry' else 'أحمد'
            payable = False
            active = False
            if partner:
                payable = partner.with_company(company).property_account_payable_id
                active = bool(payable)
                if not payable:
                    _logger.warning(
                        'Clinic finance: partner %s has no payable account for %s',
                        partner.display_name, company.display_name,
                    )
            vals = {
                'name': name,
                'name_ar': name_ar,
                'technical_code': tech,
                'source_type': 'partner',
                'partner_id': partner.id if partner else False,
                'payable_account_id': payable.id if payable else False,
                'company_id': company.id,
                'currency_id': currency.id,
                'sequence': 30 if tech == 'sabry' else 40,
                'active': active,
            }
            if source:
                source.write({k: v for k, v in vals.items() if k != 'technical_code'})
            else:
                Source.create(vals)
        return True

    @api.model
    def ensure_expense_categories(self, company=None):
        """Create/update categories; map only to verified or hook-created accounts."""
        company = company or self.env.company
        self.ensure_company_accounting(company)
        Category = self.env['pet.expense.category'].sudo().with_company(company)

        # (technical_code, name, account_code or False to leave inactive)
        specs = [
            ('medical_supplies', 'Medical supplies', '621001'),
            ('pharmacy', 'Pharmacy purchases', '621002'),
            ('laboratory', 'Laboratory', '621003'),
            ('utilities', 'Utilities', '621004'),
            ('internet', 'Internet and telephone', '621005'),
            ('maintenance', 'Maintenance', '621006'),
            ('transportation', 'Transportation', '621007'),
            ('staff', 'Staff expenses', '630000'),  # existing Salary Expenses
            ('rent', 'Rent', '612000'),  # existing Rent
            ('general', 'General expenses', '621008'),
            ('other', 'Other', '621009'),
        ]
        seq = 10
        for tech, name, code in specs:
            account = self._account_by_code(company, code) if code else False
            cat = Category.search([
                ('company_id', '=', company.id),
                ('technical_code', '=', tech),
            ], limit=1)
            vals = {
                'name': name,
                'technical_code': tech,
                'account_id': account.id if account else False,
                'company_id': company.id,
                'sequence': seq,
                'active': bool(account),
            }
            if not account:
                _logger.warning(
                    'Clinic finance: category %s inactive — account %s missing for %s',
                    name, code, company.display_name,
                )
            if cat:
                cat.write({k: v for k, v in vals.items() if k != 'technical_code'})
            else:
                Category.create(vals)
            seq += 10
        return True

    @api.model
    def setup_all_companies(self):
        companies = self.env['res.company'].sudo().search([])
        for company in companies:
            try:
                self.ensure_company_accounting(company)
                self.ensure_funding_sources(company)
                self.ensure_expense_categories(company)
            except Exception:
                _logger.exception(
                    'Clinic finance setup failed for company %s', company.display_name,
                )
        return True
