# -*- coding: utf-8 -*-
"""
bank.sms.transaction — structured financial transactions parsed from bank SMS.

Bank notification SMS (Al Ahly / QNB style, Arabic) are received as
``sms.message.log`` rows (direction='in'). This model extracts the structured
fields (amount, direction, sender/receiver, reference, account, available
balance) so they can be filtered, summed and used to track cashflow / balance.
"""
import logging
import re

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# --- Arabic bank-SMS patterns (Western digits) ----------------------------
_AMOUNT_TRANSFER = re.compile(r'بمبلغ\s+([\d,]+(?:\.\d+)?)')
_AMOUNT_CARD = re.compile(r'خصم\s+([\d,]+(?:\.\d+)?)\s*EGP', re.IGNORECASE)
_REF = re.compile(r'رقم\s*مرجعي\s+(\d+)')
_CP_IN = re.compile(r'من\s+(.+?)\s+رقم\s*مرجعي')
_CP_OUT = re.compile(r'إلى\s+(.+?)\s+رقم\s*مرجعي')
_CP_CARD = re.compile(r'عند\s+(.+?)\s+يوم')
_ACC_TRANSFER = re.compile(r'حسابكم\s+رقم\s+(\d{3,4})')
_ACC_CARD = re.compile(r'بطاقة\s+الخصم\s+المباشر\s+رقم\s+(\d{3,4})')
# Card SMS often include "المتاح 328.66" = available balance after the txn
_AVAILABLE = re.compile(r'المتاح\s+([\d,]+(?:\.\d+)?)')


def _to_float(raw):
    if not raw:
        return 0.0
    try:
        return float(str(raw).replace(',', '').strip())
    except (ValueError, TypeError):
        return 0.0


def parse_bank_sms(body):
    """
    Parse a bank-SMS body into a dict, or return ``None`` if it is not a
    financial transaction (OTP / balance / promo / unknown).

    Returns keys: direction, txn_type, amount, counterparty, ref,
    account_last4, bank_balance (optional).
    """
    if not body:
        return None
    text = body.strip()

    # --- classify -------------------------------------------------------
    if 'إضافة' in text and 'تحويل' in text:
        direction, txn_type = 'in', 'transfer'
    elif 'تحويل' in text and 'حسابكم' in text:
        direction, txn_type = 'out', 'transfer'
    elif 'خصم' in text and 'بطاقة' in text:
        direction, txn_type = 'out', 'card'
    else:
        return None  # non-transaction (OTP / balance / promo …)

    # --- amount ---------------------------------------------------------
    if txn_type == 'card':
        m = _AMOUNT_CARD.search(text)
    else:
        m = _AMOUNT_TRANSFER.search(text)
    amount = _to_float(m.group(1)) if m else 0.0
    if amount <= 0:
        return None

    # --- counterparty (sender if in, receiver if out) -------------------
    if direction == 'in':
        cp = _CP_IN.search(text)
    elif txn_type == 'card':
        cp = _CP_CARD.search(text)
    else:
        cp = _CP_OUT.search(text)
    counterparty = cp.group(1).strip() if cp else ''

    # --- reference ------------------------------------------------------
    r = _REF.search(text)
    ref = r.group(1) if r else ''

    # --- account last 4 -------------------------------------------------
    if txn_type == 'card':
        a = _ACC_CARD.search(text)
    else:
        a = _ACC_TRANSFER.search(text)
    account_last4 = a.group(1) if a else ''

    # --- bank-reported available balance (card SMS mainly) --------------
    av = _AVAILABLE.search(text)
    bank_balance = _to_float(av.group(1)) if av else False

    return {
        'direction': direction,
        'txn_type': txn_type,
        'amount': amount,
        'counterparty': counterparty,
        'ref': ref,
        'account_last4': account_last4,
        'bank_balance': bank_balance,
    }


class BankSmsTransaction(models.Model):
    _name = 'bank.sms.transaction'
    _description = 'Bank SMS Transaction'
    _order = 'date desc, id desc'
    _rec_name = 'counterparty_display'

    date = fields.Datetime(string='Date', required=True, index=True)
    direction = fields.Selection(
        selection=[('in', 'Incoming (Received)'), ('out', 'Outgoing (Sent)')],
        string='Direction', required=True, index=True,
    )
    txn_type = fields.Selection(
        selection=[('transfer', 'Instant Transfer'), ('card', 'Card / Debit'), ('other', 'Other')],
        string='Type', default='transfer', index=True,
    )
    amount = fields.Monetary(string='Amount', currency_field='currency_id')
    # Signed amount (in = +, out = −) for cashflow pivots / graphs.
    signed_amount = fields.Monetary(
        string='Net (+/−)', currency_field='currency_id',
        compute='_compute_signed_amount', store=True,
    )
    # Cumulative balance after this transaction (from earliest SMS forward).
    running_balance = fields.Monetary(
        string='Running Balance', currency_field='currency_id',
        readonly=True, help='Sum of all amounts up to this transaction (in − out).',
    )
    # Balance reported by the bank in the SMS itself (المتاح …), when present.
    bank_balance = fields.Monetary(
        string='Bank Balance (SMS)', currency_field='currency_id',
        help='Available balance extracted from the SMS body (المتاح), when present.',
    )
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.ref('base.EGP', raise_if_not_found=False)
        or self.env.company.currency_id,
    )
    counterparty = fields.Char(
        string='Sender / Receiver', index=True,
        help='Sender for incoming transfers, receiver for outgoing / merchant for card.',
    )
    masked_counterparty_name = fields.Char(
        string='Masked Name',
        readonly=True,
        copy=False,
        index=True,
        help='Original counterparty name exactly as extracted from the bank SMS.',
    )
    real_counterparty_name = fields.Char(
        string='Real Name',
        index=True,
        help='User-confirmed counterparty name supplied by a mapping rule.',
    )
    counterparty_mapping_id = fields.Many2one(
        'bank.sms.counterparty.map',
        string='Counterparty Mapping',
        readonly=True,
        copy=False,
        ondelete='set null',
        index=True,
    )
    mapping_state = fields.Selection(
        [
            ('mapped', 'Mapped'),
            ('unmapped', 'Unmapped'),
            ('conflict', 'Conflict'),
        ],
        string='Mapping Status',
        default='unmapped',
        required=True,
        readonly=True,
        copy=False,
        index=True,
    )
    mapping_conflict = fields.Text(
        string='Mapping Conflict',
        readonly=True,
        copy=False,
    )
    counterparty_display = fields.Char(
        string='Counterparty',
        compute='_compute_counterparty_display',
        store=True,
        index=True,
    )
    partner_id = fields.Many2one('res.partner', string='Contact', ondelete='set null')
    ref = fields.Char(string='Bank Reference', index=True)
    account_last4 = fields.Char(string='Account (last 4)', index=True)
    body = fields.Text(string='Original Message', readonly=True)
    sms_log_id = fields.Many2one(
        'sms.message.log', string='Source SMS', ondelete='cascade', index=True,
    )

    # ── Expense module link ───────────────────────────────────────────────────
    expense_category_id = fields.Many2one(
        'product.product',
        string='Expense Category',
        domain="[('can_be_expensed', '=', True)]",
        help='Odoo Expense category (product with Can be Expensed). Required to create an expense.',
        index=True,
    )
    expense_id = fields.Many2one(
        'hr.expense',
        string='Expense',
        ondelete='set null',
        copy=False,
        index=True,
        help='Linked expense in the Expenses app.',
    )
    expense_state = fields.Selection(
        related='expense_id.state', string='Expense Status', store=False,
    )

    _sql_constraints = [
        ('sms_log_uniq', 'unique(sms_log_id)',
         'A transaction already exists for this SMS.'),
    ]

    @api.depends('amount', 'direction')
    def _compute_signed_amount(self):
        for rec in self:
            rec.signed_amount = rec.amount if rec.direction == 'in' else -rec.amount

    @api.depends('real_counterparty_name', 'masked_counterparty_name', 'counterparty')
    def _compute_counterparty_display(self):
        for rec in self:
            masked = rec.masked_counterparty_name or rec.counterparty or ''
            rec.counterparty_display = (
                '%s — %s' % (rec.real_counterparty_name, masked)
                if rec.real_counterparty_name and masked
                else rec.real_counterparty_name or masked
            )

    @api.model
    def _mapping_values_for_name(self, masked_name):
        mapping, conflicts = self.env['bank.sms.counterparty.map'].resolve(masked_name)
        if conflicts:
            return {
                'real_counterparty_name': False,
                'counterparty_mapping_id': False,
                'mapping_state': 'conflict',
                'mapping_conflict': ', '.join(conflicts.mapped('display_name')),
            }
        if not mapping:
            return {
                'counterparty_mapping_id': False,
                'mapping_state': 'unmapped',
                'mapping_conflict': False,
            }
        return {
            'real_counterparty_name': mapping.real_name,
            'counterparty_mapping_id': mapping.id,
            'mapping_state': 'mapped',
            'mapping_conflict': False,
            'default_category_id': mapping.default_category_id.id,
        }

    def _apply_counterparty_mapping(self):
        for rec in self:
            masked = rec.masked_counterparty_name or rec.counterparty or ''
            values = rec._mapping_values_for_name(masked)
            category_id = values.pop('default_category_id', False)
            if category_id and not rec.expense_category_id:
                values['expense_category_id'] = category_id
            rec.with_context(skip_counterparty_mapping=True).write(values)
        return True

    @api.model
    def _backfill_counterparty_mappings(self, dry_run=True):
        records = self.sudo().search([])
        prepared = []
        result = {
            'total': len(records),
            'changed': 0,
            'mapped': 0,
            'unmapped': 0,
            'conflicts': 0,
        }
        for rec in records:
            masked = rec.masked_counterparty_name or rec.counterparty or ''
            values = rec._mapping_values_for_name(masked)
            category_id = values.pop('default_category_id', False)
            if category_id and not rec.expense_category_id:
                values['expense_category_id'] = category_id
            if values['mapping_state'] == 'mapped':
                result['mapped'] += 1
            elif values['mapping_state'] == 'conflict':
                result['conflicts'] += 1
            else:
                result['unmapped'] += 1
            changed = not rec.masked_counterparty_name
            for field_name, field_value in values.items():
                current = rec[field_name]
                if field_name in ('counterparty_mapping_id', 'expense_category_id'):
                    current = current.id
                if current != field_value:
                    changed = True
                    break
            if changed:
                result['changed'] += 1
            prepared.append((rec, masked, values))

        # Conflicts are reported but never partially applied.
        if dry_run or result['conflicts']:
            return result

        for rec, masked, values in prepared:
            write_values = dict(values)
            if not rec.masked_counterparty_name:
                write_values['masked_counterparty_name'] = masked
            rec.with_context(
                allow_masked_counterparty_backfill=True,
                skip_counterparty_mapping=True,
            ).write(write_values)
        return result

    # ── Running balance ───────────────────────────────────────────────────────

    @api.model
    def _recompute_running_balances(self):
        """
        Walk all transactions oldest→newest and set running_balance =
        cumulative sum of signed_amount. Idempotent; call after sync/import.
        """
        cr = self.env.cr
        cr.execute("""
            UPDATE bank_sms_transaction AS t
               SET running_balance = s.bal
              FROM (
                    SELECT id,
                           SUM(signed_amount) OVER (
                               ORDER BY date ASC, id ASC
                               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                           ) AS bal
                      FROM bank_sms_transaction
                   ) AS s
             WHERE t.id = s.id
        """)
        self.invalidate_model(['running_balance'])
        return True

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals = []
        for incoming_vals in vals_list:
            vals = dict(incoming_vals)
            masked = vals.get('masked_counterparty_name') or vals.get('counterparty') or ''
            if masked:
                vals.setdefault('masked_counterparty_name', masked)
            if not self.env.context.get('skip_counterparty_mapping'):
                mapping_values = self._mapping_values_for_name(masked)
                category_id = mapping_values.pop('default_category_id', False)
                for field_name, value in mapping_values.items():
                    vals.setdefault(field_name, value)
                if category_id:
                    vals.setdefault('expense_category_id', category_id)
            prepared_vals.append(vals)
        records = super().create(prepared_vals)
        self._recompute_running_balances()
        return records

    def write(self, vals):
        if (
            'masked_counterparty_name' in vals
            and not self.env.context.get('allow_masked_counterparty_backfill')
        ):
            for rec in self:
                if (
                    rec.masked_counterparty_name
                    and vals['masked_counterparty_name'] != rec.masked_counterparty_name
                ):
                    raise UserError(
                        'Masked Name is the immutable original value from the bank SMS.'
                    )
        res = super().write(vals)
        if any(k in vals for k in ('amount', 'direction', 'date', 'signed_amount')):
            self._recompute_running_balances()
        return res

    def unlink(self):
        res = super().unlink()
        self._recompute_running_balances()
        return res

    # ── Build transactions from inbound SMS logs ──────────────────────────────

    @api.model
    def _sync_from_logs(self, limit=None):
        """
        Parse every inbound ``sms.message.log`` that has no transaction yet and
        create the matching ``bank.sms.transaction`` rows. Idempotent.
        """
        Log = self.env['sms.message.log'].sudo()
        existing_log_ids = set(
            self.sudo().search([('sms_log_id', '!=', False)]).mapped('sms_log_id').ids
        )
        domain = [('direction', '=', 'in')]
        logs = Log.search(domain, order='sent_at asc', limit=limit)
        vals_list = []
        for log in logs:
            if log.id in existing_log_ids:
                continue
            parsed = parse_bank_sms(log.body or '')
            if not parsed:
                continue
            vals_list.append({
                'date': log.sent_at or fields.Datetime.now(),
                'body': log.body,
                'sms_log_id': log.id,
                'partner_id': log.partner_id.id if log.partner_id else False,
                **parsed,
            })
        created = self.sudo().create(vals_list) if vals_list else self.browse()
        # create() already recomputes running balances; refresh bank_balance on
        # existing rows that may have been imported before that field existed.
        if not created:
            self._recompute_running_balances()
        _logger.info('[Bank SMS] Synced %s new transaction(s) from %s inbound log(s)',
                     len(created), len(logs))
        return len(created)

    def action_sync_from_logs(self):
        """Button: (re)build transactions from the SMS logs."""
        count = self._sync_from_logs()
        # Also backfill bank_balance on existing rows from body text.
        self._backfill_bank_balance()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Bank Transactions',
                'message': '%s new transaction(s) imported. Balances updated.' % count,
                'type': 'success',
                'sticky': False,
            },
        }

    def action_create_update_mapping(self):
        self.ensure_one()
        masked = self.masked_counterparty_name or self.counterparty
        if not masked:
            raise UserError('Masked Name is required before creating a mapping.')
        if not self.real_counterparty_name:
            raise UserError('Enter the Real Name before creating a mapping.')

        Mapping = self.env['bank.sms.counterparty.map']
        mapping = Mapping.search([
            ('match_type', '=', 'exact'),
            ('masked_name', '=', masked),
        ], limit=1)
        values = {
            'real_name': self.real_counterparty_name,
            'default_category_id': self.expense_category_id.id or False,
            'active': True,
        }
        if mapping:
            mapping.write(values)
        else:
            mapping = Mapping.create({
                'masked_name': masked,
                'match_type': 'exact',
                **values,
            })

        result = self._backfill_counterparty_mappings(dry_run=False)
        if result['conflicts']:
            raise UserError(
                'Mapping saved, but no transactions were changed because %s '
                'transaction(s) have conflicting rules. Resolve priorities first.'
                % result['conflicts']
            )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Counterparty Mapping',
                'message': 'Mapping saved and applied to %s transaction(s).'
                           % result['changed'],
                'type': 'success',
                'sticky': False,
            },
        }

    @api.model
    def _backfill_bank_balance(self):
        """Re-parse bodies for bank_balance on rows that still lack it."""
        to_fix = self.sudo().search([
            '|', ('bank_balance', '=', False), ('bank_balance', '=', 0),
            ('body', 'ilike', 'المتاح'),
        ])
        for rec in to_fix:
            parsed = parse_bank_sms(rec.body or '')
            if parsed and parsed.get('bank_balance'):
                rec.bank_balance = parsed['bank_balance']
        self._recompute_running_balances()
        return len(to_fix)

    # ── Expense categories & Expenses app link ────────────────────────────────

    def _default_expense_category(self):
        """Pick a sensible category from txn_type when none is set."""
        self.ensure_one()
        xmlid = (
            'phone_sms_connector.product_expense_card'
            if self.txn_type == 'card'
            else 'phone_sms_connector.product_expense_bank_transfer'
        )
        return self.env.ref(xmlid, raise_if_not_found=False)

    def _get_expense_employee(self):
        """Employee that owns the expense (current user, else Administrator)."""
        employee = self.env.user.employee_id
        if not employee:
            employee = self.env['hr.employee'].sudo().search([], limit=1)
        return employee

    def action_suggest_category(self):
        """Fill empty categories from txn_type defaults (card vs transfer)."""
        for rec in self.filtered(lambda r: r.direction == 'out' and not r.expense_category_id):
            cat = rec._default_expense_category()
            if cat:
                rec.expense_category_id = cat.id
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Expense Category',
                'message': 'Default categories applied to outgoing transactions without a category.',
                'type': 'success',
                'sticky': False,
            },
        }

    def action_create_expense(self):
        """Create draft hr.expense from outgoing bank SMS transactions."""
        Expense = self.env['hr.expense'].sudo()
        created = self.env['hr.expense']
        skipped = 0
        errors = []

        for rec in self:
            if rec.direction != 'out':
                skipped += 1
                continue
            if rec.expense_id:
                skipped += 1
                continue
            category = rec.expense_category_id or rec._default_expense_category()
            if not category:
                errors.append('%s: no expense category' % (rec.display_name or rec.id))
                continue
            if not rec.expense_category_id:
                rec.expense_category_id = category.id

            employee = rec._get_expense_employee()
            if not employee:
                raise UserError(
                    'No HR employee found. Create an employee (or link your user) '
                    'before creating expenses.'
                )

            name = rec.counterparty or 'Bank SMS expense'
            if rec.ref:
                name = '%s [%s]' % (name, rec.ref)
            expense_date = fields.Date.to_date(rec.date) if rec.date else fields.Date.context_today(rec)

            expense = Expense.create({
                'name': name[:200],
                'employee_id': employee.id,
                'product_id': category.id,
                'total_amount_currency': rec.amount,
                'currency_id': (rec.currency_id or self.env.company.currency_id).id,
                'date': expense_date,
                'payment_mode': 'company_account',  # already paid from bank/card
                'vendor_id': rec.partner_id.id if rec.partner_id else False,
                'quantity': 1,
                'description': rec.body or '',
                'bank_sms_transaction_id': rec.id,
            })
            rec.expense_id = expense.id
            created |= expense

        msg = 'Created %s expense(s)' % len(created)
        if skipped:
            msg += ', skipped %s' % skipped
        if errors:
            msg += '. Issues: ' + '; '.join(errors[:5])

        if len(created) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Expense',
                'res_model': 'hr.expense',
                'res_id': created.id,
                'view_mode': 'form',
                'target': 'current',
            }
        if created:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Created Expenses',
                'res_model': 'hr.expense',
                'domain': [('id', 'in', created.ids)],
                'view_mode': 'list,form',
                'target': 'current',
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Expenses',
                'message': msg,
                'type': 'warning' if errors else 'info',
                'sticky': False,
            },
        }

    def action_open_expense(self):
        self.ensure_one()
        if not self.expense_id:
            raise UserError('No expense linked yet. Use Create Expense first.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Expense',
            'res_model': 'hr.expense',
            'res_id': self.expense_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
