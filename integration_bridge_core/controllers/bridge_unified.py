# -*- coding: utf-8 -*-
"""
Integration Bridge — Unified Inbound Controller (Odoo 19)
==========================================================
Single endpoint that routes all external platform events:
  - Evolution API (WhatsApp)
  - Chatwoot (conversations)
  - n8n (workflows)
  - Typebot (forms)
  - Dify / AI agents

All handlers create/update CRM leads and res.partner records.
No dependency on custom modules (error_reporter_16 removed).
"""
from odoo import http
from odoo.http import request
import json
import logging
import time
import traceback
from .bridge_base import BridgeControllerBase

_logger = logging.getLogger(__name__)


class BridgeUnifiedController(BridgeControllerBase):
    """
    Unified integration endpoint routing to platform-specific handlers.
    """

    # ── Main entry point ──────────────────────────────────────────────────────

    @http.route('/bridge/inbound', type='http', auth='public',
                methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def unified_inbound(self, **kwargs):
        """
        Unified inbound endpoint for all platforms.

        Expected payload:
        {
            "platform": "evolution | chatwoot | typebot | n8n | dify",
            "event_type": "message_created | form_submit | manual",
            "data": { ... platform-specific ... }
        }
        """
        start_time = time.time()
        payload = {}

        try:
            # Now type='http' — use http-style error responses
            auth_error = self._check_auth(json_route=False)
            if auth_error:
                return auth_error

            payload  = self._get_json_payload(**kwargs)
            platform = payload.get('platform', '').lower()
            event_type = payload.get('event_type', 'unknown')
            data     = payload.get('data', {})

            _logger.info(f"[Bridge] Received {platform} / {event_type}")

            if not platform:
                return self._error_response('Missing platform', 'platform field required', status=400)

            handler = getattr(self, f'_handle_{platform}', None)
            if not handler:
                return self._json_response({
                    'success': False,
                    'error': 'Unsupported platform',
                    'detail': f'No handler for: {platform}. Supported: evolution, chatwoot, typebot, n8n, dify',
                }, status=400)

            result = handler(event_type, data, payload)

            duration_ms = int((time.time() - start_time) * 1000)
            self._log_request(
                name=f"{platform.upper()} — {event_type}",
                direction='inbound', platform=platform,
                endpoint='/bridge/inbound',
                external_id=result.get('external_ref', ''),
                status='success',
                request_payload=payload, response_payload=result,
                http_status=200,
                related_model=result.get('odoo_model', ''),
                related_res_id=result.get('record_id', 0),
                duration_ms=duration_ms,
            )

            return self._json_response({'success': True, 'message': 'Processed successfully', **result})

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            _logger.error(f"[Bridge] Error: {e}\n{traceback.format_exc()}")
            try:
                self._log_request(
                    name=f"FAILED — {payload.get('platform', 'unknown')}",
                    direction='inbound',
                    platform=payload.get('platform', 'other'),
                    endpoint='/bridge/inbound',
                    status='failed',
                    request_payload=payload or kwargs,
                    error_message=str(e),
                    http_status=500,
                    duration_ms=duration_ms,
                )
            except Exception:
                pass
            return self._json_response({'success': False, 'error': str(e)}, status=500)

    # ── Health check ──────────────────────────────────────────────────────────

    @http.route('/bridge/inbound/health', type='http', auth='public',
                methods=['GET'], csrf=False, cors='*')
    def health(self):
        return request.make_response(
            json.dumps({
                'status': 'ok',
                'module': 'integration_bridge_core',
                'version': '19.0.1.0.0',
                'odoo': '19',
                'endpoints': {
                    'inbound':  '/bridge/inbound',
                    'health':   '/bridge/inbound/health',
                },
                'platforms': ['evolution', 'chatwoot', 'typebot', 'n8n', 'dify'],
            }),
            headers=self._get_cors_headers(),
        )

    # ── Helper: find or create partner ───────────────────────────────────────

    def _find_or_create_partner(self, phone=None, name=None, email=None):
        """Find existing partner by phone/email or create a new one."""
        Partner = request.env['res.partner'].sudo()

        # Detect available phone fields (mobile removed in some Odoo 19 builds)
        has_mobile = 'mobile' in Partner._fields

        partner = None
        if phone:
            domain = [('phone', '=', phone)]
            if has_mobile:
                domain = ['|', ('phone', '=', phone), ('mobile', '=', phone)]
            partner = Partner.search(domain, limit=1)
        if not partner and email:
            partner = Partner.search([('email', '=', email)], limit=1)
        if not partner and name:
            partner = Partner.search([('name', 'ilike', name)], limit=1)

        if not partner:
            vals = {'name': name or phone or 'Unknown Contact', 'type': 'contact'}
            if phone:
                if has_mobile:
                    vals['mobile'] = phone
                else:
                    vals['phone'] = phone
            if email:
                vals['email'] = email
            partner = Partner.create(vals)
            _logger.info(f"[Bridge] Created partner #{partner.id}: {partner.name}")

        return partner

    def _find_or_create_lead(self, partner, name, description='', source='bridge'):
        """Find existing open lead for partner or create new one."""
        Lead = request.env['crm.lead'].sudo()

        # Check open lead for this partner
        existing = Lead.search([
            ('partner_id', '=', partner.id),
            ('active', '=', True),
            ('stage_id.is_won', '=', False),
        ], limit=1, order='create_date desc')

        if existing:
            _logger.info(f"[Bridge] Reusing lead #{existing.id} for partner {partner.name}")
            return existing, False  # existing, created=False

        # Get/create "New" stage
        Stage = request.env['crm.stage'].sudo()
        stage = Stage.search([('name', 'ilike', 'new')], limit=1)
        if not stage:
            stage = Stage.search([], limit=1, order='sequence asc')

        lead_vals = {
            'name':        name[:100] if name else f'WhatsApp — {partner.name}',
            'partner_id':  partner.id,
            'partner_name': partner.name,
            'description': description,
            'phone':       (getattr(partner, 'mobile', None) or partner.phone or ''),
            'email_from':  partner.email or '',
            'type':        'lead',
        }
        if stage:
            lead_vals['stage_id'] = stage.id

        lead = Lead.create(lead_vals)
        _logger.info(f"[Bridge] Created lead #{lead.id}: {lead.name}")
        return lead, True  # lead, created=True

    # ── Evolution native webhook (delivery/read status updates) ─────────────

    @http.route('/bridge/evolution/webhook', type='http', auth='public',
                methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def evolution_native_webhook(self, **kwargs):
        """
        Accepts native Evolution API webhook payloads directly.

        Configure in Evolution API:
          Webhook URL: https://your-odoo.dev.odoo.com/bridge/evolution/webhook
          Events: MESSAGES_UPDATE, MESSAGES_UPSERT, CONNECTION_UPDATE

        Payload shape for MESSAGES_UPDATE:
        {
            "event": "messages.update",
            "instance": "sabry_1",
            "data": [
                {
                    "key": {"id": "3EB0...", "fromMe": true, "remoteJid": "965...@s.whatsapp.net"},
                    "update": {"status": "READ"}   // PENDING | SENT | DELIVERED | READ
                }
            ]
        }
        """
        try:
            raw = request.httprequest.get_data(as_text=True)
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {}

        event    = payload.get('event', '')
        instance = payload.get('instance', 'unknown')
        data     = payload.get('data', [])

        _logger.info(f"[EVO Webhook] event={event} instance={instance}")

        try:
            if event == 'messages.update':
                items = data if isinstance(data, list) else [data]
                for item in items:
                    key    = item.get('key', {})
                    update = item.get('update', {})
                    msg_id = key.get('id', '')
                    status = update.get('status', '')
                    if msg_id and status and 'wa.message.log' in request.env:
                        request.env['wa.message.log'].sudo().update_delivery_status(msg_id, status)

            elif event in ('messages.upsert', 'message.upsert'):
                items = data if isinstance(data, list) else [data]
                for msg_data in items:
                    key      = msg_data.get('key', {})
                    if key.get('fromMe'):
                        continue
                    remote_jid = key.get('remoteJid', '')
                    phone = remote_jid.split('@')[0] if '@' in remote_jid else ''
                    message = msg_data.get('message', {})
                    text = (
                        message.get('conversation') or
                        message.get('extendedTextMessage', {}).get('text', '') or
                        '[media]'
                    )
                    if phone and 'wa.message.log' in request.env:
                        request.env['wa.message.log'].sudo().mark_replied(phone, reply_text=text)

        except Exception as e:
            _logger.warning(f"[EVO Webhook] Error processing event: {e}")

        return request.make_response(
            json.dumps({'ok': True, 'event': event}),
            headers={'Content-Type': 'application/json'},
        )

    # ── Evolution API handler ─────────────────────────────────────────────────

    def _handle_evolution(self, event_type, data, full_payload):
        """
        Handle Evolution API WhatsApp events.

        Expected data:
        {
            "instance": "sabry_1",
            "data": {
                "key": {"remoteJid": "201234567890@s.whatsapp.net", "fromMe": false},
                "message": {"conversation": "..."},
                "pushName": "Contact Name"
            }
        }
        """
        _logger.info(f"[Bridge Evolution] event={event_type}")

        instance     = data.get('instance', 'unknown')
        msg_data     = data.get('data', {})
        key          = msg_data.get('key', {})
        message      = msg_data.get('message', {})

        # Skip messages sent by us
        if key.get('fromMe'):
            return {'skipped': True, 'reason': 'outgoing_message'}

        remote_jid   = key.get('remoteJid', '')
        alt_jid      = key.get('remoteJidAlt', '')

        # Extract phone: prefer @s.whatsapp.net, fallback to remoteJidAlt
        phone = ''
        for jid in [remote_jid, alt_jid]:
            if '@s.whatsapp.net' in jid or '@c.us' in jid:
                phone = jid.split('@')[0]
                break
        if not phone and '@lid' in remote_jid and alt_jid:
            phone = alt_jid.split('@')[0]

        push_name    = msg_data.get('pushName', '')
        message_text = (
            message.get('conversation') or
            message.get('extendedTextMessage', {}).get('text', '') or
            message.get('imageMessage', {}).get('caption', '') or
            '[media/attachment]'
        )

        # Find or create partner + lead
        partner = self._find_or_create_partner(phone=phone, name=push_name or phone)
        lead_name = f"WhatsApp — {partner.name}"
        lead, created = self._find_or_create_lead(partner, lead_name, message_text, source='evolution')

        # Post message to chatter
        chatter = (
            f"<div style='padding:10px;border-left:3px solid #25D366'>"
            f"<b>📱 WhatsApp via Evolution API</b><br/>"
            f"<b>From:</b> {push_name or phone} ({phone})<br/>"
            f"<b>Instance:</b> {instance}<br/>"
            f"<b>Event:</b> {event_type}<br/><br/>"
            f"<div style='background:#f5f5f5;padding:8px;border-radius:4px'>"
            f"{message_text[:500]}"
            f"</div></div>"
        )
        lead.message_post(body=chatter, message_type='comment',
                          subtype_xmlid='mail.mt_note')

        # ── Post to WhatsApp discuss.channel (if evolution_whatsapp_chat installed) ──
        try:
            if hasattr(partner, '_get_or_create_wa_channel'):
                wa_channel = partner._get_or_create_wa_channel()
                wa_channel.wa_post_inbound(message_text[:1000], push_name=push_name or phone)
                _logger.info(f"[Bridge Evolution] Inbound posted to WA channel #{wa_channel.id}")
        except Exception as e:
            _logger.warning(f"[Bridge Evolution] Could not post to WA channel: {e}")

        # Move to Contacted stage if lead was just created
        if created:
            Stage = request.env['crm.stage'].sudo()
            stage = Stage.search([('name', 'ilike', 'contact')], limit=1)
            if stage:
                lead.write({'stage_id': stage.id})

        return {
            'record_id':    lead.id,
            'odoo_model':   'crm.lead',
            'partner_id':   partner.id,
            'lead_created': created,
            'phone':        phone,
            'push_name':    push_name,
            'instance':     instance,
            'external_ref': f"EVO-{instance}-{phone}",
        }

    # ── Chatwoot handler ──────────────────────────────────────────────────────

    def _handle_chatwoot(self, event_type, data, full_payload):
        """
        Handle Chatwoot conversation events → create/update CRM lead.

        Expected data:
        {
            "name": "...",
            "description": "...",
            "reporter": {"phone": "+20...", "name": "...", "email": "..."},
            "chatwoot": {"conversation_id": "...", "account_id": "...", ...}
        }
        """
        _logger.info(f"[Bridge Chatwoot] event={event_type}")

        reporter    = data.get('reporter', {})
        chatwoot    = data.get('chatwoot', {})
        phone       = self._sanitize_phone(reporter.get('phone', ''))
        name        = reporter.get('name', 'Chatwoot User')
        email       = reporter.get('email', '')
        conv_id     = chatwoot.get('conversation_id', '')
        description = data.get('description') or data.get('name') or 'Chatwoot message'

        partner     = self._find_or_create_partner(phone=phone, name=name, email=email)
        lead_name   = f"Chatwoot — {partner.name}"
        lead, created = self._find_or_create_lead(partner, lead_name, description, 'chatwoot')

        chatter = (
            f"<div style='padding:10px;border-left:3px solid #1F93FF'>"
            f"<b>💬 Chatwoot Message</b><br/>"
            f"<b>From:</b> {name} ({phone or email})<br/>"
            f"<b>Conversation:</b> {conv_id}<br/>"
            f"<b>Event:</b> {event_type}<br/><br/>"
            f"<div style='background:#f5f5f5;padding:8px;border-radius:4px'>"
            f"{description[:500]}"
            f"</div></div>"
        )
        lead.message_post(body=chatter, message_type='comment',
                          subtype_xmlid='mail.mt_note')

        return {
            'record_id':       lead.id,
            'odoo_model':      'crm.lead',
            'partner_id':      partner.id,
            'lead_created':    created,
            'external_ref':    f"CW-{conv_id}" if conv_id else f"CW-{int(time.time())}",
            'conversation_id': conv_id,
        }

    # ── Typebot handler ───────────────────────────────────────────────────────

    def _handle_typebot(self, event_type, data, full_payload):
        """Handle Typebot form submissions → CRM lead."""
        _logger.info(f"[Bridge Typebot] event={event_type}")

        answers  = data.get('answers', {})
        contact  = data.get('contact', {})
        form_id  = data.get('form_id', '')

        phone    = self._sanitize_phone(contact.get('phone', ''))
        name     = contact.get('name', 'Typebot User')
        email    = contact.get('email', '')
        title    = answers.get('title', answers.get('error_title', 'Typebot Form')) or 'Typebot Form'
        desc     = answers.get('description', answers.get('error_description', '')) or title

        partner  = self._find_or_create_partner(phone=phone, name=name, email=email)
        lead, created = self._find_or_create_lead(partner, f"Typebot — {title}", desc, 'typebot')

        chatter = (
            f"<div style='padding:10px;border-left:3px solid #8B5CF6'>"
            f"<b>📝 Typebot Form</b><br/>"
            f"<b>Form:</b> {form_id}<br/>"
            f"<b>Contact:</b> {name} ({phone or email})<br/>"
            f"<b>Title:</b> {title}"
            f"</div>"
        )
        lead.message_post(body=chatter, message_type='comment',
                          subtype_xmlid='mail.mt_note')

        return {
            'record_id':   lead.id,
            'odoo_model':  'crm.lead',
            'partner_id':  partner.id,
            'lead_created': created,
            'external_ref': f"TB-{form_id}" if form_id else f"TB-{int(time.time())}",
            'form_id':     form_id,
        }

    # ── n8n handler ───────────────────────────────────────────────────────────

    def _handle_n8n(self, event_type, data, full_payload):
        """n8n workflows use same structure as Chatwoot."""
        _logger.info(f"[Bridge n8n] event={event_type}")
        return self._handle_chatwoot(event_type, data, full_payload)

    # ── Dify handler ──────────────────────────────────────────────────────────

    def _handle_dify(self, event_type, data, full_payload):
        """Handle Dify AI agent events."""
        _logger.info(f"[Bridge Dify] event={event_type}")

        text            = data.get('text', '').strip()
        external_user   = data.get('external_user_id', 'dify_user')
        conversation_id = data.get('conversation_id', '')

        try:
            DifyClient = request.env['integration.bridge.dify.client']
            is_workflow = text.startswith('/run ')

            if is_workflow:
                result = DifyClient.run_workflow(
                    inputs={'command': text[5:].strip(), 'user_id': external_user},
                    user_external_id=external_user,
                )
                return {
                    'mode': 'workflow',
                    'workflow_run_id': result.get('workflow_run_id'),
                    'status':          result.get('status'),
                    'outputs':         result.get('outputs', {}),
                    'external_user_id': external_user,
                }
            else:
                result = DifyClient.chatflow(
                    query=text,
                    conversation_id=conversation_id or None,
                    user_external_id=external_user,
                    inputs=data.get('inputs', {}),
                )
                return {
                    'mode':            'chatflow',
                    'answer':          result.get('answer'),
                    'conversation_id': result.get('conversation_id'),
                    'message_id':      result.get('message_id'),
                    'external_user_id': external_user,
                }
        except Exception as e:
            _logger.error(f"[Bridge Dify] Error: {e}")
            raise
