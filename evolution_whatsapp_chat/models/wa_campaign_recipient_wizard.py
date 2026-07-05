# -*- coding: utf-8 -*-
"""
Campaign Recipient Selection Wizard
"""
from odoo import models, fields, api
from odoo.exceptions import UserError


class WACampaignRecipientWizard(models.TransientModel):
    _name = 'wa.campaign.recipient.wizard'
    _description = 'Select Campaign Recipients'

    campaign_id = fields.Many2one(
        'wa.campaign', string='Campaign', required=True
    )

    target_model = fields.Selection([
        ('res.partner', 'Contacts'),
        ('crm.lead', 'CRM Leads'),
    ], string='Target', required=True)

    # ── Manual Selection ──────────────────────────────────────────────────────

    partner_ids = fields.Many2many(
        'res.partner', 'wa_campaign_recipient_wizard_partner_rel',
        'wizard_id', 'partner_id', string='Select Contacts'
    )

    lead_ids = fields.Many2many(
        'crm.lead', 'wa_campaign_recipient_wizard_lead_rel',
        'wizard_id', 'lead_id', string='Select Leads'
    )

    # ── Domain Filter ─────────────────────────────────────────────────────────

    use_domain = fields.Boolean(
        string='Use Filter', default=False,
        help='Apply domain filter for automatic selection'
    )

    filter_domain = fields.Char(
        string='Domain Filter',
        help='e.g., [("country_id.code", "=", "EG"), ("active", "=", True)]'
    )

    # ── Preview ───────────────────────────────────────────────────────────────

    preview_count = fields.Integer(
        string='Will Add', compute='_compute_preview_count'
    )

    @api.depends('partner_ids', 'lead_ids', 'use_domain', 'filter_domain', 'target_model')
    def _compute_preview_count(self):
        for wiz in self:
            count = 0
            if wiz.target_model == 'res.partner':
                if wiz.use_domain and wiz.filter_domain:
                    try:
                        domain = eval(wiz.filter_domain)
                        count = self.env['res.partner'].search_count(domain)
                    except:
                        count = 0
                else:
                    count = len(wiz.partner_ids)
            elif wiz.target_model == 'crm.lead':
                if wiz.use_domain and wiz.filter_domain:
                    try:
                        domain = eval(wiz.filter_domain)
                        count = self.env['crm.lead'].search_count(domain)
                    except:
                        count = 0
                else:
                    count = len(wiz.lead_ids)
            wiz.preview_count = count

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_add_recipients(self):
        """Add selected recipients to campaign."""
        self.ensure_one()

        if not self.preview_count:
            raise UserError("No recipients selected.")

        # Update campaign
        vals = {'target_model': self.target_model}
        
        if self.target_model == 'res.partner':
            if self.use_domain and self.filter_domain:
                vals['filter_domain'] = self.filter_domain
                try:
                    domain = eval(self.filter_domain)
                    partners = self.env['res.partner'].search(domain)
                    vals['partner_ids'] = [(6, 0, partners.ids)]
                except Exception as e:
                    raise UserError(f"Invalid domain filter: {e}")
            else:
                vals['partner_ids'] = [(6, 0, self.partner_ids.ids)]
                vals['filter_domain'] = False

        elif self.target_model == 'crm.lead':
            if self.use_domain and self.filter_domain:
                vals['filter_domain'] = self.filter_domain
                try:
                    domain = eval(self.filter_domain)
                    leads = self.env['crm.lead'].search(domain)
                    vals['lead_ids'] = [(6, 0, leads.ids)]
                except Exception as e:
                    raise UserError(f"Invalid domain filter: {e}")
            else:
                vals['lead_ids'] = [(6, 0, self.lead_ids.ids)]
                vals['filter_domain'] = False

        self.campaign_id.write(vals)

        # Auto-generate lines
        self.campaign_id.action_generate_lines()

        return {'type': 'ir.actions.act_window_close'}
