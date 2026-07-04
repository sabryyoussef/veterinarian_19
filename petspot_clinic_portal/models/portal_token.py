# -*- coding: utf-8 -*-
import logging
import re
import secrets
from datetime import timedelta


from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class PetspotPortalToken(models.Model):
    _name = 'petspot.portal.token'
    _description = 'PetSpot Clinic Portal Token'
    _order = 'id desc'

    name = fields.Char(default='New', required=True, copy=False)
    token = fields.Char(required=True, index=True, copy=False, default=lambda self: secrets.token_urlsafe(32))
    short_code = fields.Char(
        string='Short code',
        index=True,
        copy=False,
        default=lambda self: secrets.token_hex(4),
        help='Short public path /p/b/CODE or /p/e/CODE',
    )

    role = fields.Selection(

        [
            ('patient', 'Patient / Owner'),
            ('vet', 'Veterinarian'),
            ('staff', 'Staff'),
        ],
        required=True,
        default='patient',
        index=True,
    )
    state = fields.Selection(
        [
            ('open', 'Open'),
            ('used', 'Used'),
            ('expired', 'Expired'),
        ],
        default='open',
        required=True,
        index=True,
    )
    expires_at = fields.Datetime(required=True, index=True)
    chatwoot_conversation_id = fields.Integer(index=True)
    chatwoot_inbox_id = fields.Integer()
    partner_id = fields.Many2one('res.partner')
    pet_id = fields.Many2one('pet.pet')
    appointment_id = fields.Many2one('pet.appointment')
    medical_visit_id = fields.Many2one('pet.medical.visit')
    prefill_owner_name = fields.Char()
    prefill_phone = fields.Char()
    prefill_pet_name = fields.Char()
    access_url = fields.Char(compute='_compute_access_url')
    result_summary = fields.Text()
    exam_token_id = fields.Many2one('petspot.portal.token', string='Auto Exam Token', readonly=True)
    exam_access_url = fields.Char(string='Exam Portal URL', readonly=True)
    odoo_case_url = fields.Char(string='Odoo Case URL', readonly=True)


    _sql_constraints = [
        ('token_uniq', 'unique(token)', 'Portal token must be unique.'),
        ('short_code_uniq', 'unique(short_code)', 'Short code must be unique.'),
    ]

    @api.model
    def _generate_short_code(self):
        for _ in range(20):
            code = secrets.token_hex(4)
            if not self.search_count([('short_code', '=', code)]):
                return code
        return secrets.token_hex(6)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('petspot.portal.token') or _('New')
            if not vals.get('expires_at'):
                hours = self._ttl_hours(vals.get('role') or 'patient')
                vals['expires_at'] = fields.Datetime.now() + timedelta(hours=hours)
            if not vals.get('token'):
                vals['token'] = secrets.token_urlsafe(32)
            if not vals.get('short_code'):
                vals['short_code'] = self._generate_short_code()
        return super().create(vals_list)


    @api.model
    def _ttl_hours(self, role):
        ICP = self.env['ir.config_parameter'].sudo()
        if role == 'vet':
            return int(ICP.get_param('petspot_clinic_portal.vet_token_ttl_hours', '12'))
        return int(ICP.get_param('petspot_clinic_portal.patient_token_ttl_hours', '48'))

    @api.model
    def _default_duration_minutes(self):
        return int(
            self.env['ir.config_parameter']
            .sudo()
            .get_param('petspot_clinic_portal.default_appointment_minutes', '30')
        )

    def _public_base_url(self):
        return (
            self.env['ir.config_parameter']
            .sudo()
            .get_param('web.base.url', 'http://127.0.0.1:8027')
            .rstrip('/')
        )

    def _compute_access_url(self):
        base = self._public_base_url()
        for rec in self:
            code = rec.short_code or rec.token
            if rec.role == 'vet':
                path = f'/p/e/{code}'
            else:
                path = f'/p/b/{code}'
            rec.access_url = f'{base}{path}'


    def validate_token(self, allow_used=False):
        self.ensure_one()
        now = fields.Datetime.now()
        if self.expires_at and self.expires_at < now:
            if self.state != 'expired':
                self.state = 'expired'
            raise ValidationError(_('This link has expired.'))
        if self.state == 'expired':
            raise ValidationError(_('This link has expired.'))
        if self.state == 'used' and not allow_used:
            raise ValidationError(_('This link was already used.'))
        return True

    @api.model
    def create_patient_token(self, vals=None):
        vals = dict(vals or {})
        vals['role'] = 'patient'
        vals.setdefault('state', 'open')
        return self.create(vals)

    @api.model
    def create_vet_token(self, vals=None):
        vals = dict(vals or {})
        vals['role'] = 'vet'
        vals.setdefault('state', 'open')
        if not vals.get('appointment_id') and not vals.get('pet_id'):
            raise UserError(_('Vet token requires an appointment or pet.'))
        return self.create(vals)

    @api.model
    def lookup_open_appointment(self, payload=None):
        """Find latest open appointment for a phone / sender jid."""
        payload = payload or {}
        phone = re.sub(r'\D', '', str(payload.get('phone') or payload.get('sender_phone') or ''))
        sender_jid = str(payload.get('sender_jid') or '')
        if not phone and sender_jid:
            phone = re.sub(r'\D', '', sender_jid.split('@')[0])
        if not phone:
            return {
                'ok': True,
                'has_open_appointment': False,
                'appointment_id': False,
                'appointment_name': '',
                'pet_name': '',
                'partner_id': False,
            }

        Partner = self.env['res.partner'].sudo()
        variants = {phone, phone[-10:] if len(phone) >= 10 else phone}
        if phone.startswith('20') and len(phone) > 2:
            variants.add('0' + phone[2:])
        partners = Partner.browse()
        for v in variants:
            partners |= Partner.search([('phone', 'ilike', v)], limit=20)

        Appointment = self.env['pet.appointment'].sudo()
        domain = [('state', 'in', ('draft', 'confirmed', 'in_progress'))]
        if partners:
            domain = [('owner_id', 'in', partners.ids)] + domain
        else:
            return {
                'ok': True,
                'has_open_appointment': False,
                'appointment_id': False,
                'appointment_name': '',
                'pet_name': '',
                'partner_id': False,
            }

        appt = Appointment.search(domain, order='start_datetime desc', limit=1)

        if not appt:
            return {
                'ok': True,
                'has_open_appointment': False,
                'appointment_id': False,
                'appointment_name': '',
                'pet_name': '',
                'partner_id': partners[:1].id if partners else False,
            }
        return {
            'ok': True,
            'has_open_appointment': True,
            'appointment_id': appt.id,
            'appointment_name': appt.name,
            'pet_name': appt.pet_id.name if appt.pet_id else '',
            'partner_id': appt.owner_id.id if appt.owner_id else False,
            'start_datetime': fields.Datetime.to_string(appt.start_datetime),
            'state': appt.state,
        }

    @api.model
    def mint_from_api(self, payload):

        """Create token from Chatwoot / bridge payload."""
        if not isinstance(payload, dict):
            raise ValidationError(_('Invalid payload.'))
        role = (payload.get('role') or 'patient').strip().lower()
        if role not in ('patient', 'vet', 'staff'):
            raise ValidationError(_('Invalid role.'))

        vals = {
            'chatwoot_conversation_id': payload.get('chatwoot_conversation_id') or False,
            'chatwoot_inbox_id': payload.get('chatwoot_inbox_id') or False,
            'prefill_owner_name': payload.get('owner_name') or payload.get('sender_name') or '',
            'prefill_phone': payload.get('phone') or payload.get('sender_phone') or '',
            'prefill_pet_name': payload.get('pet_name') or '',
        }
        if payload.get('partner_id'):
            vals['partner_id'] = int(payload['partner_id'])
        if payload.get('pet_id'):
            vals['pet_id'] = int(payload['pet_id'])
        if payload.get('appointment_id'):
            vals['appointment_id'] = int(payload['appointment_id'])

        # Auto-pick latest open appointment for vet tokens when only conversation given
        if role == 'vet' and not vals.get('appointment_id'):
            appt = self._find_appointment_for_conversation(vals.get('chatwoot_conversation_id'))
            if appt:
                vals['appointment_id'] = appt.id
                vals['pet_id'] = appt.pet_id.id
                vals['partner_id'] = appt.owner_id.id

        if role == 'vet':
            token = self.create_vet_token(vals)
        else:
            token = self.create_patient_token(vals)

        return {
            'token_id': token.id,
            'token': token.token,
            'role': token.role,
            'url': token.access_url,
            'expires_at': fields.Datetime.to_string(token.expires_at),
        }

    @api.model
    def _find_appointment_for_conversation(self, conversation_id):
        if not conversation_id:
            return self.env['pet.appointment']
        return self.env['pet.appointment'].sudo().search(
            [
                ('chatwoot_conversation_id', '=', int(conversation_id)),
                ('state', 'in', ('draft', 'confirmed', 'in_progress')),
            ],
            order='start_datetime desc',
            limit=1,
        )

    def action_open_url(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': self.access_url,
            'target': 'new',
        }

    def create_exam_token_and_notify(self):
        """After booking: mint vet exam link and post it to WhatsApp / Chatwoot."""
        self.ensure_one()
        if not self.appointment_id:
            return False

        exam_token = self.create_vet_token({
            'appointment_id': self.appointment_id.id,
            'pet_id': self.pet_id.id if self.pet_id else self.appointment_id.pet_id.id,
            'partner_id': self.partner_id.id if self.partner_id else False,
            'chatwoot_conversation_id': self.chatwoot_conversation_id or False,
            'chatwoot_inbox_id': self.chatwoot_inbox_id or False,
            'prefill_owner_name': self.prefill_owner_name or (self.partner_id.name if self.partner_id else ''),
            'prefill_phone': self.prefill_phone or '',
            'prefill_pet_name': self.pet_id.name if self.pet_id else '',
        })
        exam_url = exam_token.access_url
        appt = self.appointment_id
        pet_name = appt.pet_id.name if appt.pet_id else ''
        summary = self.result_summary or ''
        if summary:
            summary = f'{summary}\n'
        summary += _('رابط الكشف: %s') % exam_url
        self.write({
            'exam_token_id': exam_token.id,
            'exam_access_url': exam_url,
            'result_summary': summary,
        })

        msg = _(
            'تم تأكيد الموعد %(appt)s للحيوان %(pet)s.\n\n'
            'للفريق الطبي: اضغط الزر «فتح نموذج الكشف»\n'
            '%(url)s'
        ) % {
            'appt': appt.name,
            'pet': pet_name,
            'url': exam_url,
        }


        self._notify_whatsapp_group(msg)
        self._notify_chatwoot(msg)
        # Also send interactive URL button when possible
        self._notify_whatsapp_exam_button(exam_url, appt.name, pet_name)
        return exam_token

    def _record_form_url(self, record):
        """Backend form URL for staff (Odoo 19 deep link)."""
        self.ensure_one()
        if not record:
            return ''
        return f'{self._public_base_url()}/odoo/{record._name}/{record.id}'

    def notify_odoo_case_after_exam(self):
        """After portal exam: send Odoo case link so staff can complete missing fields."""
        self.ensure_one()
        visit = self.medical_visit_id
        if not visit:
            return False

        case_url = self._record_form_url(visit)
        appt_url = self._record_form_url(self.appointment_id) if self.appointment_id else ''
        pet_name = visit.pet_id.name if visit.pet_id else (self.pet_id.name if self.pet_id else '')
        appt_name = self.appointment_id.name if self.appointment_id else ''

        summary = (self.result_summary or '').strip()
        if summary:
            summary = f'{summary}\n'
        summary += _('افتح الحالة في أودو لإكمال البيانات:\n%s') % case_url

        self.write({
            'odoo_case_url': case_url,
            'result_summary': summary,
        })

        msg = _(
            'تم حفظ الكشف للحيوان %(pet)s%(appt)s.\n\n'
            'أكمل البيانات الناقصة في أودو:\n%(url)s'
        ) % {
            'pet': pet_name or '—',
            'appt': (' — %s' % appt_name) if appt_name else '',
            'url': case_url,
        }
        if appt_url:
            msg += _('\n\nالموعد:\n%s') % appt_url

        self._notify_whatsapp_group(msg)
        self._notify_chatwoot(msg)
        self._notify_whatsapp_odoo_button(case_url, appt_name, pet_name)
        return case_url

    def _notify_whatsapp_odoo_button(self, case_url, appt_name, pet_name):
        import requests
        from urllib.parse import quote

        ICP = self.env['ir.config_parameter'].sudo()
        evo_url = ICP.get_param('integration_bridge.evolution_url', 'http://127.0.0.1:8080').rstrip('/')
        evo_key = ICP.get_param('integration_bridge.evolution_key', '')
        instance = ICP.get_param('integration_bridge.evolution_instance', 'sabry min')
        group_jid = ICP.get_param(
            'petspot_wa_intake.group_jid',
            '120363409395291215@g.us',
        ).strip()
        if not evo_key or not group_jid or not case_url:
            return False
        number = group_jid.split('@')[0]
        payload = {
            'number': number,
            'title': _('أكمل الحالة في أودو — %s') % (appt_name or pet_name or ''),
            'description': _('افتح كشف %s وأكمل البيانات الناقصة') % (pet_name or ''),
            'footer': 'PetSpot El Sahel',
            'buttons': [
                {'type': 'url', 'displayText': _('فتح الحالة في أودو'), 'url': case_url},
            ],
        }
        try:
            resp = requests.post(
                f"{evo_url}/message/sendButtons/{quote(instance, safe='')}",
                headers={'apikey': evo_key, 'Content-Type': 'application/json'},
                json=payload,
                timeout=20,
            )
            _logger.info('portal notify Odoo button status=%s', resp.status_code)
            return resp.ok
        except Exception:
            _logger.exception('portal notify Odoo button failed')
            return False

    def _notify_whatsapp_group(self, text):
        """Send plain text to PetSpot WhatsApp group via Evolution."""
        import requests
        from urllib.parse import quote

        ICP = self.env['ir.config_parameter'].sudo()
        evo_url = ICP.get_param('integration_bridge.evolution_url', 'http://127.0.0.1:8080').rstrip('/')
        evo_key = ICP.get_param('integration_bridge.evolution_key', '')
        instance = ICP.get_param('integration_bridge.evolution_instance', 'sabry min')
        group_jid = ICP.get_param(
            'petspot_wa_intake.group_jid',
            '120363409395291215@g.us',
        ).strip()
        if not evo_key or not group_jid:
            _logger.warning('portal notify: Evolution not configured')
            return False
        number = group_jid.split('@')[0]
        try:
            resp = requests.post(
                f"{evo_url}/message/sendText/{quote(instance, safe='')}",
                headers={'apikey': evo_key, 'Content-Type': 'application/json'},
                json={'number': number, 'text': text},
                timeout=20,
            )
            _logger.info('portal notify WA text status=%s', resp.status_code)
            return resp.ok
        except Exception:
            _logger.exception('portal notify WA text failed')
            return False

    def _notify_whatsapp_exam_button(self, exam_url, appt_name, pet_name):
        import requests
        from urllib.parse import quote

        ICP = self.env['ir.config_parameter'].sudo()
        evo_url = ICP.get_param('integration_bridge.evolution_url', 'http://127.0.0.1:8080').rstrip('/')
        evo_key = ICP.get_param('integration_bridge.evolution_key', '')
        instance = ICP.get_param('integration_bridge.evolution_instance', 'sabry min')
        group_jid = ICP.get_param(
            'petspot_wa_intake.group_jid',
            '120363409395291215@g.us',
        ).strip()
        if not evo_key or not group_jid:
            return False
        number = group_jid.split('@')[0]
        payload = {
            'number': number,
            'title': _('كشف بيطري — %s') % (appt_name or ''),
            'description': _('اضغط الزر لفتح نموذج الكشف للحيوان %s') % (pet_name or ''),
            'footer': 'PetSpot El Sahel',
            'buttons': [
                {'type': 'url', 'displayText': _('فتح نموذج الكشف'), 'url': exam_url},
            ],
        }
        try:
            resp = requests.post(
                f"{evo_url}/message/sendButtons/{quote(instance, safe='')}",
                headers={'apikey': evo_key, 'Content-Type': 'application/json'},
                json=payload,
                timeout=20,
            )
            _logger.info('portal notify WA button status=%s', resp.status_code)
            return resp.ok
        except Exception:
            _logger.exception('portal notify WA button failed')
            return False

    def _notify_chatwoot(self, text):
        """Post exam link into Chatwoot conversation when linked."""
        import requests

        self.ensure_one()
        if not self.chatwoot_conversation_id:
            return False
        ICP = self.env['ir.config_parameter'].sudo()

        def _param(key, default=''):
            val = ICP.get_param(key, default) or ''
            if val:
                return val
            # Bypass registry cache if param was inserted outside ORM
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
            _logger.warning('portal notify: Chatwoot token not configured')
            return False
        try:
            resp = requests.post(
                f"{base}/api/v1/accounts/{account}/conversations/{self.chatwoot_conversation_id}/messages",
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
            _logger.info('portal notify Chatwoot status=%s', resp.status_code)
            return resp.ok
        except Exception:
            _logger.exception('portal notify Chatwoot failed')
            return False

