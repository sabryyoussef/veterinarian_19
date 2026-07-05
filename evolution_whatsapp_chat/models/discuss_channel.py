# -*- coding: utf-8 -*-
"""
Extend discuss.channel to support WhatsApp routing via Evolution API.

When a message is posted to a channel of type 'whatsapp' by an internal user,
the message is forwarded to Evolution API in addition to being stored in Odoo.
Incoming messages from Evolution are posted here by bridge_unified.py.
"""
import json
import logging
import requests

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Evolution API helpers (read config from ir.config_parameter at runtime)
# ---------------------------------------------------------------------------

def _evo_config(env):
    ICP = env['ir.config_parameter'].sudo()
    return {
        'url':      ICP.get_param('integration_bridge.evolution_url',      'http://127.0.0.1:8099'),
        'key':      ICP.get_param('integration_bridge.evolution_key',       ''),
        'instance': ICP.get_param('integration_bridge.evolution_instance',  'sabry'),
    }


def _send_via_evolution(env, phone, text, media_url=None, media_type=None,
                        partner_id=None, lead_id=None, channel_id=None, queue_id=None):
    """
    Send a text (or media) message through Evolution API.
    Returns (success: bool, response_text: str, wa_message_id: str|None).

    When successful, creates a wa.message.log record if the model is available.
    """
    cfg = _evo_config(env)
    if not cfg['key'] or not cfg['url']:
        _logger.error("[WA Channel] Evolution API not configured")
        return False, "Evolution API not configured", None

    # Normalise phone: strip +, spaces, dashes
    clean = str(phone).replace('+', '').replace(' ', '').replace('-', '').strip()
    if not clean:
        return False, "No phone number", None

    headers = {
        'apikey':       cfg['key'],
        'Content-Type': 'application/json',
    }

    try:
        if media_url and media_type:
            endpoint = f"{cfg['url']}/message/sendMedia/{cfg['instance']}"
            payload  = {
                'number':    clean,
                'mediatype': media_type,
                'media':     media_url,
                'caption':   text or '',
            }
        else:
            endpoint = f"{cfg['url']}/message/sendText/{cfg['instance']}"
            payload  = {
                'number':  clean,
                'text':    text,
                'options': {'delay': 1000},
            }

        resp = requests.post(endpoint, json=payload, headers=headers, timeout=15)
        if resp.ok:
            _logger.info(f"[WA Channel] Sent to {clean}: HTTP {resp.status_code}")
            # Extract Evolution message ID from response
            wa_msg_id = None
            try:
                rj = resp.json()
                wa_msg_id = rj.get('key', {}).get('id') or rj.get('id')
            except Exception:
                pass

            # Create message log
            _create_wa_log(env, clean, text, wa_msg_id,
                           partner_id=partner_id, lead_id=lead_id,
                           channel_id=channel_id, queue_id=queue_id,
                           has_media=bool(media_url), media_type=media_type)

            return True, resp.text, wa_msg_id
        else:
            _logger.error(f"[WA Channel] Evolution error {resp.status_code}: {resp.text[:200]}")
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}", None

    except Exception as e:
        _logger.error(f"[WA Channel] Exception sending to {clean}: {e}")
        return False, str(e), None


def _create_wa_log(env, phone, text, wa_message_id,
                   partner_id=None, lead_id=None, channel_id=None, queue_id=None,
                   has_media=False, media_type=None, direction='out', delivery_status='sent'):
    """Create a wa.message.log record. Silently skips if model is unavailable."""
    try:
        if 'wa.message.log' not in env:
            return None
        vals = {
            'phone':           phone,
            'direction':       direction,
            'message_text':    (text or '')[:2000],
            'wa_message_id':   wa_message_id or False,
            'delivery_status': delivery_status,
            'has_media':       has_media,
            'media_type':      media_type or False,
        }
        if partner_id:
            vals['partner_id'] = partner_id if isinstance(partner_id, int) else partner_id.id
        if lead_id:
            vals['lead_id'] = lead_id if isinstance(lead_id, int) else lead_id.id
        if channel_id:
            vals['channel_id'] = channel_id if isinstance(channel_id, int) else channel_id.id
        if queue_id:
            vals['queue_id'] = queue_id if isinstance(queue_id, int) else queue_id.id
        return env['wa.message.log'].sudo().create(vals)
    except Exception as e:
        _logger.warning(f"[WA Log] Could not create log: {e}")
        return None


class DiscussChannelWhatsApp(models.Model):
    _inherit = 'discuss.channel'

    # ── WhatsApp fields ───────────────────────────────────────────────────────

    wa_partner_id = fields.Many2one(
        'res.partner', string='WhatsApp Contact',
        index=True, ondelete='set null',
        help='The Odoo contact this WhatsApp channel belongs to'
    )

    wa_phone = fields.Char(
        string='WhatsApp Phone',
        help='Phone number in E.164-ish format (no + sign): 201000059085'
    )

    wa_last_inbound = fields.Datetime(
        string='Last Message Received', readonly=True
    )

    wa_last_outbound = fields.Datetime(
        string='Last Message Sent', readonly=True
    )

    # ── Override message_post to route outbound to Evolution ─────────────────

    def _is_wa_channel(self):
        # Use wa_phone as the identifier — do NOT rely on channel_type='whatsapp'
        # because the enterprise WhatsApp module owns that type and adds constraints
        # that require its own wa_account_id / whatsapp_number fields.
        return bool(self.wa_phone)

    def message_post(self, *, message_type='comment', **kwargs):
        """
        If this is a WhatsApp channel and the author is an internal user (not the
        external contact), forward the message to Evolution API before storing.
        """
        msg = super().message_post(message_type=message_type, **kwargs)

        if not self._is_wa_channel():
            return msg

        # Only forward messages written by an Odoo user (not incoming from Evolution)
        # Incoming messages from Evolution are posted with author = partner (not user)
        # so we check if the author has an active internal user record
        author = msg.author_id
        is_internal = (
            author
            and self.env['res.users'].sudo().search_count(
                [('partner_id', '=', author.id), ('share', '=', False)]) > 0
        )

        if not is_internal:
            return msg  # incoming message from contact, no need to re-send

        # Build plain text from HTML body
        body_html = msg.body or ''
        from odoo.tools import html2plaintext
        plain_text = html2plaintext(body_html).strip()

        if not plain_text:
            return msg

        success, response, wa_msg_id = _send_via_evolution(
            self.env, self.wa_phone, plain_text,
            partner_id=self.wa_partner_id.id if self.wa_partner_id else None,
            channel_id=self.id,
        )

        # Update last outbound timestamp
        if success:
            self.sudo().write({'wa_last_outbound': fields.Datetime.now()})
            _logger.info(f"[WA Channel] Outbound delivered to {self.wa_phone} (msg_id={wa_msg_id})")
        else:
            self.sudo().message_post(
                body=f"<em>⚠️ WhatsApp delivery failed: {response}</em>",
                message_type='notification',
                subtype_xmlid='mail.mt_note',
            )

        return msg

    # ── Helper: post an inbound message from Evolution ────────────────────────

    def wa_post_inbound(self, text, push_name=''):
        """
        Called by bridge_unified._handle_evolution() to post an incoming
        WhatsApp message into this channel as the contact's message.
        """
        self.ensure_one()
        author = self.wa_partner_id or self.env.ref('base.public_partner')

        self.sudo().message_post(
            body=f"<p>{text}</p>",
            author_id=author.id,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
        self.sudo().write({'wa_last_inbound': fields.Datetime.now()})
        _logger.info(f"[WA Channel] Inbound posted to channel #{self.id} from {push_name or self.wa_phone}")

        # Create inbound log + mark previous outbound as replied
        phone = self.wa_phone or ''
        _create_wa_log(
            self.env, phone, text, wa_message_id=None,
            partner_id=self.wa_partner_id.id if self.wa_partner_id else None,
            channel_id=self.id,
            direction='in', delivery_status='sent',
        )
        if phone:
            self.env['wa.message.log'].sudo().mark_replied(phone, reply_text=text)
