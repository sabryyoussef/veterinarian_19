# -*- coding: utf-8 -*-
from odoo import fields, models


class PetBillingIntegrityIssue(models.Model):
    _name = 'pet.billing.integrity.issue'
    _description = 'Appointment Billing Integrity Issue'
    _order = 'severity desc, id desc'
    _rec_name = 'name'

    name = fields.Char(required=True)
    appointment_id = fields.Many2one('pet.appointment', index=True, ondelete='cascade')
    issue_type = fields.Selection([
        ('multi_primary_invoice', 'Multiple Primary Invoices'),
        ('draft_with_payment', 'Draft Invoice With Posted Payment'),
        ('overpayment', 'Payments Exceed Invoiced'),
        ('status_mismatch', 'Payment Status Mismatch'),
        ('so_invoice_mismatch', 'Sale Order / Invoice Total Mismatch'),
        ('orphan_invoice_line', 'Orphan Invoice Line'),
        ('orphan_invoice', 'Orphan Invoice Without Appointment'),
        ('pointer_mismatch', 'Invoice Pointer Mismatch'),
        ('unreconciled_credit', 'Unreconciled Appointment Credit'),
        ('duplicate_service_source', 'Duplicate Service Source'),
        ('confirmed_uninvoiced', 'Confirmed SO Not Invoiceable'),
    ], required=True, index=True)
    classification = fields.Selection([
        ('confirmed_duplicate_invoice', 'Confirmed Duplicate Invoice'),
        ('incomplete_so_sync', 'Incomplete Sale Order / Service Sync'),
        ('replaced_so_content', 'Incomplete or Replaced Sale Order Content'),
        ('other', 'Other'),
    ], string='Business Classification', index=True,
       help='Commercial classification used in integrity reports.')
    severity = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ], default='medium', required=True)
    details = fields.Text()
    state = fields.Selection([
        ('open', 'Open'),
        ('reviewed', 'Reviewed'),
        ('resolved', 'Resolved'),
    ], default='open', required=True, index=True)
    detected_at = fields.Datetime(default=fields.Datetime.now, required=True)

    def action_mark_reviewed(self):
        self.write({'state': 'reviewed'})

    def action_mark_resolved(self):
        self.write({'state': 'resolved'})

    def action_scan_all(self):
        return self.env['pet.appointment'].sudo()._scan_billing_integrity_issues()
