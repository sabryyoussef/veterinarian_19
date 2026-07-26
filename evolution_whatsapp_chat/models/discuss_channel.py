# -*- coding: utf-8 -*-
"""
Extend discuss.channel to support WhatsApp routing via Evolution API.

Phase 4: Partner Discuss outbound is orchestrated by
``_send_whatsapp_discuss_message`` which selects exactly one mode:

* ``legacy`` — ``_send_via_evolution`` (unchanged transport)
* ``shadow`` — Hub admission preview + legacy send once (no Hub transport)
* ``hub`` — unified ``service_send_message`` only (no ``_send_via_evolution``)

Campaign / wizard callers still import ``_send_via_evolution`` directly.
"""
import logging
import requests
from urllib.parse import quote

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError, AccessError
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)

# Defaults: main Evolution on master (Chatwoot-linked instance).
_EVO_URL_DEFAULT = 'http://127.0.0.1:8080'
_EVO_INSTANCE_DEFAULT = 'sabry min'


def _icp_bool(env, key, default=False):
    raw = (env['ir.config_parameter'].sudo().get_param(key) or '').strip().lower()
    if not raw:
        return default
    return raw in ('1', 'true', 'yes', 'on')


def _parse_discuss_hub_allowlist(env):
    """
    Parse whatsapp_hub.discuss_hub_allowed_channel_ids.

    Returns:
      list[int] — explicit allowlist
      None — empty/missing (fail-closed when Discuss cutover is ON)
      False — malformed (fail-closed)
    """
    raw = (
        env['ir.config_parameter']
        .sudo()
        .get_param('whatsapp_hub.discuss_hub_allowed_channel_ids')
        or ''
    ).strip()
    if not raw:
        return None
    ids = []
    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            return False
        ids.append(int(part))
    return ids or None


# ---------------------------------------------------------------------------
# Evolution API helpers (read config from ir.config_parameter at runtime)
# ---------------------------------------------------------------------------

def _evo_config(env, purpose=None, instance_name=None):
    """Prefer evolution.instance (multi-instance); fall back to ICP singleton."""
    Evo = env.get('evolution.instance')
    if Evo is not None:
        if instance_name:
            return Evo.get_config_by_instance_name(instance_name)
        if purpose:
            return Evo.get_config_for_purpose(purpose)
        return Evo.get_default_config()
    ICP = env['ir.config_parameter'].sudo()
    instance = ICP.get_param('integration_bridge.evolution_instance', _EVO_INSTANCE_DEFAULT)
    return {
        'url': ICP.get_param('integration_bridge.evolution_url', _EVO_URL_DEFAULT).rstrip('/'),
        'key': ICP.get_param('integration_bridge.evolution_key', ''),
        'instance': instance,
        # Instance names may contain spaces (e.g. "sabry min").
        'instance_path': quote(instance or '', safe=''),
        'instance_id': False,
        'purpose': False,
    }


def _send_via_evolution(env, phone, text, media_url=None, media_type=None,
                        partner_id=None, lead_id=None, channel_id=None, queue_id=None,
                        campaign_id=None, campaign_line_id=None,
                        mail_message_id=None):
    """
    Send a text (or media) message through Evolution API.
    Returns (success: bool, response_text: str, wa_message_id: str|None).

    When successful, creates a wa.message.log record if the model is available.
    Send path unchanged for Campaign — optional campaign refs enrich the log/mirror only.
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
        inst = cfg['instance_path']
        if media_url and media_type:
            endpoint = f"{cfg['url']}/message/sendMedia/{inst}"
            payload  = {
                'number':    clean,
                'mediatype': media_type,
                'media':     media_url,
                'caption':   text or '',
            }
        else:
            endpoint = f"{cfg['url']}/message/sendText/{inst}"
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
            _create_wa_log(
                env, clean, text, wa_msg_id,
                partner_id=partner_id, lead_id=lead_id,
                channel_id=channel_id, queue_id=queue_id,
                campaign_id=campaign_id, campaign_line_id=campaign_line_id,
                has_media=bool(media_url), media_type=media_type,
                mail_message_id=mail_message_id,
                send_origin='legacy',
            )

            return True, resp.text, wa_msg_id
        else:
            _logger.error(f"[WA Channel] Evolution error {resp.status_code}: {resp.text[:200]}")
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}", None

    except Exception as e:
        _logger.error(f"[WA Channel] Exception sending to {clean}: {e}")
        return False, str(e), None


def _create_wa_log(env, phone, text, wa_message_id,
                   partner_id=None, lead_id=None, channel_id=None, queue_id=None,
                   campaign_id=None, campaign_line_id=None,
                   has_media=False, media_type=None, direction='out', delivery_status='sent',
                   mail_message_id=None, hub_message_id=None, send_origin='legacy'):
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
            'send_origin':     send_origin or 'legacy',
        }
        if partner_id:
            vals['partner_id'] = partner_id if isinstance(partner_id, int) else partner_id.id
        if lead_id:
            vals['lead_id'] = lead_id if isinstance(lead_id, int) else lead_id.id
        if channel_id:
            vals['channel_id'] = channel_id if isinstance(channel_id, int) else channel_id.id
        if queue_id:
            vals['queue_id'] = queue_id if isinstance(queue_id, int) else queue_id.id
        if campaign_id:
            vals['campaign_id'] = campaign_id if isinstance(campaign_id, int) else campaign_id.id
        if campaign_line_id:
            vals['campaign_line_id'] = (
                campaign_line_id if isinstance(campaign_line_id, int) else campaign_line_id.id
            )
        if mail_message_id:
            vals['mail_message_id'] = (
                mail_message_id if isinstance(mail_message_id, int) else mail_message_id.id
            )
        if hub_message_id:
            vals['hub_message_id'] = (
                hub_message_id if isinstance(hub_message_id, int) else hub_message_id.id
            )
        return env['wa.message.log'].sudo().create(vals)
    except Exception as e:
        _logger.warning(f"[WA Log] Could not create log: {e}")
        return None


class DiscussChannelWhatsApp(models.Model):
    _inherit = 'discuss.channel'

    # ── WhatsApp fields ───────────────────────────────────────────────────────

    wa_partner_id = fields.Many2one(
        'res.partner', string='WA Contact',
        index=True, ondelete='set null',
        help='The Odoo contact this WA channel belongs to'
    )

    wa_phone = fields.Char(
        string='WA Phone',
        help='Phone number in E.164-ish format (no + sign): 201000059085'
    )

    wa_last_inbound = fields.Datetime(
        string='Last Message Received', readonly=True
    )

    wa_last_outbound = fields.Datetime(
        string='Last Message Sent', readonly=True
    )

    wa_outbound_mode = fields.Selection(
        [
            ('legacy', 'Legacy (_send_via_evolution)'),
            ('shadow', 'Shadow (legacy send + Hub preview)'),
            ('hub', 'Hub unified outbound'),
        ],
        string='WA Outbound Mode',
        default='legacy',
        required=True,
        help='Phase 4 Discuss routing. Default legacy. Hub mode also requires '
             'global + instance Discuss cutover flags. Admin-only change.',
    )

    # ── E3 Ops helpers (computed, non-stored) ─────────────────────────────────
    wa_hub_allowlisted = fields.Boolean(
        string='Hub Allowlisted',
        compute='_compute_wa_hub_ops',
        help='True if channel id is in whatsapp_hub.discuss_hub_allowed_channel_ids',
    )
    wa_hub_instance_name = fields.Char(
        string='Hub Instance',
        compute='_compute_wa_hub_ops',
    )
    wa_hub_conversation_id = fields.Many2one(
        'whatsapp.conversation',
        string='Canonical Conversation',
        compute='_compute_wa_hub_ops',
    )
    wa_hub_pending_count = fields.Integer(
        string='Pending Unified Jobs',
        compute='_compute_wa_hub_ops',
    )
    wa_hub_last_job_state = fields.Char(
        string='Last Unified Job State',
        compute='_compute_wa_hub_ops',
    )
    wa_hub_last_outbound_at = fields.Datetime(
        string='Last Hub Outbound',
        compute='_compute_wa_hub_ops',
    )
    wa_shadow_matched_count = fields.Integer(
        string='Shadow Matched',
        compute='_compute_wa_hub_ops',
    )
    wa_shadow_mismatch_count = fields.Integer(
        string='Shadow Mismatches',
        compute='_compute_wa_hub_ops',
    )
    wa_hub_health_warning = fields.Char(
        string='Ops Warning',
        compute='_compute_wa_hub_ops',
    )

    @api.depends('wa_phone', 'wa_outbound_mode')
    def _compute_wa_hub_ops(self):
        allow = _parse_discuss_hub_allowlist(self.env)
        allow_set = set(allow or []) if allow not in (None, False) else set()
        Out = self.env['whatsapp.outbound.message'].sudo()
        Message = self.env['whatsapp.message'].sudo()
        Shadow = self.env['whatsapp.discuss.shadow'].sudo()
        for ch in self:
            if not ch.wa_phone:
                ch.wa_hub_allowlisted = False
                ch.wa_hub_instance_name = False
                ch.wa_hub_conversation_id = False
                ch.wa_hub_pending_count = 0
                ch.wa_hub_last_job_state = False
                ch.wa_hub_last_outbound_at = False
                ch.wa_shadow_matched_count = 0
                ch.wa_shadow_mismatch_count = 0
                ch.wa_hub_health_warning = False
                continue
            ch.wa_hub_allowlisted = ch.id in allow_set
            try:
                inst = ch._wa_resolve_hub_instance()
                ch.wa_hub_instance_name = inst.instance_name if inst else False
            except Exception:
                ch.wa_hub_instance_name = False
            jobs = Out.search(
                [
                    ('discuss_channel_id', '=', ch.id),
                    ('transport_mode', '=', 'unified_bridge'),
                ],
                order='id desc',
                limit=50,
            )
            pending = jobs.filtered(lambda j: j.state in ('pending', 'processing'))
            ch.wa_hub_pending_count = len(pending)
            last = jobs[:1]
            ch.wa_hub_last_job_state = last.state if last else False
            ch.wa_hub_last_outbound_at = last.sent_at or last.create_date if last else False
            hub_msgs = Message.search(
                [('discuss_channel_id', '=', ch.id), ('source_app', '=', 'discuss')],
                order='id desc',
                limit=20,
            )
            ch.wa_hub_conversation_id = (
                hub_msgs[:1].conversation_id if hub_msgs else False
            )
            shadows = Shadow.search([('channel_id', '=', ch.id)])
            ch.wa_shadow_matched_count = len(
                shadows.filtered(lambda s: s.classification == 'matched')
            )
            ch.wa_shadow_mismatch_count = len(
                shadows.filtered(lambda s: s.classification != 'matched')
            )
            warns = []
            if ch.wa_outbound_mode == 'hub' and not ch.wa_hub_allowlisted:
                warns.append('hub not allowlisted')
            if ch.wa_hub_allowlisted and ch.wa_outbound_mode != 'hub':
                warns.append('allowlisted but not hub')
            if ch.wa_hub_pending_count:
                warns.append(f'pending={ch.wa_hub_pending_count}')
            if ch.wa_shadow_mismatch_count:
                warns.append(f'mismatch={ch.wa_shadow_mismatch_count}')
            ch.wa_hub_health_warning = '; '.join(warns) if warns else False

    # ── Override message_post to route outbound to Evolution ─────────────────

    def _is_wa_channel(self):
        # Use wa_phone as the identifier — do NOT rely on channel_type='whatsapp'
        # because the enterprise WhatsApp module owns that type and adds constraints
        # that require its own wa_account_id / whatsapp_number fields.
        return bool(self.wa_phone)

    def _wa_resolve_hub_instance(self):
        """Best-effort Hub instance matching the Evolution default used by Discuss."""
        self.ensure_one()
        Instance = self.env['whatsapp.instance'].sudo()
        cfg = _evo_config(self.env)
        name = (cfg or {}).get('instance') or False
        if name:
            rec = Instance.search(
                [('instance_name', '=', name), ('active', '=', True)], limit=1
            )
            if rec:
                return rec
        rec = Instance.search([('is_default', '=', True), ('active', '=', True)], limit=1)
        if rec:
            return rec
        return Instance.search([('active', '=', True)], limit=1)

    def _wa_discuss_business_key(self, mail_message):
        from odoo.addons.whatsapp_hub.models.whatsapp_message import discuss_business_key
        return discuss_business_key(self.id, mail_message.id)

    def _wa_resolve_outbound_mode(self):
        """Single routing decision for Discuss WA outbound. Default: legacy."""
        self.ensure_one()
        mode = self.wa_outbound_mode or 'legacy'
        if mode not in ('legacy', 'shadow', 'hub'):
            return 'legacy'
        return mode

    def _wa_hub_cutover_prerequisites(self, hub_instance):
        """
        Return (ok: bool, error: str).

        Hub mode requires global unified + discuss cutover AND instance flags
        AND explicit channel allowlist (Production fail-closed).
        Missing prerequisites are a safe pre-admission failure (no transport).
        """
        if not _icp_bool(self.env, 'whatsapp_hub.unified_outbound_enabled', False):
            return False, (
                "Hub Discuss cutover blocked: whatsapp_hub.unified_outbound_enabled is OFF."
            )
        if not _icp_bool(self.env, 'whatsapp_hub.discuss_cutover_enabled', False):
            return False, (
                "Hub Discuss cutover blocked: whatsapp_hub.discuss_cutover_enabled is OFF."
            )
        # Fail-closed allowlist whenever Discuss cutover capability is ON.
        allow = _parse_discuss_hub_allowlist(self.env)
        if allow is None:
            return False, (
                "Hub Discuss cutover blocked: whatsapp_hub.discuss_hub_allowed_channel_ids "
                "is empty (fail-closed)."
            )
        if allow is False:
            return False, (
                "Hub Discuss cutover blocked: whatsapp_hub.discuss_hub_allowed_channel_ids "
                "is malformed (expected comma-separated integers)."
            )
        if self.id not in allow:
            return False, (
                f"Hub Discuss cutover blocked: channel {self.id} is not in "
                f"discuss_hub_allowed_channel_ids={allow}."
            )
        if not hub_instance:
            return False, "Hub Discuss cutover blocked: no WhatsApp Hub instance resolved."
        if not hub_instance.unified_outbound_enabled:
            return False, (
                f"Hub Discuss cutover blocked: instance '{hub_instance.display_name}' "
                "unified_outbound_enabled is OFF."
            )
        if not hub_instance.discuss_cutover_enabled:
            return False, (
                f"Hub Discuss cutover blocked: instance '{hub_instance.display_name}' "
                "discuss_cutover_enabled is OFF."
            )
        return True, ""

    def _wa_build_hub_preview_vals(self, mail_message, plain_text, hub_instance):
        self.ensure_one()
        biz = self._wa_discuss_business_key(mail_message)
        cfg = _evo_config(self.env)
        return {
            'destination': self.wa_phone,
            'body': plain_text,
            'message_type': 'text',
            'purpose': 'discuss',
            'source_app': 'discuss',
            'client_request_id': biz,
            'business_key': biz,
            'related_model': 'mail.message',
            'related_res_id': mail_message.id,
            'partner_id': self.wa_partner_id.id if self.wa_partner_id else False,
            'discuss_channel_id': self.id,
            'instance_id': hub_instance.id if hub_instance else False,
            'instance_reference': (cfg or {}).get('instance') or False,
        }

    def _wa_map_hub_result_to_discuss(self, result):
        """Map Hub outbound lifecycle to Discuss success/failure UX.

        Do not report success merely because Hub admitted the message.
        After send_now, pending without a provider id means retry/not confirmed.
        """
        if not result:
            return False, "Hub outbound returned empty result"
        state = (result.get('state') or '').lower()
        delivery = (result.get('delivery_state') or '').lower()
        evo_id = result.get('evolution_message_id') or False
        if state == 'sent' or delivery in ('sent', 'delivered', 'read'):
            return True, evo_id or 'hub-sent'
        if state == 'failed' or delivery == 'failed':
            return False, "Hub outbound failed (see WhatsApp Hub outbound queue)"
        if evo_id and state in ('pending', 'processing'):
            return True, evo_id
        if state in ('pending', 'processing'):
            # Temporary transport failure schedules Hub retry — not user "sent".
            return False, (
                "WhatsApp delivery not confirmed; Hub will retry. "
                "No legacy fallback (avoid double-send)."
            )
        if result.get('ok') and evo_id:
            return True, evo_id
        return False, "Hub outbound did not accept the message"

    def _wa_create_hub_compat_log(self, mail_message, plain_text, hub_result, hub_msg):
        """Compatibility wa.message.log linked to canonical Hub message (no second send)."""
        delivery = 'sent'
        state = (hub_result or {}).get('state') or ''
        if state == 'failed':
            delivery = 'failed'
        elif state in ('pending', 'processing'):
            delivery = 'pending'
        return _create_wa_log(
            self.env,
            self.wa_phone,
            plain_text,
            (hub_result or {}).get('evolution_message_id'),
            partner_id=self.wa_partner_id.id if self.wa_partner_id else None,
            channel_id=self.id,
            mail_message_id=mail_message.id,
            hub_message_id=hub_msg.id if hub_msg else None,
            send_origin='hub_unified',
            delivery_status=delivery,
        )

    def _send_whatsapp_discuss_message(
        self,
        mail_message,
        plain_text,
        *,
        message_type='text',
        has_attachments=False,
    ):
        """
        Single Discuss outbound orchestration wrapper (Phase 4).

        Selects exactly one of: legacy | shadow | hub.
        Never runs legacy and Hub transport for the same message.
        """
        self.ensure_one()
        mode = self._wa_resolve_outbound_mode()
        partner = self.wa_partner_id
        hub_instance = self._wa_resolve_hub_instance()
        biz_key = self._wa_discuss_business_key(mail_message)

        # Unsupported rich content in Hub mode — never silent text-only.
        if mode == 'hub' and (has_attachments or message_type not in ('text', 'comment')):
            err = (
                "Hub Discuss mode supports text only. "
                "Attachments/media are not sent; switch channel to legacy or remove attachments."
            )
            return {
                'ok': False,
                'mode': mode,
                'error': err,
                'wa_message_id': None,
                'wa_log': None,
            }

        if mode == 'hub':
            ok_flags, flag_err = self._wa_hub_cutover_prerequisites(hub_instance)
            if not ok_flags:
                # Safe pre-admission failure — no Hub job, no legacy fallback (explicit hub mode).
                return {
                    'ok': False,
                    'mode': mode,
                    'error': flag_err,
                    'wa_message_id': None,
                    'wa_log': None,
                }
            Out = self.env['whatsapp.outbound.message']
            vals = self._wa_build_hub_preview_vals(mail_message, plain_text, hub_instance)
            vals['send_now'] = True
            try:
                result = Out.sudo().service_send_message(vals)
            except (UserError, ValidationError) as exc:
                return {
                    'ok': False,
                    'mode': mode,
                    'error': str(exc),
                    'wa_message_id': None,
                    'wa_log': None,
                }
            hub_msg = self.env['whatsapp.message'].sudo().browse(
                result.get('message_id') or 0
            )
            success, evo_or_err = self._wa_map_hub_result_to_discuss(result)
            wa_log = None
            if hub_msg:
                wa_log = self._wa_create_hub_compat_log(
                    mail_message, plain_text, result, hub_msg
                )
            if success:
                return {
                    'ok': True,
                    'mode': mode,
                    'error': False,
                    'wa_message_id': result.get('evolution_message_id') or evo_or_err,
                    'wa_log': wa_log,
                    'hub_result': result,
                    'business_key': biz_key,
                }
            # Post-admission / failed transport — Hub owns retry; no legacy fallback.
            return {
                'ok': False,
                'mode': mode,
                'error': evo_or_err if isinstance(evo_or_err, str) else 'Hub send failed',
                'wa_message_id': None,
                'wa_log': wa_log,
                'hub_result': result,
                'business_key': biz_key,
                'no_legacy_fallback': True,
            }

        # legacy + shadow: preview first (shadow), then exactly one legacy send
        preview = {'ok': False, 'eligible': False, 'classification': 'legacy_only', 'errors': []}
        if mode == 'shadow' and 'whatsapp.outbound.message' in self.env:
            try:
                preview = self.env['whatsapp.outbound.message'].sudo().service_preview_send_message(
                    self._wa_build_hub_preview_vals(mail_message, plain_text, hub_instance)
                )
            except Exception as exc:
                preview = {
                    'ok': False,
                    'eligible': False,
                    'classification': 'validation_error',
                    'errors': [str(exc)],
                    'candidate': {'business_key': biz_key},
                }

        success, response, wa_msg_id = _send_via_evolution(
            self.env,
            self.wa_phone,
            plain_text,
            partner_id=partner.id if partner else None,
            channel_id=self.id,
            mail_message_id=mail_message.id,
        )

        wa_log = None
        if success and mail_message and 'wa.message.log' in self.env:
            wa_log = self.env['wa.message.log'].sudo().search(
                [
                    ('channel_id', '=', self.id),
                    ('mail_message_id', '=', mail_message.id),
                    ('direction', '=', 'out'),
                ],
                order='id desc',
                limit=1,
            )
            if not wa_log and wa_msg_id:
                wa_log = self.env['wa.message.log'].sudo().search(
                    [('wa_message_id', '=', wa_msg_id)], order='id desc', limit=1
                )

        if mode == 'shadow' and 'whatsapp.discuss.shadow' in self.env:
            mirrored = self.env['whatsapp.message'].browse()
            if wa_log and 'whatsapp.hub.compat' in self.env:
                mirrored = self.env['whatsapp.message'].sudo().search(
                    [('wa_message_log_id', '=', wa_log.id)], limit=1
                )
            try:
                self.env['whatsapp.discuss.shadow'].record_from_preview(
                    channel=self,
                    mail_message=mail_message,
                    partner=partner,
                    preview=preview,
                    wa_log=wa_log,
                    mirrored_message=mirrored,
                    notes=f"mode=shadow legacy_ok={success}",
                )
            except Exception:
                _logger.exception("[WA Channel] Failed to store shadow comparison")

        return {
            'ok': bool(success),
            'mode': mode,
            'error': False if success else response,
            'wa_message_id': wa_msg_id,
            'wa_log': wa_log,
            'business_key': biz_key,
            'preview': preview if mode == 'shadow' else False,
        }

    def message_post(self, *, message_type='comment', **kwargs):
        """
        If this is a WhatsApp channel and the author is an internal user (not the
        external contact), forward the message via the Phase 4 Discuss wrapper.
        """
        msg = super().message_post(message_type=message_type, **kwargs)

        if self.env.context.get('skip_wa_outbound'):
            return msg
        if not self._is_wa_channel():
            return msg
        # Failure notes / system notifications must never re-enter WA send.
        if message_type not in ('comment', 'email'):
            return msg

        author = msg.author_id
        is_internal = (
            author
            and self.env['res.users'].sudo().search_count(
                [('partner_id', '=', author.id), ('share', '=', False)]) > 0
        )
        if not is_internal:
            return msg

        body_html = msg.body or ''
        plain_text = html2plaintext(body_html).strip()
        if not plain_text and not msg.attachment_ids:
            return msg

        result = self._send_whatsapp_discuss_message(
            msg,
            plain_text or '',
            message_type='text',
            has_attachments=bool(msg.attachment_ids),
        )

        if result.get('ok'):
            self.sudo().write({'wa_last_outbound': fields.Datetime.now()})
            _logger.info(
                "[WA Channel] Outbound mode=%s to %s (msg_id=%s)",
                result.get('mode'),
                self.wa_phone,
                result.get('wa_message_id'),
            )
        else:
            err = result.get('error') or 'unknown error'
            self.with_context(skip_wa_outbound=True).sudo().message_post(
                body=f"<em>⚠️ WA delivery failed: {err}</em>",
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

        self.with_context(skip_wa_outbound=True).sudo().message_post(
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

    def action_quarantine_hub_outbound(self):
        """Admin-only: quarantine incomplete Hub unified jobs for this channel."""
        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise AccessError("Only system administrators can quarantine Hub outbound jobs.")
        result = self.env['whatsapp.outbound.message'].service_quarantine_discuss_channel(
            self.id,
            reason=f"admin quarantine from discuss.channel#{self.id}",
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Hub outbound quarantine',
                'message': (
                    f"channel={result.get('channel_id')} found={result.get('jobs_found')} "
                    f"cancelled={result.get('cancelled')} uncertain={result.get('uncertain')} "
                    f"already_sent={result.get('already_sent')} failed={result.get('failed')}"
                ),
                'type': 'success',
                'sticky': False,
            },
        }
