#!/usr/bin/env python3
"""Reclassify Sahel setup accrual to Sabry partner payable (additive correction).

Run via odoo shell:
  exec(open('.../adjust_sahel_sabry_setup_payable.py').read())
  post_sabry_setup_adjustment(env)
  verify_sabry_balance(env)
"""
from datetime import date

REF = 'SAHEL-ADJ-SABRY-SETUP-100K'
AMOUNT = 100000.0


def _account(env, code):
    acc = env['account.account'].search([
        ('code', '=', code),
        ('company_ids', 'in', env.company.id),
    ], limit=1)
    if not acc:
        raise RuntimeError(f'Account {code} not found')
    return acc


def post_sabry_setup_adjustment(env):
    existing = env['account.move'].search([
        ('ref', '=', REF),
        ('company_id', '=', env.company.id),
    ], limit=1)
    if existing:
        print(f'Skip: {REF} already exists as {existing.name} ({existing.state})')
        return existing

    sabry = env['res.partner'].search([('name', '=', 'Sabry Youssef')], limit=1)
    if not sabry:
        raise RuntimeError('Partner Sabry Youssef not found')

    accrued_setup = _account(env, '211102')
    payable = _account(env, '211000')
    journal = env['account.journal'].search([
        ('code', '=', 'MISC'),
        ('company_id', '=', env.company.id),
    ], limit=1)

    move = env['account.move'].create({
        'move_type': 'entry',
        'journal_id': journal.id,
        'date': date.today(),
        'ref': REF,
        'narration': (
            'Sahel: reclassify setup costs paid personally by Sabry Youssef — '
            'move liability from Accrued Setup (211102) to partner payable (211000). '
            'Does not duplicate expense (already in SAHEL-JE3-SETUP-ACCRUAL).'
        ),
        'line_ids': [
            (0, 0, {
                'name': 'Reclass accrued setup → Sabry partner payable',
                'account_id': accrued_setup.id,
                'debit': AMOUNT,
                'credit': 0.0,
            }),
            (0, 0, {
                'name': 'Partner capital — Sabry Youssef setup payments (100k)',
                'account_id': payable.id,
                'partner_id': sabry.id,
                'debit': 0.0,
                'credit': AMOUNT,
            }),
        ],
    })
    move.action_post()
    env.cr.commit()
    print(f'Posted {REF}: {move.name}')
    return move


def verify_sabry_balance(env):
    sabry = env['res.partner'].search([('name', '=', 'Sabry Youssef')], limit=1)
    ahmed = env['res.partner'].search([('name', '=', 'Ahmed Barakat')], limit=1)
    accrued_setup = _account(env, '211102')

    sabry_lines = env['account.move.line'].search([
        ('partner_id', '=', sabry.id),
        ('parent_state', '=', 'posted'),
    ])
    sabry_credit = sum(sabry_lines.mapped('credit'))
    sabry_balance = -sum(sabry_lines.mapped('balance'))

    ahmed_lines = env['account.move.line'].search([
        ('partner_id', '=', ahmed.id),
        ('parent_state', '=', 'posted'),
    ])
    ahmed_balance = -sum(ahmed_lines.mapped('balance'))

    setup_lines = env['account.move.line'].search([
        ('account_id', '=', accrued_setup.id),
        ('parent_state', '=', 'posted'),
    ])
    setup_balance = sum(setup_lines.mapped('balance'))

    print('\n=== Sabry reconciliation ===')
    print(f'Sabry partner payable (amount clinic owes): {sabry_balance:,.2f} EGP')
    print(f'Expected: 150,000.00 EGP')
    print(f'Difference: {150000 - sabry_balance:,.2f} EGP')
    print(f'Ahmed partner payable (unchanged check): {ahmed_balance:,.2f} EGP')
    print(f'Accrued Setup 211102 balance: {setup_balance:,.2f} EGP (expect 0 after adjustment)')


if 'env' in dir():
    post_sabry_setup_adjustment(env)
    verify_sabry_balance(env)
