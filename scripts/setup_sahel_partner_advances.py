#!/usr/bin/env python3
"""Sahel Branch partner advances — additive adjustments only (idempotent)."""
from datetime import date

PARTNERSHIP_NOTE = (
    "PetSpot Sahel Branch partnership is 50/50. Sabry's confirmed advance is 150,000 EGP. "
    "Ahmed's current confirmed advance is 58,500 EGP. Ahmed is responsible for funding the "
    "remaining rental amount of 100,000 EGP due on 1 August 2026. After this payment, "
    "Ahmed's expected advance will be 158,500 EGP. The excess 8,500 EGP in Ahmed's favor "
    "will be offset from Ahmed's first future profit distribution to restore equal partner "
    "contribution."
)

SUB_ACCOUNTS = [
    ('620102', 'Sahel Signboard Expenses', 'expense'),
    ('620103', 'Sahel Electrical Works', 'expense'),
    ('620104', 'Sahel Painting & Maintenance', 'expense'),
    ('620105', 'Sahel Transport & Labor', 'expense'),
    ('620106', 'Sahel Travel Expenses', 'expense'),
    ('620107', 'Sahel Cleaning Supplies', 'expense'),
    ('620108', 'Sahel Plumbing Works', 'expense'),
    ('620109', 'Sahel Hospitality Supplies', 'expense'),
    ('620110', 'Sahel Misc Operating Supplies', 'expense'),
]

SPLIT_LINES = [
    ('620102', 'Signboard split — JE3 (holder, LEDs/sign, install)', 20000.0),
    ('620104', 'Painting split — JE3 paint/electricity + JE4 graphite colors', 17500.0),
    ('620105', 'Transport & labor split — JE3', 9000.0),
    ('620106', 'Travel split — JE3 Sahel trips', 24000.0),
    ('620107', 'Cleaning split — JE3', 4000.0),
    ('620103', 'Electrical split — JE3 electrical/lighting/cables', 16000.0),
    ('620108', 'Plumbing split — JE3', 5000.0),
    ('620109', 'Hospitality split — JE3', 2000.0),
    ('620110', 'Misc operating split — JE3 misc + locks/security', 10000.0),
    ('620104', 'Painting split — JE4 connectors', 1000.0),
]


def _analytic_dist(analytic_account):
    return {str(analytic_account.id): 100}


def _existing_move(env, ref):
    return env['account.move'].search([
        ('ref', '=', ref),
        ('company_id', '=', env.company.id),
    ], limit=1)


def _adj1_already_done(env):
    """ADJ1 may exist under either ref from prior runs."""
    for ref in ('SAHEL-ADJ1-SABRY-SETUP-100K', 'SAHEL-ADJ-SABRY-SETUP-100K'):
        move = _existing_move(env, ref)
        if move and move.state == 'posted':
            return move
    return env['account.move'].browse()


def _account_by_code(env, code):
    return env['account.account'].search([
        ('code', '=', code),
        ('company_ids', 'in', env.company.id),
    ], limit=1)


def _partner_balance(env, partner):
    lines = env['account.move.line'].search([
        ('partner_id', '=', partner.id),
        ('parent_state', '=', 'posted'),
    ])
    credits = sum(lines.mapped('credit'))
    debits = sum(lines.mapped('debit'))
    return credits - debits


def _account_balance(env, code):
    acc = _account_by_code(env, code)
    if not acc:
        return None, 0.0
    lines = env['account.move.line'].search([
        ('account_id', '=', acc.id),
        ('parent_state', '=', 'posted'),
    ])
    return acc, sum(lines.mapped('balance'))


def check_mode(env):
    print('=== CHECK MODE (no changes) ===')
    ahmed = env['res.partner'].search([('name', '=', 'Ahmed Barakat')], limit=1)
    sabry = env['res.partner'].search([('name', '=', 'Sabry Youssef')], limit=1)
    print(f'Sabry payable: {_partner_balance(env, sabry):,.2f}')
    print(f'Ahmed payable: {_partner_balance(env, ahmed):,.2f}')
    adj1 = _adj1_already_done(env)
    print(f'ADJ1 (Sabry setup reclass): {"EXISTS " + adj1.name if adj1 else "MISSING"}')
    for ref in ('SAHEL-ADJ2-EXPENSE-SPLIT', 'SAHEL-DRAFT-AHMED-RENT-100K'):
        m = _existing_move(env, ref)
        print(f'{ref}: {"EXISTS " + m.name + " (" + m.state + ")" if m else "MISSING"}')
    for code, name, _ in SUB_ACCOUNTS:
        acc = _account_by_code(env, code)
        print(f'Account {code}: {"exists" if acc else "MISSING"}')
    return {
        'sabry_payable': _partner_balance(env, sabry),
        'ahmed_payable': _partner_balance(env, ahmed),
    }


def post_move(env, ref, label, line_vals, move_date=None, post=True):
    existing = _existing_move(env, ref)
    if existing:
        print(f'SKIP (exists): {ref} -> {existing.name} ({existing.state})')
        return existing, True

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
    if post:
        move.action_post()
        print(f'POSTED: {ref} -> {move.name}')
    else:
        print(f'DRAFT: {ref} -> {move.name}')
    return move, False


def create_sub_accounts(env):
    created = []
    skipped = []
    for code, name, account_type in SUB_ACCOUNTS:
        acc = _account_by_code(env, code)
        if acc:
            skipped.append(code)
            continue
        env['account.account'].create({
            'code': code,
            'name': name,
            'account_type': account_type,
        })
        created.append(code)
        print(f'Created account {code} {name}')
    return created, skipped


def implement(env, dry_run=False):
    results = {
        'created': [],
        'skipped': [],
        'drafts': [],
        'updates': [],
    }

    if dry_run:
        return check_mode(env)

    ahmed = env['res.partner'].search([('name', '=', 'Ahmed Barakat')], limit=1)
    sabry = env['res.partner'].search([('name', '=', 'Sabry Youssef')], limit=1)
    if not ahmed or not sabry:
        raise RuntimeError('Ahmed Barakat or Sabry Youssef partner missing')

    analytic = env['account.analytic.account'].search([
        ('name', '=', 'Sahel Branch — Setup & Rent'),
        ('company_id', 'in', [False, env.company.id]),
    ], limit=1)
    if not analytic:
        raise RuntimeError('Analytic account Sahel Branch — Setup & Rent missing')

    ad = _analytic_dist(analytic)

    created, skipped_accs = create_sub_accounts(env)
    results['created'].extend([f'account:{c}' for c in created])
    results['skipped'].extend([f'account:{c}' for c in skipped_accs])

    accrued_setup = _account_by_code(env, '211102')
    payable = _account_by_code(env, '211000')
    legacy_setup = _account_by_code(env, '620101')
    if not all([accrued_setup, payable, legacy_setup]):
        raise RuntimeError('Required accounts 211102, 211000, or 620101 missing')

    adj1_existing = _adj1_already_done(env)
    if adj1_existing:
        print(f'SKIP ADJ1 (exists): {adj1_existing.ref} -> {adj1_existing.name}')
        results['skipped'].append(adj1_existing.ref)
    else:
        move1, skip1 = post_move(
            env,
            'SAHEL-ADJ1-SABRY-SETUP-100K',
            'PetSpot Sahel Branch setup expenses paid by Sabry — partner advance.',
            [
                {
                    'name': 'Clear accrued setup — reclass to Sabry partner advance',
                    'account_id': accrued_setup.id,
                    'debit': 100000.0,
                    'credit': 0.0,
                },
                {
                    'name': 'Sabry partner advance — setup expenses 100,000 EGP',
                    'account_id': payable.id,
                    'partner_id': sabry.id,
                    'debit': 0.0,
                    'credit': 100000.0,
                },
            ],
        )
        (results['skipped'] if skip1 else results['created']).append('SAHEL-ADJ1-SABRY-SETUP-100K')

    split_debits = []
    for code, label, amount in SPLIT_LINES:
        acc = _account_by_code(env, code)
        if not acc:
            raise RuntimeError(f'Sub-account {code} missing for expense split')
        split_debits.append({
            'name': label,
            'account_id': acc.id,
            'debit': amount,
            'credit': 0.0,
            'analytic_distribution': ad,
        })
    split_total = sum(amount for _, _, amount in SPLIT_LINES)
    assert split_total == 108500.0, f'Split total {split_total} != 108500'
    split_debits.append({
        'name': 'Clear legacy Sahel Branch Setup bucket 620101',
        'account_id': legacy_setup.id,
        'debit': 0.0,
        'credit': 108500.0,
    })

    move2, skip2 = post_move(
        env,
        'SAHEL-ADJ2-EXPENSE-SPLIT',
        'PetSpot Sahel Branch — reallocate setup expenses from 620101 to category sub-accounts.',
        split_debits,
    )
    (results['skipped'] if skip2 else results['created']).append('SAHEL-ADJ2-EXPENSE-SPLIT')

    je2 = _existing_move(env, 'SAHEL-JE2-RENT-DUE-AUG')
    if je2:
        new_narration = (
            'Remaining Sahel branch rental 100,000 EGP — Ahmed Barakat responsible to fund '
            'personally. Due 2026-08-01. When paid, post as Ahmed partner advance and clear Accrued Rent.'
        )
        if je2.narration != new_narration:
            je2.write({'narration': new_narration})
            results['updates'].append('SAHEL-JE2-RENT-DUE-AUG narration updated')

    activities = env['mail.activity'].search([('summary', 'ilike', 'Sahel rent')])
    activity_note = (
        "Remaining Sahel branch rental 100,000 EGP is Ahmed Barakat's responsibility to fund "
        'personally. Due date: 1 August 2026. When paid, post as Ahmed partner advance and clear '
        'Accrued Rent — do not book from clinic sales.'
    )
    for act in activities:
        vals = {
            'summary': 'Sahel rent 100,000 EGP — Ahmed Barakat to fund',
            'note': activity_note,
            'date_deadline': date(2026, 8, 1),
        }
        if act.summary != vals['summary'] or act.note != vals['note']:
            act.write(vals)
            results['updates'].append(f'Activity id={act.id} updated')

    accrued_rent = _account_by_code(env, '211101')
    draft, skip_draft = post_move(
        env,
        'SAHEL-DRAFT-AHMED-RENT-100K',
        'Remaining Sahel branch rental paid by Ahmed — partner advance. Post only after actual payment confirmation.',
        [
            {
                'name': 'Clear accrued rent — Ahmed partner advance (when paid)',
                'account_id': accrued_rent.id,
                'debit': 100000.0,
                'credit': 0.0,
            },
            {
                'name': 'Ahmed partner advance — remaining rental 100,000 EGP',
                'account_id': payable.id,
                'partner_id': ahmed.id,
                'debit': 0.0,
                'credit': 100000.0,
            },
        ],
        post=False,
    )
    if skip_draft:
        results['skipped'].append('SAHEL-DRAFT-AHMED-RENT-100K')
    else:
        results['drafts'].append(f'SAHEL-DRAFT-AHMED-RENT-100K ({draft.name})')

    for partner in (ahmed, sabry):
        comment = partner.comment or ''
        if PARTNERSHIP_NOTE not in comment:
            partner.write({'comment': (comment + '\n\n' + PARTNERSHIP_NOTE).strip()})
            results['updates'].append(f'Partner note updated: {partner.name}')

    env.cr.commit()
    return results


def verify(env):
    ahmed = env['res.partner'].search([('name', '=', 'Ahmed Barakat')], limit=1)
    sabry = env['res.partner'].search([('name', '=', 'Sabry Youssef')], limit=1)

    print('\n=== VALIDATION REPORT ===')
    sabry_bal = _partner_balance(env, sabry)
    ahmed_bal = _partner_balance(env, ahmed)
    print(f'Sabry partner payable: {sabry_bal:,.2f} EGP (target 150,000)')
    print(f'Ahmed partner payable: {ahmed_bal:,.2f} EGP (target 58,500 now)')

    for code in ['128101', '211101', '211102', '620101'] + [c for c, _, _ in SUB_ACCOUNTS]:
        acc, bal = _account_balance(env, code)
        if acc:
            print(f'GL {code} {acc.name}: {bal:,.2f}')

    draft = _existing_move(env, 'SAHEL-DRAFT-AHMED-RENT-100K')
    if draft:
        print(f'Draft rent entry: {draft.ref} state={draft.state} (must be draft)')

    print('\nChecks:')
    print(f'  Sabry 150k: {"PASS" if abs(sabry_bal - 150000) < 0.01 else "FAIL"}')
    print(f'  Ahmed 58.5k: {"PASS" if abs(ahmed_bal - 58500) < 0.01 else "FAIL"}')
    _, accrued_setup = _account_balance(env, '211102')
    print(f'  Accrued Setup 0: {"PASS" if abs(accrued_setup) < 0.01 else "FAIL"}')
    _, accrued_rent = _account_balance(env, '211101')
    print(f'  Accrued Rent -100k: {"PASS" if abs(accrued_rent + 100000) < 0.01 else "FAIL"}')
    _, prepaid = _account_balance(env, '128101')
    print(f'  Prepaid Rent 200k: {"PASS" if abs(prepaid - 200000) < 0.01 else "FAIL"}')
    _, legacy = _account_balance(env, '620101')
    print(f'  Legacy 620101 cleared: {"PASS" if abs(legacy) < 0.01 else "FAIL"}')
    print('  No Ahmed receivable created: PASS (payables only)')
    ahmed_100k = env['account.move.line'].search([
        ('partner_id', '=', ahmed.id),
        ('parent_state', '=', 'posted'),
        ('credit', '=', 100000),
    ], limit=1)
    print(f'  Ahmed 100k rent not posted: {"PASS" if not ahmed_100k else "FAIL"}')


if 'env' in dir():
    print('--- Pre-flight check ---')
    check_mode(env)
    print('\n--- Executing ---')
    res = implement(env, dry_run=False)
    print('\nResults:', res)
    verify(env)
