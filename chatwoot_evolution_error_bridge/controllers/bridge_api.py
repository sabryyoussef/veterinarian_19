# -*- coding: utf-8 -*-
"""
Backward-compatible /bridge/error_reports endpoints.
In Odoo 19 these routes now create/update crm.lead instead of error.report.
Existing n8n workflows using these routes need zero changes.
"""
from odoo import http, fields
from odoo.http import request
import json
import logging
import time
import traceback
from functools import wraps

_logger = logging.getLogger(__name__)


def _jr(data, status=200):
    """Return a plain HTTP JSON response (required for type='http' routes in Odoo 19)."""
    return request.make_response(
        json.dumps(data, ensure_ascii=False, default=str),
        headers=[('Content-Type', 'application/json'),
                 ('Access-Control-Allow-Origin', '*')],
        status=status,
    )


def _get_master_token():
    ICP = request.env['ir.config_parameter'].sudo()
    return (
        ICP.get_param('integration_bridge.master_token', default='') or
        ICP.get_param('chatwoot_bridge.token', default='')
    )


def validate_bridge_token(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        token_header = request.httprequest.headers.get('X-Bridge-Token', '')
        remote_ip    = request.httprequest.remote_addr
        master_token = _get_master_token()

        if not master_token:
            _logger.error("[Bridge API] Token not configured")
            return request.make_json_response(
                {'success': False, 'error': 'Token not configured'}, status=500)

        if not token_header or token_header != master_token:
            _logger.warning(f"[Bridge API] Invalid token from {remote_ip}")
            return request.make_json_response(
                {'success': False, 'error': 'Unauthorized'}, status=401)

        ICP = request.env['ir.config_parameter'].sudo()
        ip_whitelist = ICP.get_param('integration_bridge.ip_whitelist', default='')
        if ip_whitelist:
            allowed = [ip.strip() for ip in ip_whitelist.split(',') if ip.strip()]
            if allowed and remote_ip not in allowed:
                _logger.warning(f"[Bridge API] IP {remote_ip} not in whitelist")
                return request.make_json_response(
                    {'success': False, 'error': 'Forbidden'}, status=403)

        return func(self, *args, **kwargs)
    return wrapper


def _cors_headers():
    ICP = request.env['ir.config_parameter'].sudo()
    origins = ICP.get_param('chatwoot_bridge.cors_origins', default='*')
    return [
        ('Access-Control-Allow-Origin',  origins),
        ('Access-Control-Allow-Methods', 'POST, GET, OPTIONS'),
        ('Access-Control-Allow-Headers', 'Content-Type, X-Bridge-Token'),
        ('Content-Type', 'application/json'),
    ]


def _sanitize_phone(phone):
    return str(phone or '').replace('+', '').replace('@s.whatsapp.net', '').strip()


def _find_or_create_partner(phone=None, name=None, email=None):
    Partner = request.env['res.partner'].sudo()
    has_mobile = 'mobile' in Partner._fields
    partner = None
    if phone:
        domain = [('phone', '=', phone)]
        if has_mobile:
            domain = ['|', ('phone', '=', phone), ('mobile', '=', phone)]
        partner = Partner.search(domain, limit=1)
    if not partner and email:
        partner = Partner.search([('email', '=', email)], limit=1)
    if not partner:
        vals = {'name': name or phone or 'WhatsApp Contact', 'type': 'contact'}
        if phone:
            vals['mobile' if has_mobile else 'phone'] = phone
        if email:
            vals['email'] = email
        partner = Partner.create(vals)
    return partner


class ChatwootBridgeAPI(http.Controller):
    """Backward-compatible bridge API for legacy n8n/Chatwoot workflows."""

    # ── POST /bridge/error_reports ────────────────────────────────────────────

    @http.route('/bridge/error_reports', type='http', auth='public',
                methods=['POST'], csrf=False, cors='*')
    @validate_bridge_token
    def create_error_report(self, **kwargs):
        """Create a CRM lead from a Chatwoot/WhatsApp conversation."""
        try:
            raw = request.httprequest.get_data(as_text=True)
            data = json.loads(raw) if raw else kwargs
            reporter     = data.get('reporter', {})
            chatwoot     = data.get('chatwoot', {})
            phone        = _sanitize_phone(reporter.get('phone', ''))
            r_name       = reporter.get('name', 'WhatsApp User')
            r_email      = reporter.get('email', '')
            conv_id      = chatwoot.get('conversation_id', '')
            external_ref = f"CW-{conv_id}" if conv_id else ''

            Lead = request.env['crm.lead'].sudo()

            # Duplicate check
            if external_ref:
                existing = Lead.search(
                    [('x_external_ref', '=', external_ref)], limit=1)
                if existing:
                    return _jr({
                        'success':   True,
                        'duplicate': True,
                        'error_id':  existing.id,
                        'error_number': f"CRM-{existing.id:05d}",
                        'odoo_url':  f"/web#id={existing.id}&model=crm.lead&view_type=form",
                        'external_ref': external_ref,
                        'chatwoot_conversation_id': conv_id,
                        'message':   'Lead already exists for this conversation',
                    })

            partner = _find_or_create_partner(phone=phone, name=r_name, email=r_email)

            # Get/create Stage
            Stage = request.env['crm.stage'].sudo()
            stage = Stage.search([('name', 'ilike', 'new')], limit=1)
            if not stage:
                stage = Stage.search([], limit=1, order='sequence asc')

            title = data.get('name') or f"Chatwoot — {r_name}"
            desc  = data.get('description') or data.get('error_message') or ''

            lead_vals = {
                'name':         title[:100],
                'partner_id':   partner.id,
                'partner_name': partner.name,
                'description':  desc,
                'phone':        phone,
                'email_from':   r_email,
                'type':         'lead',
                # Chatwoot tracking
                'x_source_platform':          'chatwoot',
                'x_reporter_phone':           phone,
                'x_reporter_name':            r_name,
                'x_reporter_email':           r_email,
                'x_chatwoot_account_id':      chatwoot.get('account_id', ''),
                'x_chatwoot_inbox_id':        chatwoot.get('inbox_id', ''),
                'x_chatwoot_conversation_id': conv_id,
                'x_chatwoot_contact_id':      chatwoot.get('contact_id', ''),
                'x_chatwoot_message_id':      chatwoot.get('message_id', ''),
                'x_chatwoot_payload':         json.dumps(
                    chatwoot.get('payload', {}), ensure_ascii=False),
            }
            if external_ref:
                lead_vals['x_external_ref'] = external_ref
            if stage:
                lead_vals['stage_id'] = stage.id

            lead = Lead.create(lead_vals)
            _logger.info(f"[Bridge API] Created lead #{lead.id}: {lead.name}")

            chatter = (
                f"<div style='padding:10px;border-left:3px solid #00A09D'>"
                f"<b>📱 Chatwoot/WhatsApp → CRM</b><br/>"
                f"<b>Reporter:</b> {r_name} ({phone})<br/>"
                f"<b>Email:</b> {r_email or 'N/A'}<br/>"
                f"<b>Conversation:</b> {conv_id}<br/>"
                f"<b>Ref:</b> {external_ref}"
                f"</div>"
            )
            lead.message_post(body=chatter, message_type='comment',
                              subtype_xmlid='mail.mt_note')

            return _jr({
                'success':      True,
                'error_id':     lead.id,
                'error_number': f"CRM-{lead.id:05d}",
                'odoo_url':     f"/web#id={lead.id}&model=crm.lead&view_type=form",
                'external_ref': external_ref,
                'chatwoot_conversation_id': conv_id,
                'message':      'Lead created successfully',
            })

        except Exception as e:
            _logger.error(f"[Bridge API] create_error_report: {e}\n{traceback.format_exc()}")
            return _jr({'success': False, 'error': str(e)})

    # ── POST /bridge/error_reports/<id>/status ────────────────────────────────

    @http.route('/bridge/error_reports/<int:lead_id>/status', type='http',
                auth='public', methods=['POST'], csrf=False, cors='*')
    @validate_bridge_token
    def update_error_status(self, lead_id, **kwargs):
        """Update CRM lead stage + post a chatter note."""
        try:
            raw = request.httprequest.get_data(as_text=True)
            data = json.loads(raw) if raw else kwargs
            Lead    = request.env['crm.lead'].sudo()
            lead    = Lead.browse(lead_id)

            if not lead.exists():
                return _jr({'success': False, 'error': f'Lead #{lead_id} not found'})

            new_status = data.get('status', '')
            note       = data.get('note', '')

            # Map legacy status names to CRM stage names
            stage_map = {
                'new':         'New',
                'in_progress': 'Contacted',
                'fixed':       'Won',
                'wont_fix':    'Lost',
                'duplicate':   'Lost',
            }

            if new_status and new_status in stage_map:
                Stage = request.env['crm.stage'].sudo()
                stage = Stage.search(
                    [('name', 'ilike', stage_map[new_status])], limit=1)
                if stage:
                    lead.write({'stage_id': stage.id})

            if note:
                lead.message_post(
                    body=f"<p><b>Status Update via Bridge API:</b></p><p>{note}</p>",
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                )

            return _jr({
                'success':      True,
                'error_id':     lead.id,
                'error_number': f"CRM-{lead.id:05d}",
                'status':       lead.stage_id.name if lead.stage_id else '',
                'message':      'Lead updated',
            })

        except Exception as e:
            _logger.error(f"[Bridge API] update_error_status: {e}\n{traceback.format_exc()}")
            return _jr({'success': False, 'error': str(e)})

    # ── GET /bridge/error_reports/<id> ────────────────────────────────────────

    @http.route('/bridge/error_reports/<int:lead_id>', type='http',
                auth='public', methods=['GET'], csrf=False, cors='*')
    @validate_bridge_token
    def get_error_report(self, lead_id, **kwargs):
        """Return CRM lead detail in legacy error-report format."""
        try:
            lead = request.env['crm.lead'].sudo().browse(lead_id)
            if not lead.exists():
                return _jr({'success': False, 'error': f'Lead #{lead_id} not found'})

            return _jr({
                'success': True,
                'error': {
                    'id':           lead.id,
                    'error_number': f"CRM-{lead.id:05d}",
                    'name':         lead.name,
                    'description':  lead.description or '',
                    'status':       lead.stage_id.name if lead.stage_id else '',
                    'reporter_name':  getattr(lead, 'x_reporter_name', ''),
                    'reporter_phone': getattr(lead, 'x_reporter_phone', ''),
                    'reporter_email': getattr(lead, 'x_reporter_email', ''),
                    'chatwoot_conversation_id': getattr(
                        lead, 'x_chatwoot_conversation_id', ''),
                    'external_ref': getattr(lead, 'x_external_ref', ''),
                    'odoo_url':     f"/web#id={lead.id}&model=crm.lead&view_type=form",
                    'created_at':   lead.create_date.isoformat() if lead.create_date else None,
                },
            })

        except Exception as e:
            _logger.error(f"[Bridge API] get_error_report: {e}\n{traceback.format_exc()}")
            return _jr({'success': False, 'error': str(e)})

    # ── GET /bridge/error_reports/<id>/reply_message ──────────────────────────

    @http.route('/bridge/error_reports/<int:lead_id>/reply_message', type='http',
                auth='public', methods=['GET'], csrf=False, cors='*')
    @validate_bridge_token
    def get_reply_message(self, lead_id, **kwargs):
        """Return a formatted WhatsApp reply message for this lead."""
        try:
            lead = request.env['crm.lead'].sudo().browse(lead_id)
            if not lead.exists():
                return _jr({'success': False, 'error': f'Lead #{lead_id} not found'})

            return _jr({
                'success':         True,
                'error_id':        lead.id,
                'message':         lead.get_chatwoot_reply_message(),
                'conversation_id': getattr(lead, 'x_chatwoot_conversation_id', ''),
            })

        except Exception as e:
            _logger.error(f"[Bridge API] get_reply_message: {e}\n{traceback.format_exc()}")
            return _jr({'success': False, 'error': str(e)})

    # ── GET /bridge/health ────────────────────────────────────────────────────

    @http.route('/bridge/health', type='http', auth='public',
                methods=['GET'], csrf=False, cors='*')
    def health_check(self):
        return request.make_response(
            json.dumps({
                'status':  'ok',
                'module':  'chatwoot_evolution_error_bridge',
                'version': '19.0.1.0.0',
                'odoo':    '19',
            }),
            headers=_cors_headers(),
        )
