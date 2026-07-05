# -*- coding: utf-8 -*-
import logging
from urllib.parse import quote

from odoo import models, _

_logger = logging.getLogger(__name__)


class PetspotNotifyMixin(models.AbstractModel):
    """Shared Evolution WhatsApp + Chatwoot notify helpers."""

    _name = 'petspot.notify.mixin'
    _description = 'PetSpot Notify Mixin'

    def _petspot_icp(self):
        return self.env['ir.config_parameter'].sudo()

    def _petspot_group_jid(self):
        return self._petspot_icp().get_param(
            'petspot_wa_intake.group_jid',
            '120363409395291215@g.us',
        ).strip()

    def _petspot_public_base_url(self):
        ICP = self._petspot_icp()
        explicit = (ICP.get_param('petspot_clinic_portal.public_base_url') or '').strip().rstrip('/')
        if explicit:
            return explicit
        return ICP.get_param('web.base.url', 'https://drpaws.ai').rstrip('/')

    def _petspot_evolution_number(self, group_jid=None):
        """Evolution group sends need the full @g.us JID."""
        jid = (group_jid or self._petspot_group_jid() or '').strip()
        if jid.endswith('@g.us'):
            return jid
        return jid.split('@', 1)[0] if jid else ''

    def _petspot_record_form_url(self, record):
        if not record:
            return ''
        return f'{self._petspot_public_base_url()}/odoo/{record._name}/{record.id}'

    def petspot_notify_whatsapp_group(self, text):
        import requests

        ICP = self._petspot_icp()
        evo_url = ICP.get_param('integration_bridge.evolution_url', 'http://127.0.0.1:8080').rstrip('/')
        evo_key = ICP.get_param('integration_bridge.evolution_key', '')
        instance = ICP.get_param('integration_bridge.evolution_instance', 'sabry min')
        group_jid = self._petspot_group_jid()
        number = self._petspot_evolution_number(group_jid)
        if not evo_key or not number:
            _logger.warning('petspot notify: Evolution not configured')
            return False
        try:
            resp = requests.post(
                f"{evo_url}/message/sendText/{quote(instance, safe='')}",
                headers={'apikey': evo_key, 'Content-Type': 'application/json'},
                json={'number': number, 'text': text},
                timeout=20,
            )
            _logger.info('petspot notify WA text status=%s', resp.status_code)
            return resp.ok
        except Exception:
            _logger.exception('petspot notify WA text failed')
            return False

    def petspot_notify_whatsapp_button(self, title, description, display_text, url):
        import requests

        ICP = self._petspot_icp()
        evo_url = ICP.get_param('integration_bridge.evolution_url', 'http://127.0.0.1:8080').rstrip('/')
        evo_key = ICP.get_param('integration_bridge.evolution_key', '')
        instance = ICP.get_param('integration_bridge.evolution_instance', 'sabry min')
        group_jid = self._petspot_group_jid()
        number = self._petspot_evolution_number(group_jid)
        if not evo_key or not number or not url:
            return False
        payload = {
            'number': number,
            'title': title,
            'description': description,
            'footer': 'PetSpot El Sahel',
            'buttons': [{'type': 'url', 'displayText': display_text, 'url': url}],
        }
        try:
            resp = requests.post(
                f"{evo_url}/message/sendButtons/{quote(instance, safe='')}",
                headers={'apikey': evo_key, 'Content-Type': 'application/json'},
                json=payload,
                timeout=20,
            )
            _logger.info('petspot notify WA button status=%s', resp.status_code)
            return resp.ok
        except Exception:
            _logger.exception('petspot notify WA button failed')
            return False

    def petspot_notify_chatwoot(self, conversation_id, text):
        import requests

        if not conversation_id:
            return False
        ICP = self._petspot_icp()

        def _param(key, default=''):
            val = ICP.get_param(key, default) or ''
            if val:
                return val
            self.env.cr.execute(
                'SELECT value FROM ir_config_parameter WHERE key = %s LIMIT 1',
                (key,),
            )
            row = self.env.cr.fetchone()
            return (row[0] if row else default) or default

        base = _param('petspot_clinic_portal.chatwoot_url', 'http://127.0.0.1:3000').rstrip('/')
        token = _param('petspot_clinic_portal.chatwoot_api_token', '')
        account = _param('petspot_clinic_portal.chatwoot_account_id', '2')
        if not token:
            _logger.warning('petspot notify: Chatwoot token not configured')
            return False
        try:
            resp = requests.post(
                f"{base}/api/v1/accounts/{account}/conversations/{int(conversation_id)}/messages",
                headers={
                    'api_access_token': token,
                    'Content-Type': 'application/json',
                },
                json={
                    'content': text,
                    'message_type': 'outgoing',
                    'private': False,
                },
                timeout=20,
            )
            _logger.info('petspot notify Chatwoot status=%s', resp.status_code)
            return resp.ok
        except Exception:
            _logger.exception('petspot notify Chatwoot failed')
            return False
