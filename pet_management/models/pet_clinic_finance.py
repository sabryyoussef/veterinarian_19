# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, _


class PetClinicFinance(models.AbstractModel):
    """Live finance aggregates from account.move.line (not transient storage)."""

    _name = 'pet.clinic.finance'
    _description = 'Clinic Finance Aggregates'

    @api.model
    def _period_bounds(self, period, date_from=None, date_to=None):
        today = fields.Date.context_today(self)
        if period == 'today':
            return today, today
        if period == 'week':
            start = today - timedelta(days=today.weekday())
            return start, today
        if period == 'month':
            start = today.replace(day=1)
            return start, today
        if period == 'custom':
            return date_from or today, date_to or today
        return today.replace(day=1), today

    @api.model
    def get_dashboard_data(self, period='month', date_from=False, date_to=False, company_id=False):
        company = self.env['res.company'].browse(company_id) if company_id else self.env.company
        d_from, d_to = self._period_bounds(period, date_from, date_to)
        Source = self.env['pet.funding.source'].with_company(company)
        sources = Source.search([
            ('company_id', '=', company.id),
            ('active', '=', True),
        ], order='sequence, id')

        liquidity_cards = []
        partner_cards = []
        for src in sources:
            if src.source_type in ('cash', 'bank'):
                liquidity_cards.append({
                    'id': src.id,
                    'technical_code': src.technical_code,
                    'label': src.display_name_dashboard(),
                    'label_ar': src.name_ar or src.name,
                    'amount': src.get_liquidity_balance(company=company, date_to=d_to),
                    'currency_id': src.currency_id.id,
                    'section': 'liquidity',
                })
            elif src.source_type == 'partner':
                partner_cards.append({
                    'id': src.id,
                    'technical_code': src.technical_code,
                    'label': src.display_name_dashboard(),
                    'label_ar': src.name_ar or src.name,
                    'amount': src.get_partner_due_balance(company=company, date_to=d_to),
                    'currency_id': src.currency_id.id,
                    'section': 'partner_liability',
                })

        MoveLine = self.env['account.move.line'].with_company(company)
        expense_domain = [
            ('company_id', '=', company.id),
            ('parent_state', '=', 'posted'),
            ('account_id.account_type', 'in', [
                'expense', 'expense_direct_cost', 'expense_depreciation',
            ]),
            ('date', '>=', d_from),
            ('date', '<=', d_to),
        ]
        def _group_balance(groups):
            """read_group may return balance=False when there are no lines."""
            if not groups:
                return 0.0
            return float(groups[0].get('balance') or 0.0)

        expense_groups = MoveLine.read_group(expense_domain, ['balance:sum'], [])
        # expense accounts normally have debit balance (positive balance)
        expenses_total = _group_balance(expense_groups)

        income_domain = [
            ('company_id', '=', company.id),
            ('parent_state', '=', 'posted'),
            ('account_id.account_type', 'in', [
                'income', 'income_other',
            ]),
            ('date', '>=', d_from),
            ('date', '<=', d_to),
        ]
        income_groups = MoveLine.read_group(income_domain, ['balance:sum'], [])
        # income accounts normally credit → balance negative; revenue = -balance
        income_balance = _group_balance(income_groups)
        revenue_total = -income_balance

        quick_expense_moves = self.env['pet.clinic.expense'].search([
            ('company_id', '=', company.id),
            ('state', '=', 'posted'),
            ('date', '>=', d_from),
            ('date', '<=', d_to),
            ('move_id', '!=', False),
        ]).mapped('move_id')
        quick_domain = expense_domain + [('move_id', 'in', quick_expense_moves.ids)] if quick_expense_moves else expense_domain + [('id', '=', 0)]
        quick_groups = MoveLine.read_group(quick_domain, ['balance:sum'], []) if quick_expense_moves else []
        quick_expenses_total = _group_balance(quick_groups)

        today = fields.Date.context_today(self)
        expenses_today = MoveLine.read_group(
            [
                ('company_id', '=', company.id),
                ('parent_state', '=', 'posted'),
                ('account_id.account_type', 'in', [
                    'expense', 'expense_direct_cost', 'expense_depreciation',
                ]),
                ('date', '=', today),
            ],
            ['balance:sum'], [],
        )
        expenses_today_total = _group_balance(expenses_today)

        month_start = today.replace(day=1)
        expenses_month = MoveLine.read_group(
            [
                ('company_id', '=', company.id),
                ('parent_state', '=', 'posted'),
                ('account_id.account_type', 'in', [
                    'expense', 'expense_direct_cost', 'expense_depreciation',
                ]),
                ('date', '>=', month_start),
                ('date', '<=', today),
            ],
            ['balance:sum'], [],
        )
        expenses_month_total = _group_balance(expenses_month)

        revenue_today_g = MoveLine.read_group(
            [
                ('company_id', '=', company.id),
                ('parent_state', '=', 'posted'),
                ('account_id.account_type', 'in', ['income', 'income_other']),
                ('date', '=', today),
            ],
            ['balance:sum'], [],
        )
        revenue_today = -_group_balance(revenue_today_g)

        net_profit_loss = revenue_total - expenses_total

        return {
            'company_id': company.id,
            'period': period,
            'date_from': fields.Date.to_string(d_from),
            'date_to': fields.Date.to_string(d_to),
            'currency_id': company.currency_id.id,
            'sections': {
                'liquidity': {
                    'title': _('Liquidity'),
                    'title_ar': 'السيولة',
                    'cards': liquidity_cards,
                },
                'partner_liability': {
                    'title': _('Partner Liabilities'),
                    'title_ar': 'مستحقات الشركاء',
                    'cards': partner_cards,
                },
                'performance': {
                    'title': _('Performance'),
                    'title_ar': 'الأداء',
                    'cards': [
                        {
                            'key': 'net_profit_loss',
                            'label': _('Net Profit/Loss'),
                            'label_ar': 'صافي الربح أو الخسارة',
                            'amount': net_profit_loss,
                        },
                        {
                            'key': 'revenue_period',
                            'label': _('Revenue'),
                            'label_ar': 'الإيرادات',
                            'amount': revenue_total,
                        },
                        {
                            'key': 'expenses_period',
                            'label': _('Expenses'),
                            'label_ar': 'المصروفات',
                            'amount': expenses_total,
                        },
                        {
                            'key': 'revenue_today',
                            'label': _('Revenue Today'),
                            'label_ar': 'إيرادات اليوم',
                            'amount': revenue_today,
                        },
                        {
                            'key': 'expenses_today',
                            'label': _('Expenses Today'),
                            'label_ar': 'مصروفات اليوم',
                            'amount': expenses_today_total,
                        },
                        {
                            'key': 'quick_expenses_period',
                            'label': _('Quick Expenses'),
                            'label_ar': 'مصروفات سريعة',
                            'amount': quick_expenses_total,
                        },
                        {
                            'key': 'expenses_month',
                            'label': _('Expenses This Month'),
                            'label_ar': 'مصروفات الشهر',
                            'amount': expenses_month_total,
                        },
                    ],
                },
            },
        }
