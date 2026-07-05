#!/usr/bin/env python3
"""One-shot Sahel clinic accounting setup — run via odoo shell."""
from datetime import date

COMPANY = None  # env.company at runtime


def _analytic_dist(analytic_account):
    return {str(analytic_account.id): 100}


def setup_prerequisites(env):
    company = env.company

    # Activate EGP and set company currency
    egp = env['res.currency'].with_context(active_test=False).search([('name', '=', 'EGP')], limit=1)
    if not egp:
        raise RuntimeError('EGP currency not found')
    if not egp.active:
        egp.active = True

    if company.currency_id.name != 'EGP':
        company.currency_id = egp
        print(f'Set company currency to EGP (id={egp.id})')

    # Enable analytic accounting for all internal users
    analytic_group = env.ref('analytic.group_analytic_accounting')
    users = env['res.users'].search([('share', '=', False)])
    for user in users:
        if analytic_group not in user.group_ids:
            user.write({'group_ids': [(4, analytic_group.id)]})
    print('Enabled analytic accounting group for internal users')

    # Analytic account
    plan = env['account.analytic.plan'].search([], limit=1)
    analytic = env['account.analytic.account'].search([
        ('name', '=', 'Sahel Branch — Setup & Rent'),
        ('company_id', 'in', [False, company.id]),
    ], limit=1)
    if not analytic:
        analytic = env['account.analytic.account'].create({
            'name': 'Sahel Branch — Setup & Rent',
            'plan_id': plan.id,
            'company_id': company.id,
        })
        print(f'Created analytic account id={analytic.id}')
    else:
        print(f'Using existing analytic account id={analytic.id}')

    return analytic


def setup_master_data(env):
    company = env.company

    def get_or_create_account(code, name, account_type, reconcile=False):
        acc = env['account.account'].search([
            ('code', '=', code),
            ('company_ids', 'in', company.id),
        ], limit=1)
        if acc:
            return acc
        return env['account.account'].create({
            'code': code,
            'name': name,
            'account_type': account_type,
            'reconcile': reconcile,
        })

    accounts = {
        'prepaid_rent': get_or_create_account(
            '128101', 'Prepaid Rent — Sahel', 'asset_current'),
        'accrued_rent': get_or_create_account(
            '211101', 'Accrued Rent — Sahel', 'liability_current'),
        'accrued_setup': get_or_create_account(
            '211102', 'Accrued Setup Costs — Sahel', 'liability_current'),
        'setup_expense': get_or_create_account(
            '620101', 'Sahel Branch Setup', 'expense'),
        'payable': env['account.account'].search([
            ('code', '=', '211000'),
            ('company_ids', 'in', company.id),
        ], limit=1),
    }
    if not accounts['payable']:
        accounts['payable'] = get_or_create_account(
            '211000', 'Account Payable', 'liability_payable', reconcile=True)

    # Partners
    ahmed = env['res.partner'].search([('name', '=', 'Ahmed Barakat')], limit=1)
    if not ahmed:
        ahmed = env['res.partner'].create({
            'name': 'Ahmed Barakat',
            'company_type': 'person',
            'supplier_rank': 1,
            'comment': 'Sahel clinic partner — 50% share',
        })
        print(f'Created partner Ahmed Barakat id={ahmed.id}')
    else:
        ahmed.write({'supplier_rank': max(ahmed.supplier_rank, 1)})

    sabry = env['res.partner'].search([
        ('name', 'in', ['Sabry Youssef', 'sabryyoussef']),
    ], limit=1)
    if sabry:
        sabry.write({
            'name': 'Sabry Youssef',
            'supplier_rank': max(sabry.supplier_rank, 1),
            'comment': (sabry.comment or '') + '\nSahel clinic partner — 50% share',
        })
    else:
        sabry = env['res.partner'].create({
            'name': 'Sabry Youssef',
            'company_type': 'person',
            'supplier_rank': 1,
            'comment': 'Sahel clinic partner — 50% share',
        })
    print(f'Partner Sabry Youssef id={sabry.id}')

    journal = env['account.journal'].search([
        ('code', '=', 'MISC'),
        ('company_id', '=', company.id),
    ], limit=1)

    return accounts, ahmed, sabry, journal


def _existing_move(env, ref):
    return env['account.move'].search([
        ('ref', '=', ref),
        ('company_id', '=', env.company.id),
    ], limit=1)


def post_move(env, ref, label, line_vals, move_date=None):
    existing = _existing_move(env, ref)
    if existing:
        print(f'Skip existing move {ref}: {existing.name} ({existing.state})')
        return existing

    journal = env['account.journal'].search([
        ('code', '=', 'MISC'),
        ('company_id', '=', env.company.id),
    ], limit=1)

    move = env['account.move'].create({
        'move_type': 'entry',
        'journal_id': journal.id,
        'date': move_date or date.today(),
        'ref': ref,
        'narration': label,
        'line_ids': [(0, 0, v) for v in line_vals],
    })
    move.action_post()
    print(f'Posted {ref}: {move.name}')
    return move


def implement(env):
    analytic = setup_prerequisites(env)
    accounts, ahmed, sabry, journal = setup_master_data(env)
    ad = _analytic_dist(analytic)
    payable = accounts['payable']

    # JE #1 — Rent paid by partners (100k)
    post_move(env, 'SAHEL-JE1-RENT-PAID', 'Sahel: rent paid 100k (Ahmed 50k + Sabry 50k)', [
        {
            'name': 'Prepaid rent — Sahel (paid portion)',
            'account_id': accounts['prepaid_rent'].id,
            'debit': 100000.0,
            'credit': 0.0,
            'analytic_distribution': ad,
        },
        {
            'name': 'Partner capital — Ahmed Barakat rent',
            'account_id': payable.id,
            'partner_id': ahmed.id,
            'debit': 0.0,
            'credit': 50000.0,
        },
        {
            'name': 'Partner capital — Sabry Youssef rent',
            'account_id': payable.id,
            'partner_id': sabry.id,
            'debit': 0.0,
            'credit': 50000.0,
        },
    ])

    # JE #2 — Rent due 1 August (100k from sales)
    move2 = post_move(
        env,
        'SAHEL-JE2-RENT-DUE-AUG',
        'Sahel: rent remaining 100k due 1 August — pay from clinic sales',
        [
            {
                'name': 'Prepaid rent — Sahel (due Aug 1)',
                'account_id': accounts['prepaid_rent'].id,
                'debit': 100000.0,
                'credit': 0.0,
                'analytic_distribution': ad,
            },
            {
                'name': 'Accrued rent — Sahel (due 2026-08-01)',
                'account_id': accounts['accrued_rent'].id,
                'debit': 0.0,
                'credit': 100000.0,
            },
        ],
    )

    # Activity reminder for Aug 1 rent payment
    if move2 and not env['mail.activity'].search([
        ('res_model', '=', 'account.move'),
        ('res_id', '=', move2.id),
        ('summary', 'ilike', 'Sahel rent'),
    ], limit=1):
        activity_type = env.ref('mail.mail_activity_data_todo')
        env['mail.activity'].create({
            'activity_type_id': activity_type.id,
            'summary': 'Sahel rent payment 100,000 EGP due',
            'note': 'Pay accrued rent (100k EGP) from clinic sales. Ref: SAHEL-JE2-RENT-DUE-AUG',
            'date_deadline': date(2026, 8, 1),
            'user_id': env.ref('base.user_admin').id,
            'res_model_id': env['ir.model']._get('account.move').id,
            'res_id': move2.id,
        })
        print('Created Aug 1 rent payment activity')

    # JE #3 — Setup accrual (100k, 14 line items)
    setup_lines = [
        ('حامل يافطة', 8000),
        ('ليدات وترانسات ومشتريات اليافطة', 7000),
        ('دهانات وكهرباء', 10000),
        ('نقل ويوميات عمال', 9000),
        ('فك وتركيب يافطة', 5000),
        ('انتقالات من وإلى الساحل', 24000),
        ('أدوات نظافة', 4000),
        ('تأسيسات كهرباء إضافية (مفاتيح – فيش – قواطع)', 8000),
        ('أعمال سباكة وخامات', 5000),
        ('لمبات وإضاءة احتياطية', 4000),
        ('كابلات ومشتركات ووصلات كهربائية', 4000),
        ('أقفال ومفاتيح وإكسسوارات أمان', 3000),
        ('أدوات ضيافة (كاتل – أكواب – شاي – سكر – مياه)', 2000),
        ('أدوات ومستلزمات تشغيل متنوعة', 7000),
    ]
    assert sum(v for _, v in setup_lines) == 100000

    je3_lines = []
    for label, amount in setup_lines:
        je3_lines.append({
            'name': label,
            'account_id': accounts['setup_expense'].id,
            'debit': float(amount),
            'credit': 0.0,
            'analytic_distribution': ad,
        })
    je3_lines.append({
        'name': 'Accrued setup costs — Sahel (pay from sales)',
        'account_id': accounts['accrued_setup'].id,
        'debit': 0.0,
        'credit': 100000.0,
    })
    post_move(
        env,
        'SAHEL-JE3-SETUP-ACCRUAL',
        'Sahel: branch setup costs 100k — to be paid from clinic sales',
        je3_lines,
    )

    # JE #4 — Ahmed graphite extras (transport TBD — not included)
    post_move(
        env,
        'SAHEL-JE4-AHMED-GRAPHITE',
        'Sahel: Ahmed Barakat personal spend — graphite colors + connectors (transport TBD)',
        [
            {
                'name': 'ألوان / graphite work',
                'account_id': accounts['setup_expense'].id,
                'debit': 7500.0,
                'credit': 0.0,
                'analytic_distribution': ad,
            },
            {
                'name': 'موصلات / connectors',
                'account_id': accounts['setup_expense'].id,
                'debit': 1000.0,
                'credit': 0.0,
                'analytic_distribution': ad,
            },
            {
                'name': 'Reimburse Ahmed Barakat — graphite work',
                'account_id': payable.id,
                'partner_id': ahmed.id,
                'debit': 0.0,
                'credit': 8500.0,
            },
        ],
    )

    # Optional budget if module available
    if 'crossovered.budget' in env:
        budget = env['crossovered.budget'].search([
            ('name', '=', 'Sahel sales-funded payments'),
        ], limit=1)
        if not budget:
            try:
                budget = env['crossovered.budget'].create({
                    'name': 'Sahel sales-funded payments',
                    'date_from': date(2026, 7, 1),
                    'date_to': date(2026, 12, 31),
                })
                env['crossovered.budget.lines'].create({
                    'crossovered_budget_id': budget.id,
                    'general_budget_id': env['account.budget.post'].search([], limit=1).id,
                    'date_from': date(2026, 7, 1),
                    'date_to': date(2026, 12, 31),
                    'planned_amount': -200000.0,
                    'analytic_account_id': analytic.id,
                })
                print('Created budget: Sahel sales-funded payments 200k')
            except Exception as exc:
                print(f'Budget skipped: {exc}')
    else:
        print('Budget module not installed — skipped optional budget')

    env.cr.commit()
    print('Committed all changes')


def verify(env):
    ahmed = env['res.partner'].search([('name', '=', 'Ahmed Barakat')], limit=1)
    sabry = env['res.partner'].search([('name', '=', 'Sabry Youssef')], limit=1)
    analytic = env['account.analytic.account'].search([
        ('name', '=', 'Sahel Branch — Setup & Rent'),
    ], limit=1)

    print('\n=== VERIFICATION ===')
    print('Currency:', env.company.currency_id.name)
    print('Analytic:', analytic.name, analytic.id)

    for partner in (ahmed, sabry):
        lines = env['account.move.line'].search([
            ('partner_id', '=', partner.id),
            ('parent_state', '=', 'posted'),
        ])
        balance = sum(lines.mapped('balance'))
        print(f'Partner {partner.name}: payable balance={-balance:,.2f} EGP ({len(lines)} lines)')

    moves = env['account.move'].search([
        ('ref', 'ilike', 'SAHEL-'),
        ('state', '=', 'posted'),
    ])
    print(f'Sahel journal entries: {len(moves)}')
    for m in moves.sorted('ref'):
        print(f'  {m.ref}: {m.name} total={m.amount_total:,.2f}')

    if analytic:
        a_lines = env['account.analytic.line'].search([
            ('account_id', '=', analytic.id),
        ])
        total = sum(a_lines.mapped('amount'))
        print(f'Analytic Sahel total expense (signed): {total:,.2f} EGP across {len(a_lines)} lines')

    prepaid = env['account.account'].search([('code', '=', '128101')], limit=1)
    accrued_rent = env['account.account'].search([('code', '=', '211101')], limit=1)
    accrued_setup = env['account.account'].search([('code', '=', '211102')], limit=1)
    for acc in (prepaid, accrued_rent, accrued_setup):
        if acc:
            lines = env['account.move.line'].search([
                ('account_id', '=', acc.id),
                ('parent_state', '=', 'posted'),
            ])
            print(f'Account {acc.code} {acc.name}: balance={sum(lines.mapped("balance")):,.2f}')


# Entry point for odoo shell: exec(open(...).read()); implement(env); verify(env)
if 'env' in dir():
    implement(env)
    verify(env)
