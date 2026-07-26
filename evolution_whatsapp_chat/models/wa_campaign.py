# -*- coding: utf-8 -*-
"""
WhatsApp Campaign Management

Persistent campaigns with full status tracking, anti-duplicate logic,
and comprehensive reporting.
"""
import logging
from datetime import datetime, timedelta
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class WhatsAppCampaign(models.Model):
    _name = 'wa.campaign'
    _description = 'WA Campaign'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    # ── Basic Info ────────────────────────────────────────────────────────────

    name = fields.Char(
        string='Campaign Name', required=True, tracking=True,
        help='Internal name for this campaign'
    )

    description = fields.Text(
        string='Description',
        help='Purpose and details of this campaign'
    )

    state = fields.Selection([
        ('draft',     'Draft'),
        ('scheduled', 'Scheduled'),
        ('running',   'Running'),
        ('paused',    'Paused'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)

    # Phase 5A: Hub routing mode (default legacy — no behavior change until P5B+)
    wa_outbound_mode = fields.Selection(
        [
            ('legacy', 'Legacy'),
            ('shadow', 'Shadow (compare only)'),
            ('hub', 'Hub Unified'),
        ],
        string='WA Outbound Mode',
        default='legacy',
        required=True,
        tracking=True,
        help='Phase 5: Hub cutover routing. Default legacy. Hub mode requires '
             'global/instance Campaign cutover flags + allowlist. Media '
             'attachments force legacy until Hub media support.',
    )

    # P5E/P5F-A Campaign Hub Ops helpers (computed)
    wa_hub_allowlisted = fields.Boolean(
        string='Hub Allowlisted',
        compute='_compute_wa_hub_ops',
    )
    wa_hub_active_authorization = fields.Boolean(
        string='Hub Active Authorization',
        compute='_compute_wa_hub_ops',
        help='Allowlisted and admission-capable (not completed/cancelled)',
    )
    wa_hub_historical = fields.Boolean(
        string='Historical Hub Usage',
        compute='_compute_wa_hub_ops',
    )
    wa_hub_requires_allowlist_cleanup = fields.Boolean(
        string='Allowlist Cleanup Needed',
        compute='_compute_wa_hub_ops',
    )
    wa_hub_render_ready = fields.Boolean(
        string='Render Freeze Ready',
        compute='_compute_wa_hub_ops',
        help='All pending lines are frozen (or no pending lines)',
    )
    wa_hub_locked_line_count = fields.Integer(
        string='Frozen Lines',
        compute='_compute_wa_hub_ops',
    )
    wa_hub_unlocked_line_count = fields.Integer(
        string='Unlocked Pending Lines',
        compute='_compute_wa_hub_ops',
    )
    wa_hub_eligibility_reason = fields.Char(
        string='Eligibility Reason',
        compute='_compute_wa_hub_ops',
    )
    wa_hub_instance_name = fields.Char(
        string='Hub Instance',
        compute='_compute_wa_hub_ops',
    )
    wa_hub_job_count = fields.Integer(
        string='Hub Jobs',
        compute='_compute_wa_hub_ops',
    )
    wa_hub_pending_count = fields.Integer(
        string='Pending Hub Jobs',
        compute='_compute_wa_hub_ops',
    )
    wa_hub_failed_count = fields.Integer(
        string='Failed Hub Jobs',
        compute='_compute_wa_hub_ops',
    )
    wa_hub_last_outbound_at = fields.Datetime(
        string='Last Hub Outbound',
        compute='_compute_wa_hub_ops',
    )
    wa_hub_max_retry_count = fields.Integer(
        string='Max Hub Retry',
        compute='_compute_wa_hub_ops',
    )
    wa_hub_legacy_leakage_count = fields.Integer(
        string='Legacy Leakage',
        compute='_compute_wa_hub_ops',
    )
    wa_hub_health_warning = fields.Char(
        string='Ops Warning',
        compute='_compute_wa_hub_ops',
    )
    wa_hub_render_warning = fields.Char(
        string='Render Warning',
        compute='_compute_wa_hub_ops',
    )
    wa_hub_eligible = fields.Boolean(
        string='Hub Eligible',
        compute='_compute_wa_hub_ops',
        help='P5F: text-only immediate Campaign eligible for Hub approval',
    )
    wa_hub_scheduled_warning = fields.Char(
        string='Scheduled Hub Warning',
        compute='_compute_wa_hub_ops',
    )

    def _compute_wa_hub_ops(self):
        Out = self.env['whatsapp.outbound.message'].sudo()
        Log = self.env['wa.message.log'].sudo() if 'wa.message.log' in self.env else None
        Routing = self.env['whatsapp.campaign.hub.routing']
        allow_set = set(Routing.get_allowlist_ids())
        for camp in self:
            camp.wa_hub_allowlisted = camp.id in allow_set
            admission_capable = Routing.campaign_is_admission_capable(camp)
            camp.wa_hub_active_authorization = bool(
                camp.wa_hub_allowlisted and camp.state not in ('completed', 'cancelled')
            )
            try:
                inst = Routing.resolve_hub_instance()
                camp.wa_hub_instance_name = inst.instance_name if inst else False
            except Exception:
                camp.wa_hub_instance_name = False
            jobs = Out.search(
                [
                    ('campaign_id', '=', camp.id),
                    ('purpose', '=', 'campaign'),
                    ('transport_mode', '=', 'unified_bridge'),
                ],
                order='id desc',
                limit=500,
            )
            camp.wa_hub_job_count = len(jobs)
            pending = jobs.filtered(lambda j: j.state in ('pending', 'processing'))
            failed = jobs.filtered(lambda j: j.state == 'failed')
            camp.wa_hub_pending_count = len(pending)
            camp.wa_hub_failed_count = len(failed)
            last = jobs[:1]
            camp.wa_hub_last_outbound_at = (
                (last.sent_at or last.create_date) if last else False
            )
            camp.wa_hub_max_retry_count = max(jobs.mapped('retry_count') or [0])
            camp.wa_hub_historical = bool(
                jobs
                or camp.campaign_line_ids.filtered(
                    lambda l: l.hub_outbound_id or l.hub_message_id
                )
            )
            camp.wa_hub_requires_allowlist_cleanup = bool(
                camp.wa_hub_allowlisted
                and camp.state in ('completed', 'cancelled')
            )
            lines = camp.campaign_line_ids
            locked = lines.filtered(lambda l: l.rendered_locked)
            unlocked_pending = lines.filtered(
                lambda l: l.status == 'pending' and not l.rendered_locked
            )
            camp.wa_hub_locked_line_count = len(locked)
            camp.wa_hub_unlocked_line_count = len(unlocked_pending)
            pending_lines = lines.filtered(lambda l: l.status == 'pending')
            camp.wa_hub_render_ready = (
                not pending_lines
                or all(l.rendered_locked for l in pending_lines)
            )
            assess = Routing.service_assess_hub_eligibility(camp)
            camp.wa_hub_eligible = bool(assess.get('eligible'))
            camp.wa_hub_eligibility_reason = assess.get('reason') or False
            leakage = 0
            if Log and camp.wa_outbound_mode == 'hub':
                leakage = Log.search_count(
                    [
                        ('campaign_id', '=', camp.id),
                        ('send_origin', '=', 'legacy'),
                    ]
                )
            camp.wa_hub_legacy_leakage_count = leakage
            if (
                camp.wa_outbound_mode == 'hub'
                and (
                    camp.send_mode == 'scheduled'
                    or camp.state == 'scheduled'
                    or (camp.send_mode == 'queue' and camp.scheduled_date)
                )
            ):
                camp.wa_hub_scheduled_warning = (
                    'Scheduled time is not enforced by the current Hub Campaign path.'
                )
            else:
                camp.wa_hub_scheduled_warning = False
            render_warn = False
            if camp.wa_outbound_mode == 'hub' and unlocked_pending:
                render_warn = f'{len(unlocked_pending)} pending line(s) not frozen'
            if assess.get('reason') == 'attachments_media':
                render_warn = (render_warn + '; ' if render_warn else '') + (
                    'Not Hub eligible: attachments/media'
                )
            camp.wa_hub_render_warning = render_warn or False
            warns = []
            if admission_capable and not camp.wa_hub_allowlisted:
                warns.append('active hub not allowlisted')
            if camp.wa_hub_requires_allowlist_cleanup:
                warns.append('completed still allowlisted — cleanup')
            if camp.wa_hub_allowlisted and camp.wa_outbound_mode != 'hub':
                warns.append('allowlisted but not hub')
            if camp.wa_hub_allowlisted and not camp.wa_hub_eligible and camp.state not in (
                'completed',
                'cancelled',
            ):
                warns.append(f"allowlisted but ineligible ({camp.wa_hub_eligibility_reason})")
            if camp.wa_hub_pending_count:
                warns.append(f'pending={camp.wa_hub_pending_count}')
            if camp.wa_hub_failed_count:
                warns.append(f'failed={camp.wa_hub_failed_count}')
            if camp.wa_hub_legacy_leakage_count and camp.wa_outbound_mode == 'hub':
                warns.append(f'legacy_leak={camp.wa_hub_legacy_leakage_count}')
            if camp.wa_hub_scheduled_warning:
                warns.append('scheduled not on Hub')
            if camp.wa_hub_render_warning:
                warns.append(camp.wa_hub_render_warning)
            if pending_lines and camp.wa_hub_unlocked_line_count:
                warns.append(
                    f'{camp.wa_hub_locked_line_count} locked / '
                    f'{camp.wa_hub_unlocked_line_count} unlocked'
                )
            camp.wa_hub_health_warning = '; '.join(warns) if warns else False

    def action_hub_approve_for_allowlist(self):
        """Admin: add Campaign to Hub allowlist after eligibility checks (does not flip mode)."""
        self.ensure_one()
        Routing = self.env['whatsapp.campaign.hub.routing']
        assess = Routing.service_assess_hub_eligibility(self)
        if not assess.get('eligible'):
            raise UserError(
                "Campaign is not Hub-eligible for approval: %s%s"
                % (
                    assess.get('reason'),
                    (' — ' + '; '.join(assess.get('details') or []))
                    if assess.get('details')
                    else '',
                )
            )
        result = Routing.service_allowlist_add(self.id)
        self.message_post(
            body=(
                f"Hub approval: Campaign {self.id} added to "
                f"campaign_hub_allowed_campaign_ids. Mode not changed "
                f"(still {self.wa_outbound_mode}). Flip to hub last."
            )
        )
        self.invalidate_recordset()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Hub Approve',
                'message': f"Allowlist now: {result.get('allowlist')}",
                'type': 'success',
                'sticky': False,
            },
        }

    def action_hub_revoke_allowlist(self):
        """Admin: remove Campaign from Hub allowlist (preserves Hub history)."""
        self.ensure_one()
        Out = self.env['whatsapp.outbound.message'].sudo()
        incomplete = Out.search_count(
            [
                ('campaign_id', '=', self.id),
                ('purpose', '=', 'campaign'),
                ('transport_mode', '=', 'unified_bridge'),
                ('state', 'in', ('pending', 'processing')),
            ]
        )
        if incomplete:
            raise UserError(
                "Cannot revoke Hub approval while %s incomplete Hub job(s) exist. "
                "Quarantine incomplete Campaign Hub jobs first."
                % incomplete
            )
        Routing = self.env['whatsapp.campaign.hub.routing']
        result = Routing.service_allowlist_remove(self.id)
        self.message_post(
            body=(
                f"Hub approval revoked: Campaign {self.id} removed from allowlist. "
                f"Historical Hub messages/jobs preserved."
            )
        )
        self.invalidate_recordset()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Hub Revoke',
                'message': f"Allowlist now: {result.get('allowlist') or '(empty)'}",
                'type': 'warning',
                'sticky': False,
            },
        }

    def action_hub_cleanup_completed_allowlist(self):
        """Admin: remove completed/cancelled Campaign from Hub allowlist."""
        self.ensure_one()
        if self.state not in ('completed', 'cancelled'):
            raise UserError(
                "Cleanup applies only to completed/cancelled Campaigns "
                "(or revoke approval for active Campaigns)."
            )
        return self.action_hub_revoke_allowlist()

    def action_freeze_campaign_lines_for_hub(self):
        """Freeze unlocked lines for Hub (idempotent for already locked)."""
        self.ensure_one()
        frozen = already = skipped = invalid = 0
        for line in self.campaign_line_ids:
            if line.status in ('sent', 'delivered', 'read', 'skipped'):
                skipped += 1
                continue
            if not (line.phone or '').strip():
                invalid += 1
                continue
            if line.rendered_locked and line.rendered_body_hash:
                already += 1
                continue
            try:
                line.service_freeze_rendered_body()
                frozen += 1
            except Exception:
                invalid += 1
        self.invalidate_recordset()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Freeze Campaign Lines',
                'message': (
                    f"frozen={frozen} already={already} "
                    f"skipped={skipped} invalid={invalid}"
                ),
                'type': 'success' if invalid == 0 else 'warning',
                'sticky': False,
            },
        }

    def action_quarantine_campaign_hub(self):
        """Admin: quarantine incomplete Hub Campaign jobs for this campaign."""
        self.ensure_one()
        Out = self.env['whatsapp.outbound.message'].sudo()
        result = Out.service_quarantine_campaign(
            self.id, reason=f'Ops quarantine Campaign {self.id}'
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Campaign Quarantine',
                'message': (
                    f"found={result.get('jobs_found')} "
                    f"cancelled={result.get('cancelled')} "
                    f"already_sent={result.get('already_sent')} "
                    f"uncertain={result.get('uncertain')}"
                ),
                'type': 'warning',
                'sticky': False,
            },
        }

    def action_open_hub_outbound_jobs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Campaign Hub Outbound',
            'res_model': 'whatsapp.outbound.message',
            'view_mode': 'list,form',
            'domain': [
                ('campaign_id', '=', self.id),
                ('purpose', '=', 'campaign'),
            ],
        }

    def action_open_hub_messages(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Campaign Hub Messages',
            'res_model': 'whatsapp.message',
            'view_mode': 'list,form',
            'domain': [('campaign_id', '=', self.id)],
        }

    def action_open_campaign_shadow(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Campaign Shadow',
            'res_model': 'whatsapp.campaign.shadow',
            'view_mode': 'list,form',
            'domain': [('campaign_id', '=', self.id)],
        }

    # ── Message Template ──────────────────────────────────────────────────────

    template_id = fields.Many2one(
        'evo.wa.template', string='Message Template',
        domain=[('active', '=', True)],
        help='Select a template to use'
    )

    message = fields.Text(
        string='Message Content', required=True, tracking=True,
        help='Use placeholders: {name}, {first}, {company}, {phone}'
    )

    personalise = fields.Boolean(
        string='Personalise per Contact', default=True,
        help='Replace placeholders with contact-specific values'
    )

    attachment_ids = fields.Many2many(
        'ir.attachment', 'wa_campaign_attachment_rel',
        'campaign_id', 'attachment_id',
        string='Attachments',
        help='Media files to send with each message'
    )

    # ── Recipients ────────────────────────────────────────────────────────────

    campaign_line_ids = fields.One2many(
        'wa.campaign.line', 'campaign_id',
        string='Campaign Recipients'
    )

    # ── Targeting ─────────────────────────────────────────────────────────────

    target_model = fields.Selection([
        ('res.partner', 'Contacts'),
        ('crm.lead',    'CRM Leads'),
    ], string='Target', default='res.partner', required=True)

    partner_ids = fields.Many2many(
        'res.partner', 'wa_campaign_partner_rel',
        'campaign_id', 'partner_id',
        string='Selected Contacts'
    )

    lead_ids = fields.Many2many(
        'crm.lead', 'wa_campaign_lead_rel',
        'campaign_id', 'lead_id',
        string='Selected Leads'
    )

    filter_domain = fields.Char(
        string='Filter Domain',
        help='Optional domain filter for automatic contact selection'
    )

    # ── Scheduling ────────────────────────────────────────────────────────────

    send_mode = fields.Selection([
        ('immediate', 'Send Immediately'),
        ('scheduled', 'Schedule for Specific Time'),
        ('queue',     'Add to Queue (Rate Limited)'),
    ], string='Send Mode', default='queue', required=True)

    scheduled_date = fields.Datetime(
        string='Scheduled Send Time',
        help='When to start sending messages'
    )

    delay_between = fields.Integer(
        string='Delay Between Messages (seconds)',
        default=5,
        help='Seconds between each message to avoid rate limits'
    )

    # ── Anti-Duplicate Settings ───────────────────────────────────────────────

    check_duplicates = fields.Boolean(
        string='Prevent Duplicate Sends', default=True,
        help='Skip contacts who already received this campaign'
    )

    min_days_between = fields.Integer(
        string='Minimum Days Between Campaigns',
        default=0,
        help='Skip contacts contacted in last X days (0 = no check)'
    )

    # ── Statistics (computed) ─────────────────────────────────────────────────

    total_count = fields.Integer(
        string='Total Recipients', compute='_compute_stats', store=True
    )
    pending_count = fields.Integer(
        string='Pending', compute='_compute_stats', store=True
    )
    sent_count = fields.Integer(
        string='Sent', compute='_compute_stats', store=True
    )
    delivered_count = fields.Integer(
        string='Delivered', compute='_compute_stats', store=True
    )
    read_count = fields.Integer(
        string='Read', compute='_compute_stats', store=True
    )
    failed_count = fields.Integer(
        string='Failed', compute='_compute_stats', store=True
    )
    skipped_count = fields.Integer(
        string='Skipped', compute='_compute_stats', store=True
    )

    success_rate = fields.Float(
        string='Success Rate (%)', compute='_compute_stats', store=True
    )
    read_rate = fields.Float(
        string='Read Rate (%)', compute='_compute_stats', store=True
    )

    # ── Dates ─────────────────────────────────────────────────────────────────

    start_date = fields.Datetime(
        string='Started At', readonly=True, tracking=True
    )
    completed_date = fields.Datetime(
        string='Completed At', readonly=True, tracking=True
    )

    # ── Progress ──────────────────────────────────────────────────────────────

    progress = fields.Float(
        string='Progress (%)', compute='_compute_progress'
    )

    @api.depends('campaign_line_ids.status')
    def _compute_stats(self):
        for campaign in self:
            lines = campaign.campaign_line_ids
            campaign.total_count     = len(lines)
            campaign.pending_count   = len(lines.filtered(lambda l: l.status == 'pending'))
            campaign.sent_count      = len(lines.filtered(lambda l: l.status in ['sent', 'delivered', 'read']))
            campaign.delivered_count = len(lines.filtered(lambda l: l.status in ['delivered', 'read']))
            campaign.read_count      = len(lines.filtered(lambda l: l.status == 'read'))
            campaign.failed_count    = len(lines.filtered(lambda l: l.status == 'failed'))
            campaign.skipped_count   = len(lines.filtered(lambda l: l.status == 'skipped'))

            if campaign.total_count > 0:
                campaign.success_rate = (campaign.sent_count / campaign.total_count) * 100
                campaign.read_rate = (campaign.read_count / campaign.sent_count * 100) if campaign.sent_count > 0 else 0
            else:
                campaign.success_rate = 0
                campaign.read_rate = 0

    @api.depends('total_count', 'sent_count', 'failed_count', 'skipped_count')
    def _compute_progress(self):
        for campaign in self:
            processed = campaign.sent_count + campaign.failed_count + campaign.skipped_count
            campaign.progress = (processed / campaign.total_count * 100) if campaign.total_count > 0 else 0

    # ── Template auto-fill ────────────────────────────────────────────────────

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if self.template_id:
            self.message = self.template_id.body or ''

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_load_recipients(self):
        """Open wizard to select recipients."""
        self.ensure_one()
        return {
            'name': 'Select Recipients',
            'type': 'ir.actions.act_window',
            'res_model': 'wa.campaign.recipient.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_campaign_id': self.id,
                'default_target_model': self.target_model,
            }
        }

    def action_generate_lines(self):
        """Generate campaign lines from selected contacts/leads."""
        self.ensure_one()
        if self.state not in ['draft', 'scheduled']:
            raise UserError("Can only generate lines for draft or scheduled campaigns.")

        # Clear existing lines
        self.campaign_line_ids.unlink()

        lines = []
        from .res_partner import _normalise_phone

        if self.target_model == 'res.partner':
            contacts = self.partner_ids
            # Apply domain filter if provided
            if self.filter_domain:
                try:
                    domain = eval(self.filter_domain)
                    contacts = contacts.filtered_domain(domain)
                except Exception as e:
                    _logger.warning(f"Invalid domain filter: {e}")

            for partner in contacts:
                phone = _normalise_phone(getattr(partner, 'mobile', None) or partner.phone or '')
                if not phone and self.check_duplicates:
                    continue  # Skip contacts without phone

                # Check if already sent
                if self.check_duplicates:
                    if self._already_sent_to_partner(partner):
                        lines.append((0, 0, {
                            'partner_id': partner.id,
                            'phone': phone,
                            'status': 'skipped',
                            'error_msg': 'Already received this campaign',
                        }))
                        continue

                # Check minimum days between campaigns
                if self.min_days_between > 0:
                    if self._contacted_recently(partner):
                        lines.append((0, 0, {
                            'partner_id': partner.id,
                            'phone': phone,
                            'status': 'skipped',
                            'error_msg': f'Contacted in last {self.min_days_between} days',
                        }))
                        continue

                lines.append((0, 0, {
                    'partner_id': partner.id,
                    'phone': phone,
                    'status': 'pending',
                }))

        elif self.target_model == 'crm.lead':
            leads = self.lead_ids
            if self.filter_domain:
                try:
                    domain = eval(self.filter_domain)
                    leads = leads.filtered_domain(domain)
                except Exception as e:
                    _logger.warning(f"Invalid domain filter: {e}")

            for lead in leads:
                partner = lead.partner_id
                phone = _normalise_phone(
                    lead.phone or lead.mobile or
                    (getattr(partner, 'mobile', None) or partner.phone if partner else '')
                    or ''
                )
                if not phone and self.check_duplicates:
                    continue

                # Check duplicates
                if self.check_duplicates:
                    if self._already_sent_to_lead(lead):
                        lines.append((0, 0, {
                            'lead_id': lead.id,
                            'partner_id': partner.id if partner else False,
                            'phone': phone,
                            'status': 'skipped',
                            'error_msg': 'Already received this campaign',
                        }))
                        continue

                # Check recent contact
                if self.min_days_between > 0 and partner:
                    if self._contacted_recently(partner):
                        lines.append((0, 0, {
                            'lead_id': lead.id,
                            'partner_id': partner.id,
                            'phone': phone,
                            'status': 'skipped',
                            'error_msg': f'Contacted in last {self.min_days_between} days',
                        }))
                        continue

                lines.append((0, 0, {
                    'lead_id': lead.id,
                    'partner_id': partner.id if partner else False,
                    'phone': phone,
                    'status': 'pending',
                }))

        self.campaign_line_ids = lines
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': f'{len(lines)} recipients loaded successfully',
                'type': 'success',
                'sticky': False,
            }
        }

    def _already_sent_to_partner(self, partner):
        """Check if this partner already received this campaign."""
        return self.env['wa.campaign.line'].search_count([
            ('campaign_id', '=', self.id),
            ('partner_id', '=', partner.id),
            ('status', 'in', ['sent', 'delivered', 'read']),
        ]) > 0

    def _already_sent_to_lead(self, lead):
        """Check if this lead already received this campaign."""
        return self.env['wa.campaign.line'].search_count([
            ('campaign_id', '=', self.id),
            ('lead_id', '=', lead.id),
            ('status', 'in', ['sent', 'delivered', 'read']),
        ]) > 0

    def _contacted_recently(self, partner):
        """Check if partner was contacted in last X days."""
        if self.min_days_between <= 0:
            return False
        cutoff = fields.Datetime.now() - timedelta(days=self.min_days_between)
        return self.env['wa.message.log'].search_count([
            ('partner_id', '=', partner.id),
            ('direction', '=', 'out'),
            ('create_date', '>=', cutoff),
        ]) > 0

    def action_start_campaign(self):
        """Start sending campaign messages."""
        self.ensure_one()
        if self.state not in ['draft', 'scheduled', 'paused']:
            raise UserError("Can only start draft, scheduled or paused campaigns.")

        if not self.campaign_line_ids:
            raise UserError("No recipients loaded. Use 'Load Recipients' first.")

        pending = self.campaign_line_ids.filtered(lambda l: l.status == 'pending')
        if not pending:
            raise UserError("No pending messages to send.")

        self.write({
            'state': 'running',
            'start_date': fields.Datetime.now() if not self.start_date else self.start_date,
        })

        # Process in background
        self._process_campaign_queue()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': f'Campaign started! Processing {len(pending)} messages...',
                'type': 'success',
                'sticky': False,
            }
        }

    def _process_campaign_queue(self):
        """Process pending messages in campaign.

        Branch point (P5B): routing decision → legacy | shadow | hub.
        Production flags OFF keep all Campaigns on legacy.
        """
        self.ensure_one()
        decision = self._wa_hub_routing().resolve_outbound_route(self)
        route = decision.get("route") or "legacy"
        if route == "hub":
            return self._process_campaign_queue_hub(decision)
        if route == "shadow":
            return self._process_campaign_queue_shadow()
        return self._process_campaign_queue_legacy()

    def _process_campaign_queue_legacy(self):
        """Unchanged legacy Campaign transport (immediate / bridge queue)."""
        self.ensure_one()
        from .discuss_channel import _send_via_evolution
        from .whatsapp_bulk_wizard import _send_media_evolution
        import time

        pending_lines = self.campaign_line_ids.filtered(lambda l: l.status == 'pending')

        from .discuss_channel import _evo_config
        cfg = _evo_config(self.env)
        evo_url = cfg['url']
        evo_key = cfg['key']
        evo_instance = cfg['instance_path']

        attachment_info = self._get_attachment_info()

        for line in pending_lines:
            if self.state == 'paused':
                break

            rendered = self._render_message_for_line(line)
            line.message = rendered

            if self.send_mode == 'immediate':
                success, resp, wa_msg_id = _send_via_evolution(
                    self.env, line.phone, rendered,
                    partner_id=line.partner_id.id if line.partner_id else None,
                    lead_id=line.lead_id.id if line.lead_id else None,
                    campaign_id=self.id,
                    campaign_line_id=line.id,
                )
                if success:
                    line.write({
                        'status': 'sent',
                        'sent_date': fields.Datetime.now(),
                        'wa_message_id': wa_msg_id,
                    })
                    for att in attachment_info:
                        _send_media_evolution(self.env, line.phone, att, '')
                    line._post_to_chatter(rendered, 'sent')
                else:
                    line.write({
                        'status': 'failed',
                        'error_msg': resp[:200],
                    })
                if self.delay_between > 0:
                    time.sleep(self.delay_between)

            else:  # queue or scheduled
                scheduled_dt = self.scheduled_date if self.send_mode == 'scheduled' else False
                try:
                    endpoint = f"{evo_url}/message/sendText/{evo_instance}"
                    queue_rec = self.env['integration.outbound.queue'].sudo().create_outbound_message(
                        name=f"Campaign '{self.name}' → {line.phone}",
                        platform='evolution',
                        endpoint_url=endpoint,
                        payload={'number': line.phone, 'text': rendered, 'options': {'delay': 1000}},
                        headers={'apikey': evo_key, 'Content-Type': 'application/json'},
                        related_model=line.lead_id._name if line.lead_id else (line.partner_id._name if line.partner_id else ''),
                        related_res_id=line.lead_id.id if line.lead_id else (line.partner_id.id if line.partner_id else 0),
                        priority=5,
                        scheduled_at=scheduled_dt,
                    )
                    line.write({
                        'status': 'sent',
                        'sent_date': fields.Datetime.now(),
                        'queue_id': queue_rec.id,
                    })
                    for att in attachment_info:
                        self.env['integration.outbound.queue'].sudo().create_outbound_message(
                            name=f"Campaign Media → {line.phone}",
                            platform='evolution',
                            endpoint_url=f"{evo_url}/message/sendMedia/{evo_instance}",
                            payload={'number': line.phone, 'mediatype': att['type'],
                                     'media': att['url'], 'caption': att['name']},
                            headers={'apikey': evo_key, 'Content-Type': 'application/json'},
                            related_model=line.lead_id._name if line.lead_id else (line.partner_id._name if line.partner_id else ''),
                            related_res_id=line.lead_id.id if line.lead_id else (line.partner_id.id if line.partner_id else 0),
                            priority=4,
                            scheduled_at=scheduled_dt,
                        )
                except Exception as e:
                    line.write({
                        'status': 'failed',
                        'error_msg': str(e)[:200],
                    })

        if not self.campaign_line_ids.filtered(lambda l: l.status == 'pending'):
            self.write({
                'state': 'completed',
                'completed_date': fields.Datetime.now(),
            })

    def _process_campaign_queue_hub(self, decision):
        """Hub unified outbound path — no _send_via_evolution, no bridge queue."""
        self.ensure_one()
        Routing = self._wa_hub_routing()
        pending_lines = self.campaign_line_ids.filtered(lambda l: l.status == 'pending')

        if not decision.get('ok'):
            err = (decision.get('error') or 'Hub Campaign cutover not eligible')[:200]
            _logger.warning(
                "Campaign %s hub route blocked (no legacy fallback): %s",
                self.id,
                err,
            )
            pending_lines.write({'status': 'failed', 'error_msg': err})
            if not self.campaign_line_ids.filtered(lambda l: l.status == 'pending'):
                self.write({
                    'state': 'completed',
                    'completed_date': fields.Datetime.now(),
                })
            return

        batch = Routing.campaign_admit_batch_size()
        admitted = 0
        for line in pending_lines:
            if self.state == 'paused':
                break
            if admitted >= batch:
                _logger.info(
                    "Campaign %s Hub admit batch size %s reached; remaining lines stay pending",
                    self.id,
                    batch,
                )
                break

            # Already Hub-linked: project/sync only (idempotent), do not re-admit under batch
            if line.hub_outbound_id or line.hub_message_id:
                Out = self.env['whatsapp.outbound.message'].sudo()
                job = Out.browse(line.hub_outbound_id) if line.hub_outbound_id else Out.browse()
                if job and job.exists():
                    job._project_campaign_line_from_outbound()
                else:
                    # Re-admit same business_key (idempotent Hub API) using frozen body
                    body = line.get_frozen_or_freeze_body()
                    Routing.service_admit_campaign_line(self, line, body=body)
                continue

            # P5E: freeze once from campaign.message; admit frozen body only
            body = line.get_frozen_or_freeze_body()
            res = Routing.service_admit_campaign_line(self, line, body=body)
            if res.get('backpressure'):
                _logger.info(
                    "Campaign %s Hub backpressure: %s",
                    self.id,
                    res.get('error'),
                )
                break
            if not res.get('ok'):
                line.write({
                    'status': 'failed',
                    'error_msg': (res.get('error') or 'Hub admission failed')[:200],
                })
                continue
            admitted += 1
            # Line stays pending until Hub provider acceptance projects sent

        # Complete only when no pending remain (Hub jobs may still be in flight)
        if not self.campaign_line_ids.filtered(lambda l: l.status == 'pending'):
            self.write({
                'state': 'completed',
                'completed_date': fields.Datetime.now(),
            })

    def _process_campaign_queue_shadow(self):
        """
        P5C: observational shadow — preview Hub candidate, legacy send once, evidence.

        Never Hub-sends. Replay guard: skip transport if legacy_send_completed shadow exists.
        """
        self.ensure_one()
        Routing = self._wa_hub_routing()
        Shadow = self.env['whatsapp.campaign.shadow'].sudo()
        pending_lines = self.campaign_line_ids.filtered(lambda l: l.status == 'pending')
        Out = self.env['whatsapp.outbound.message'].sudo()
        camp_jobs_before = Out.search_count([('purpose', '=', 'campaign')])

        for line in pending_lines:
            if self.state == 'paused':
                break

            # Replay guard — do not duplicate provider send
            prior = Shadow.find_completed_for_line(line.id)
            if prior:
                _logger.info(
                    "Campaign %s line %s shadow replay skipped (legacy_send_completed)",
                    self.id,
                    line.id,
                )
                Shadow.classify_and_record(
                    campaign=self,
                    line=line,
                    preview=Routing.service_preview_campaign_line(self, line),
                    legacy_transport=prior.legacy_transport or 'none',
                    wa_log=self.env['wa.message.log'].sudo().browse(
                        prior.wa_message_log_id
                    ) if prior.wa_message_log_id else None,
                    mirrored_message=prior.mirrored_message_id,
                    legacy_provider_message_id=prior.legacy_provider_message_id,
                    legacy_queue_id=prior.legacy_queue_id,
                    legacy_send_ok=True,
                    force_classification='replay_skipped',
                    notes='Replay guard: legacy already sent for this line',
                )
                # Keep line non-pending so campaign can complete
                if line.status == 'pending':
                    line.write({
                        'status': 'sent' if prior.legacy_provider_message_id or prior.legacy_queue_id else 'skipped',
                        'wa_message_id': prior.legacy_provider_message_id or line.wa_message_id,
                        'sent_date': line.sent_date or fields.Datetime.now(),
                        'error_msg': False,
                    })
                continue

            # P5E: freeze once; preview + legacy send share the same frozen body
            rendered = line.get_frozen_or_freeze_body()
            preview = Routing.service_preview_campaign_line(self, line, body=rendered)

            # Attachments: still run legacy for observational honesty if campaign has media,
            # but classify has_attachments. Spec: no Hub transport; legacy preserved.
            legacy_transport = (
                'immediate' if self.send_mode == 'immediate' else 'bridge_queue'
            )
            notes = None
            if self.send_mode != 'immediate':
                notes = (
                    'queue/scheduled shadow: bridge enqueue evidence only; '
                    'provider acceptance is asynchronous'
                )

            send_result = self._shadow_legacy_send_one_line(line, rendered)
            wa_log = False
            if 'wa.message.log' in self.env:
                wa_log = self.env['wa.message.log'].sudo().search(
                    [('campaign_line_id', '=', line.id)],
                    order='id desc',
                    limit=1,
                )
            mirrored = False
            if wa_log and wa_log.hub_message_id:
                mirrored = wa_log.hub_message_id
            elif wa_log:
                # Observational mirror may run on create; re-read
                wa_log.invalidate_recordset()
                mirrored = wa_log.hub_message_id or False

            force = None
            if not preview.get('eligible'):
                force = preview.get('classification') or 'has_attachments'

            Shadow.classify_and_record(
                campaign=self,
                line=line,
                preview=preview,
                legacy_transport=legacy_transport,
                wa_log=wa_log or None,
                mirrored_message=mirrored or None,
                legacy_provider_message_id=send_result.get('wa_message_id')
                or (wa_log.wa_message_id if wa_log else False),
                legacy_queue_id=send_result.get('queue_id') or (line.queue_id.id if line.queue_id else False),
                legacy_send_ok=bool(send_result.get('ok')),
                force_classification=force,
                notes=notes,
            )

        camp_jobs_after = Out.search_count([('purpose', '=', 'campaign')])
        if camp_jobs_after != camp_jobs_before:
            _logger.error(
                "Campaign %s shadow created Hub campaign jobs (delta=%s) — unexpected",
                self.id,
                camp_jobs_after - camp_jobs_before,
            )

        if not self.campaign_line_ids.filtered(lambda l: l.status == 'pending'):
            self.write({
                'state': 'completed',
                'completed_date': fields.Datetime.now(),
            })

    def _shadow_legacy_send_one_line(self, line, rendered):
        """Legacy transport for one line (shadow only). Returns {ok, wa_message_id, queue_id}."""
        from .discuss_channel import _send_via_evolution, _evo_config
        from .whatsapp_bulk_wizard import _send_media_evolution
        import time

        result = {'ok': False, 'wa_message_id': False, 'queue_id': False}
        attachment_info = self._get_attachment_info()
        if self.send_mode == 'immediate':
            success, resp, wa_msg_id = _send_via_evolution(
                self.env, line.phone, rendered,
                partner_id=line.partner_id.id if line.partner_id else None,
                lead_id=line.lead_id.id if line.lead_id else None,
                campaign_id=self.id,
                campaign_line_id=line.id,
            )
            if success:
                line.write({
                    'status': 'sent',
                    'sent_date': fields.Datetime.now(),
                    'wa_message_id': wa_msg_id,
                })
                for att in attachment_info:
                    _send_media_evolution(self.env, line.phone, att, '')
                line._post_to_chatter(rendered, 'sent')
                result.update({'ok': True, 'wa_message_id': wa_msg_id})
            else:
                line.write({'status': 'failed', 'error_msg': (resp or '')[:200]})
            if self.delay_between > 0:
                time.sleep(self.delay_between)
            return result

        cfg = _evo_config(self.env)
        scheduled_dt = self.scheduled_date if self.send_mode == 'scheduled' else False
        try:
            queue_rec = self.env['integration.outbound.queue'].sudo().create_outbound_message(
                name=f"Campaign '{self.name}' → {line.phone}",
                platform='evolution',
                endpoint_url=f"{cfg['url']}/message/sendText/{cfg['instance_path']}",
                payload={'number': line.phone, 'text': rendered, 'options': {'delay': 1000}},
                headers={'apikey': cfg['key'], 'Content-Type': 'application/json'},
                related_model=line.lead_id._name if line.lead_id else (line.partner_id._name if line.partner_id else ''),
                related_res_id=line.lead_id.id if line.lead_id else (line.partner_id.id if line.partner_id else 0),
                priority=5,
                scheduled_at=scheduled_dt,
            )
            line.write({
                'status': 'sent',
                'sent_date': fields.Datetime.now(),
                'queue_id': queue_rec.id,
            })
            result.update({'ok': True, 'queue_id': queue_rec.id})
        except Exception as e:
            line.write({'status': 'failed', 'error_msg': str(e)[:200]})
        return result

    def _render_message_for_line(self, line):
        """Render message with personalisation for a campaign line."""
        body = self.message or ''
        if not self.personalise:
            return body

        contact_name = ''
        company_name = ''
        if line.lead_id:
            contact_name = line.lead_id.partner_name or (line.partner_id.name if line.partner_id else '') or ''
            company_name = line.lead_id.partner_id.company_name if line.lead_id.partner_id else ''
        elif line.partner_id:
            contact_name = line.partner_id.name or ''
            company_name = (
                line.partner_id.company_name
                or (line.partner_id.parent_id.name if line.partner_id.parent_id else '')
                or ''
            )

        first_name = contact_name.split()[0] if contact_name else 'there'
        phone = line.phone or ''

        body = body.replace('{name}',    contact_name or 'there')
        body = body.replace('{first}',   first_name)
        body = body.replace('{company}', company_name or 'your company')
        body = body.replace('{phone}',   phone)
        return body

    def _get_attachment_info(self):
        """Return list of {url, type, name} for Evolution API."""
        from .whatsapp_bulk_wizard import _mime_to_evo_type
        import mimetypes
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', 'http://localhost:8069')
        result = []
        for att in self.attachment_ids:
            mimetype = att.mimetype or mimetypes.guess_type(att.name or '')[0] or 'application/octet-stream'
            result.append({
                'url':  f"{base_url}/web/content/{att.id}?download=true",
                'type': _mime_to_evo_type(mimetype),
                'name': att.name or 'file',
            })
        return result

    def _wa_hub_routing(self):
        return self.env["whatsapp.campaign.hub.routing"]

    def _wa_hub_text_eligible(self):
        """Return (ok, error) — empty attachments required for Hub/shadow."""
        self.ensure_one()
        return self._wa_hub_routing().text_eligible(self)

    def _wa_hub_cutover_prerequisites(self):
        """Return (ok, error) for Hub send gate (P5B+; unused by send loop in P5A)."""
        self.ensure_one()
        return self._wa_hub_routing().hub_cutover_prerequisites(self)

    def _wa_hub_build_candidate(self, line, body=None):
        """Preview Hub candidate for a line — never sends or creates jobs."""
        self.ensure_one()
        return self._wa_hub_routing().service_preview_campaign_hub(
            self, line, body=body
        )

    def action_pause_campaign(self):
        """Pause running campaign."""
        self.ensure_one()
        if self.state != 'running':
            raise UserError("Can only pause running campaigns.")
        self.state = 'paused'

    def action_resume_campaign(self):
        """Resume paused campaign."""
        self.ensure_one()
        if self.state != 'paused':
            raise UserError("Can only resume paused campaigns.")
        self.state = 'running'
        self._process_campaign_queue()

    def action_cancel_campaign(self):
        """Cancel campaign; quarantine Hub Campaign jobs when applicable."""
        self.ensure_one()
        if self.state in ['completed', 'cancelled']:
            raise UserError("Campaign already finished.")
        self.state = 'cancelled'
        # P5B: quarantine only purpose=campaign Hub jobs for this campaign
        if (
            self.wa_outbound_mode == 'hub'
            or self.campaign_line_ids.filtered(lambda l: l.hub_outbound_id)
        ):
            try:
                self.env['whatsapp.outbound.message'].sudo().service_quarantine_campaign(
                    self.id,
                    reason=f"Campaign {self.id} cancelled",
                )
            except Exception as exc:
                _logger.warning(
                    "Campaign %s cancel quarantine skipped/failed: %s",
                    self.id,
                    exc,
                )

    def action_retry_failed(self):
        """Retry failed messages with Hub-safe identity reuse."""
        self.ensure_one()
        failed = self.campaign_line_ids.filtered(lambda l: l.status == 'failed')
        if not failed:
            raise UserError("No failed messages to retry.")
        reset = self.env['wa.campaign.line']
        for line in failed:
            if line._hub_retry_allowed():
                reset |= line
        if not reset:
            raise UserError(
                "No failed Hub/legacy lines eligible for retry "
                "(provider-accepted Hub lines are not resent)."
            )
        reset.write({'status': 'pending', 'error_msg': False})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': f'{len(reset)} messages marked for retry',
                'type': 'success',
            }
        }

    def action_view_lines(self):
        """Open campaign lines view."""
        self.ensure_one()
        return {
            'name': f'Campaign Recipients: {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'wa.campaign.line',
            'view_mode': 'list,form,pivot,graph',
            'domain': [('campaign_id', '=', self.id)],
            'context': {'default_campaign_id': self.id},
        }

    def action_clone_campaign(self):
        """Clone this campaign."""
        self.ensure_one()
        new_campaign = self.copy({
            'name': f"{self.name} (Copy)",
            'state': 'draft',
            'start_date': False,
            'completed_date': False,
            'campaign_line_ids': False,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'wa.campaign',
            'res_id': new_campaign.id,
            'view_mode': 'form',
            'target': 'current',
        }
