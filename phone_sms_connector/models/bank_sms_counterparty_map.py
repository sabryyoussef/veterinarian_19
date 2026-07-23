# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class BankSmsCounterpartyMap(models.Model):
    _name = 'bank.sms.counterparty.map'
    _description = 'Bank SMS Counterparty Mapping'
    _order = 'priority desc, id asc'
    _rec_name = 'masked_name'

    masked_name = fields.Char(string='Masked Name', required=True, index=True)
    real_name = fields.Char(string='Real Name', required=True, index=True)
    default_category_id = fields.Many2one(
        'product.product',
        string='Default Category',
        domain="[('can_be_expensed', '=', True)]",
        ondelete='restrict',
    )
    notes = fields.Text()
    active = fields.Boolean(default=True, index=True)
    match_type = fields.Selection(
        [
            ('exact', 'Exact'),
            ('contains', 'Contains'),
            ('regex', 'Regex'),
        ],
        required=True,
        default='exact',
        index=True,
    )
    priority = fields.Integer(
        default=10,
        required=True,
        index=True,
        help='Higher-priority rules are evaluated first.',
    )

    def init(self):
        """Prevent concurrent creation of duplicate exact rules."""
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
                bank_sms_counterparty_map_exact_name_uniq
            ON bank_sms_counterparty_map (masked_name)
            WHERE match_type = 'exact'
        """)

    @api.constrains('masked_name', 'match_type')
    def _check_exact_uniqueness(self):
        for rec in self.filtered(lambda item: item.match_type == 'exact' and item.masked_name):
            duplicate = self.search_count([
                ('id', '!=', rec.id),
                ('match_type', '=', 'exact'),
                ('masked_name', '=', rec.masked_name),
            ])
            if duplicate:
                raise ValidationError(
                    'An Exact mapping already exists for this Masked Name.'
                )

    @api.constrains('masked_name', 'match_type')
    def _check_regex(self):
        for rec in self.filtered(lambda item: item.match_type == 'regex'):
            try:
                re.compile(rec.masked_name or '')
            except re.error as exc:
                raise ValidationError('Invalid regular expression: %s' % exc) from exc

    def _matches_name(self, masked_name):
        self.ensure_one()
        if not masked_name:
            return False
        if self.match_type == 'exact':
            return masked_name == self.masked_name
        if self.match_type == 'contains':
            return self.masked_name in masked_name
        try:
            return bool(re.search(self.masked_name, masked_name))
        except re.error:
            return False

    @api.model
    def resolve(self, masked_name):
        """Return ``(winner, conflicts)`` without guessing ambiguous matches."""
        if not masked_name:
            return self.browse(), self.browse()
        rules = self.search([('active', '=', True)], order='priority desc, id asc')
        matching = rules.filtered(lambda rule: rule._matches_name(masked_name))
        if not matching:
            return self.browse(), self.browse()

        specificity = {'exact': 3, 'contains': 2, 'regex': 1}
        best_key = max(
            (rule.priority, specificity[rule.match_type])
            for rule in matching
        )
        best = matching.filtered(
            lambda rule: (rule.priority, specificity[rule.match_type]) == best_key
        )
        if len(best) > 1:
            return self.browse(), best
        return best, self.browse()

    def action_apply_to_transactions(self):
        result = self.env['bank.sms.transaction']._backfill_counterparty_mappings(
            dry_run=False
        )
        if result['conflicts']:
            raise UserError(
                'No changes were applied because %s transaction(s) have '
                'conflicting top-priority rules.' % result['conflicts']
            )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Counterparty Mappings',
                'message': '%s transaction(s) updated; %s remain unmapped.'
                           % (result['changed'], result['unmapped']),
                'type': 'success',
                'sticky': False,
            },
        }
