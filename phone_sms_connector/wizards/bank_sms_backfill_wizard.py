# -*- coding: utf-8 -*-
from odoo import fields, models


class BankSmsBackfillWizard(models.TransientModel):
    _name = 'bank.sms.backfill.wizard'
    _description = 'Bank SMS Counterparty Backfill'

    state = fields.Selection(
        [('draft', 'Draft'), ('preview', 'Previewed'), ('done', 'Applied')],
        default='draft',
        required=True,
        readonly=True,
    )
    total_count = fields.Integer(readonly=True)
    changed_count = fields.Integer(readonly=True)
    mapped_count = fields.Integer(readonly=True)
    unmapped_count = fields.Integer(readonly=True)
    conflict_count = fields.Integer(readonly=True)
    result_summary = fields.Text(readonly=True)

    def _set_result(self, result, state):
        self.ensure_one()
        summary = (
            'Total: %(total)s\n'
            'Would change / changed: %(changed)s\n'
            'Mapped: %(mapped)s\n'
            'Unmapped: %(unmapped)s\n'
            'Conflicts: %(conflicts)s'
        ) % result
        self.write({
            'state': state,
            'total_count': result['total'],
            'changed_count': result['changed'],
            'mapped_count': result['mapped'],
            'unmapped_count': result['unmapped'],
            'conflict_count': result['conflicts'],
            'result_summary': summary,
        })

    def action_preview(self):
        self.ensure_one()
        result = self.env['bank.sms.transaction']._backfill_counterparty_mappings(
            dry_run=True
        )
        self._set_result(result, 'preview')
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_apply(self):
        self.ensure_one()
        preview = self.env['bank.sms.transaction']._backfill_counterparty_mappings(
            dry_run=True
        )
        if preview['conflicts']:
            self._set_result(preview, 'preview')
            return {
                'type': 'ir.actions.act_window',
                'res_model': self._name,
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'new',
            }
        result = self.env['bank.sms.transaction']._backfill_counterparty_mappings(
            dry_run=False
        )
        self._set_result(result, 'done')
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
