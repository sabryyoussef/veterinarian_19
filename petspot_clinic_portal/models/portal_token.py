# -*- coding: utf-8 -*-
import logging
import secrets
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from .phone_utils import normalize_eg_phone, phone_match_variants, normalize_pet_name

_logger = logging.getLogger(__name__)


class PetspotPortalToken(models.Model):
    _name = 'petspot.portal.token'
    _description = 'PetSpot Clinic Portal Token'
    _inherit = ['petspot.notify.mixin']
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
            ('staff', 'Staff (legacy)'),
            ('staff_register', 'Staff — Register visit'),
            ('staff_payment', 'Staff — Collect payment'),
        ],
        required=True,
        default='patient',
        index=True,
    )
    portal_action = fields.Selection(
        [
            ('book', 'Booking'),
            ('register', 'Staff register'),
            ('exam', 'Exam'),
            ('payment', 'Payment'),
        ],
        string='Portal action',
        help='Drives short URL routing for staff/client flows.',
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
    intake_id = fields.Many2one('petspot.wa.intake', string='Linked Intake')
    prefill_owner_name = fields.Char()
    prefill_phone = fields.Char()
    prefill_pet_name = fields.Char()
    access_url = fields.Char(compute='_compute_access_url')
    result_summary = fields.Text()
    exam_token_id = fields.Many2one('petspot.portal.token', string='Auto Exam Token', readonly=True)
    exam_access_url = fields.Char(string='Exam Portal URL', readonly=True)
    odoo_case_url = fields.Char(string='Odoo Case URL', readonly=True)

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
            if vals.get('prefill_phone'):
                vals['prefill_phone'] = normalize_eg_phone(vals['prefill_phone'])
        return super().create(vals_list)

    @api.model
    def _ttl_hours(self, role):
        ICP = self.env['ir.config_parameter'].sudo()
        if role == 'vet':
            return int(ICP.get_param('petspot_clinic_portal.vet_token_ttl_hours', '12'))
        if role == 'staff_payment':
            return int(ICP.get_param('petspot_clinic_portal.staff_payment_token_ttl_hours', '4'))
        if role in ('staff', 'staff_register'):
            return int(ICP.get_param('petspot_clinic_portal.staff_register_token_ttl_hours', '24'))
        return int(ICP.get_param('petspot_clinic_portal.patient_token_ttl_hours', '48'))

    @api.model
    def _default_duration_minutes(self):
        return int(
            self.env['ir.config_parameter']
            .sudo()
            .get_param('petspot_clinic_portal.default_appointment_minutes', '30')
        )

    def _public_base_url(self):
        return self._petspot_public_base_url()

    def _live_portal_path(self, role=None):
        self.ensure_one()
        code = self.short_code or self.token
        role = role or self.role
        if role == 'vet':
            return f'/p/e/{code}'
        if role in ('staff', 'staff_register'):
            return f'/p/s/r/{code}'
        if role == 'staff_payment':
            return f'/p/s/p/{code}'
        return f'/p/b/{code}'

    def _live_portal_url(self, role=None):
        self.ensure_one()
        return f'{self._public_base_url()}{self._live_portal_path(role=role)}'

    def _compute_access_url(self):
        for rec in self:
            rec.access_url = rec._live_portal_url()

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
    def find_partner_by_phone(self, phone, name=None):
        Partner = self.env['res.partner'].sudo()
        variants = phone_match_variants(phone)
        if not variants:
            return Partner.browse()
        phone_fields = ['phone']
        if 'mobile' in Partner._fields:
            phone_fields.append('mobile')
        partners = Partner.browse()
        for v in variants:
            domain = [(phone_fields[0], 'ilike', v)]
            for fname in phone_fields[1:]:
                domain = ['|', (fname, 'ilike', v)] + domain
            partners |= Partner.search(domain, limit=20)
        # Prefer exact last-10 match
        norm = normalize_eg_phone(phone)
        last10 = norm[-10:] if len(norm) >= 10 else norm
        for p in partners:
            for fname in phone_fields:
                field = p[fname]
                if field and normalize_eg_phone(field)[-10:] == last10:
                    return p
        return partners[:1]

    @api.model
    def find_or_create_partner(self, phone, name):
        Partner = self.env['res.partner'].sudo()
        partner = self.find_partner_by_phone(phone, name)
        norm = normalize_eg_phone(phone)
        display_phone = ('0' + norm[2:]) if norm.startswith('20') and len(norm) > 2 else norm
        if partner:
            vals = {}
            if name and partner.name != name:
                vals['name'] = name
            if display_phone and not partner.phone:
                vals['phone'] = display_phone
            if display_phone and 'mobile' in Partner._fields and not partner.mobile:
                vals['mobile'] = display_phone
            if vals:
                partner.write(vals)
            return partner
        vals = {
            'name': name or display_phone or _('عميل PetSpot'),
            'phone': display_phone or False,
            'comment': _('من بوابة PetSpot / Chatwoot'),
        }
        if 'mobile' in Partner._fields:
            vals['mobile'] = display_phone or False
        return Partner.create(vals)

    @api.model
    def find_or_create_pet(self, partner, pet_name, species, extra=None):
        Pet = self.env['pet.pet'].sudo()
        extra = extra or {}
        key = normalize_pet_name(pet_name)
        pets = Pet.search([('owner_id', '=', partner.id)], limit=50)
        for pet in pets:
            if normalize_pet_name(pet.name) == key:
                vals = {}
                if extra.get('breed_id') and not pet.breed_id:
                    vals['breed_id'] = extra['breed_id']
                if vals:
                    pet.write(vals)
                return pet
        vals = {
            'name': (pet_name or _('حيوان'))[:64],
            'species_id': species.id,
            'owner_id': partner.id,
        }
        if extra.get('breed_id'):
            vals['breed_id'] = extra['breed_id']
        if extra.get('notes'):
            vals['behavior_notes'] = extra['notes']
        return Pet.create(vals)

    @api.model
    def create_patient_token(self, vals=None):
        vals = dict(vals or {})
        vals['role'] = 'patient'
        vals.setdefault('portal_action', 'book')
        vals.setdefault('state', 'open')
        return self.create(vals)

    @api.model
    def create_vet_token(self, vals=None):
        vals = dict(vals or {})
        vals['role'] = 'vet'
        vals.setdefault('portal_action', 'exam')
        vals.setdefault('state', 'open')
        if not vals.get('appointment_id') and not vals.get('pet_id'):
            raise UserError(_('Vet token requires an appointment or pet.'))
        return self.create(vals)

    @api.model
    def create_staff_register_token(self, vals=None):
        vals = dict(vals or {})
        vals['role'] = 'staff_register'
        vals.setdefault('portal_action', 'register')
        vals.setdefault('state', 'open')
        return self.create(vals)

    @api.model
    def create_staff_payment_token(self, vals=None):
        vals = dict(vals or {})
        vals['role'] = 'staff_payment'
        vals.setdefault('portal_action', 'payment')
        vals.setdefault('state', 'open')
        if not vals.get('medical_visit_id') and not vals.get('appointment_id'):
            raise UserError(_('Payment token requires a visit or appointment.'))
        return self.create(vals)

    @api.model
    def _payment_summary_for_visit(self, visit):
        """Read-only payment snapshot for WhatsApp lookup (no accounting writes)."""
        if not visit:
            return {}
        appt = visit.appointment_id
        invoice = appt.invoice_id if appt else self.env['account.move']
        amount_total = visit.amount_total or visit.cost or 0.0
        if invoice:
            amount_total = invoice.amount_total
        return {
            'visit_payment_status': visit.payment_status or 'pending',
            'visit_cost': visit.cost or 0.0,
            'visit_amount_total': visit.amount_total or visit.cost or 0.0,
            'visit_line_count': len(visit.line_ids),
            'appointment_payment_status': appt.payment_status if appt else '',
            'invoice_id': invoice.id if invoice else False,
            'invoice_name': invoice.name if invoice else '',
            'invoice_state': invoice.state if invoice else '',
            'amount_total': amount_total,
            'amount_paid': 0.0,
            'amount_residual': amount_total,
        }

    @api.model
    def _payment_summary_for_appointment(self, appt):
        if not appt:
            return {}
        invoice = appt.invoice_id
        amount_total = appt.invoice_amount if appt.invoice_id else 0.0
        visit = appt.medical_visit_id
        if visit and visit.cost and not amount_total:
            amount_total = visit.cost
        return {
            'visit_payment_status': visit.payment_status if visit else '',
            'visit_cost': visit.cost if visit else 0.0,
            'appointment_payment_status': appt.payment_status or 'pending',
            'invoice_id': invoice.id if invoice else False,
            'invoice_name': invoice.name if invoice else '',
            'invoice_state': invoice.state if invoice else '',
            'amount_total': amount_total,
            'amount_paid': 0.0,
            'amount_residual': amount_total,
        }

        vals = dict(vals or {})
        vals['role'] = 'vet'
        vals.setdefault('state', 'open')
        if not vals.get('appointment_id') and not vals.get('pet_id'):
            raise UserError(_('Vet token requires an appointment or pet.'))
        return self.create(vals)

    @api.model
    def lookup_open_appointment(self, payload=None):
        """Find latest open appointment / incomplete visit for a phone."""
        payload = payload or {}
        phone = normalize_eg_phone(
            payload.get('phone') or payload.get('sender_phone') or ''
        )
        sender_jid = str(payload.get('sender_jid') or '')
        if not phone and sender_jid:
            phone = normalize_eg_phone(sender_jid)
        if not phone:
            return self._empty_status()

        partner = self.find_partner_by_phone(phone)
        Appointment = self.env['pet.appointment'].sudo()
        Visit = self.env['pet.medical.visit'].sudo()

        appt = Appointment.browse()
        if partner:
            appt = Appointment.search(
                [
                    ('owner_id', '=', partner.id),
                    ('state', 'in', ('draft', 'confirmed', 'in_progress')),
                ],
                order='start_datetime desc',
                limit=1,
            )

        incomplete = Visit.browse()
        if partner:
            incomplete = Visit.search(
                [
                    ('pet_id.owner_id', '=', partner.id),
                    ('portal_incomplete', '=', True),
                ],
                order='id desc',
                limit=1,
            )

        # Exam pending: open appointment without incomplete visit yet, or open exam token
        exam_url = ''
        exam_pending = False
        if appt:
            open_exam = self.search(
                [
                    ('appointment_id', '=', appt.id),
                    ('role', '=', 'vet'),
                    ('state', '=', 'open'),
                ],
                order='id desc',
                limit=1,
            )
            if open_exam:
                exam_url = open_exam._live_portal_url()
                exam_pending = True
            else:
                book_tok = self.search(
                    [
                        ('appointment_id', '=', appt.id),
                        ('role', '=', 'patient'),
                        ('exam_token_id', '!=', False),
                    ],
                    order='id desc',
                    limit=1,
                )
                if book_tok and book_tok.exam_token_id.state == 'open':
                    exam_url = book_tok.exam_token_id._live_portal_url()
                    exam_pending = True

        case_url = ''
        missing = ''
        visit_id = False
        visit_status = ''
        if incomplete:
            case_url = incomplete._petspot_record_form_url(incomplete)
            missing = incomplete.portal_missing_fields or ''
            visit_id = incomplete.id
            visit_status = incomplete.status
        elif appt and appt.medical_visit_id:
            visit = appt.medical_visit_id
            case_url = visit._petspot_record_form_url(visit)
            visit_id = visit.id
            visit_status = visit.status
            if visit.portal_incomplete:
                missing = visit.portal_missing_fields or ''

        payment = {}
        if incomplete:
            payment = self._payment_summary_for_visit(incomplete)
        elif visit_id:
            payment = self._payment_summary_for_visit(Visit.browse(visit_id))
        elif appt:
            payment = self._payment_summary_for_appointment(appt)

        payment_defaults = {
            'visit_payment_status': '',
            'visit_cost': 0.0,
            'appointment_payment_status': '',
            'invoice_id': False,
            'invoice_name': '',
            'invoice_state': '',
            'amount_total': 0.0,
            'amount_paid': 0.0,
            'amount_residual': 0.0,
        }

        result = {
            'ok': True,
            'has_open_appointment': bool(appt),
            'appointment_id': appt.id if appt else False,
            'appointment_name': appt.name if appt else '',
            'appointment_state': appt.state if appt else '',
            'pet_name': (appt.pet_id.name if appt and appt.pet_id else (
                incomplete.pet_id.name if incomplete and incomplete.pet_id else ''
            )),
            'partner_id': partner.id if partner else False,
            'partner_name': partner.name if partner else '',
            'start_datetime': fields.Datetime.to_string(appt.start_datetime) if appt else '',
            'state': appt.state if appt else '',
            'exam_pending': exam_pending,
            'exam_url': exam_url,
            'visit_id': visit_id,
            'visit_status': visit_status,
            'portal_incomplete': bool(incomplete) or bool(missing),
            'portal_missing_fields': missing,
            'odoo_case_url': case_url,
        }
        result.update({**payment_defaults, **payment})
        return result

    @api.model
    def _empty_status(self):
        return {
            'ok': True,
            'has_open_appointment': False,
            'appointment_id': False,
            'appointment_name': '',
            'appointment_state': '',
            'pet_name': '',
            'partner_id': False,
            'partner_name': '',
            'exam_pending': False,
            'exam_url': '',
            'visit_id': False,
            'visit_status': '',
            'portal_incomplete': False,
            'portal_missing_fields': '',
            'odoo_case_url': '',
            'visit_payment_status': '',
            'visit_cost': 0.0,
            'appointment_payment_status': '',
            'invoice_id': False,
            'invoice_name': '',
            'invoice_state': '',
            'amount_total': 0.0,
            'amount_paid': 0.0,
            'amount_residual': 0.0,
        }

    @api.model
    def mint_from_api(self, payload):
        if not isinstance(payload, dict):
            raise ValidationError(_('Invalid payload.'))
        role = (payload.get('role') or 'patient').strip().lower()
        if role == 'staff':
            role = 'staff_register'
        allowed = ('patient', 'vet', 'staff_register', 'staff_payment')
        if role not in allowed:
            raise ValidationError(_('Invalid role.'))

        vals = {
            'chatwoot_conversation_id': payload.get('chatwoot_conversation_id') or False,
            'chatwoot_inbox_id': payload.get('chatwoot_inbox_id') or False,
            'prefill_owner_name': payload.get('owner_name') or payload.get('sender_name') or '',
            'prefill_phone': normalize_eg_phone(
                payload.get('phone') or payload.get('sender_phone') or ''
            ),
            'prefill_pet_name': payload.get('pet_name') or '',
        }
        if payload.get('partner_id'):
            vals['partner_id'] = int(payload['partner_id'])
        if payload.get('pet_id'):
            vals['pet_id'] = int(payload['pet_id'])
        if payload.get('appointment_id'):
            vals['appointment_id'] = int(payload['appointment_id'])
        if payload.get('visit_id') or payload.get('medical_visit_id'):
            vals['medical_visit_id'] = int(payload.get('visit_id') or payload.get('medical_visit_id'))

        if role == 'vet' and not vals.get('appointment_id'):
            appt = self._find_appointment_for_conversation(vals.get('chatwoot_conversation_id'))
            if not appt and vals.get('prefill_phone'):
                status = self.lookup_open_appointment({'phone': vals['prefill_phone']})
                if status.get('appointment_id'):
                    vals['appointment_id'] = status['appointment_id']
            if appt:
                vals['appointment_id'] = appt.id
                vals['pet_id'] = appt.pet_id.id
                vals['partner_id'] = appt.owner_id.id

        if role == 'staff_payment' and not vals.get('medical_visit_id'):
            if vals.get('appointment_id'):
                appt = self.env['pet.appointment'].sudo().browse(vals['appointment_id'])
                if appt.medical_visit_id:
                    vals['medical_visit_id'] = appt.medical_visit_id.id
            elif vals.get('prefill_phone'):
                status = self.lookup_open_appointment({'phone': vals['prefill_phone']})
                if status.get('visit_id'):
                    vals['medical_visit_id'] = status['visit_id']
                if status.get('appointment_id'):
                    vals['appointment_id'] = status['appointment_id']

        if role == 'vet':
            vals['portal_action'] = 'exam'
            token = self.create_vet_token(vals)
        elif role == 'staff_register':
            token = self.create_staff_register_token(vals)
        elif role == 'staff_payment':
            token = self.create_staff_payment_token(vals)
        else:
            vals['portal_action'] = 'book'
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
        self.ensure_one()
        if not self.appointment_id:
            return False

        exam_token = self.create_vet_token({
            'appointment_id': self.appointment_id.id,
            'pet_id': self.pet_id.id if self.pet_id else self.appointment_id.pet_id.id,
            'partner_id': self.partner_id.id if self.partner_id else False,
            'chatwoot_conversation_id': self.chatwoot_conversation_id or False,
            'chatwoot_inbox_id': self.chatwoot_inbox_id or False,
            'intake_id': self.intake_id.id if self.intake_id else False,
            'prefill_owner_name': self.prefill_owner_name or (self.partner_id.name if self.partner_id else ''),
            'prefill_phone': self.prefill_phone or '',
            'prefill_pet_name': self.pet_id.name if self.pet_id else '',
        })
        exam_url = exam_token._live_portal_url()
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
            'للفريق الطبي: افتح نموذج الكشف:\n'
            '%(url)s'
        ) % {'appt': appt.name, 'pet': pet_name, 'url': exam_url}

        self.petspot_notify_whatsapp_group(msg)
        self.petspot_notify_chatwoot(self.chatwoot_conversation_id, msg)
        self.petspot_notify_whatsapp_button(
            _('كشف بيطري — %s') % (appt.name or ''),
            _('افتح نموذج الكشف للحيوان %s') % (pet_name or ''),
            _('فتح نموذج الكشف'),
            exam_url,
        )
        return exam_token

    def _record_form_url(self, record):
        return self._petspot_record_form_url(record)

    def notify_odoo_case_after_exam(self):
        self.ensure_one()
        visit = self.medical_visit_id
        if not visit:
            return False

        visit.refresh_portal_incomplete_state(notify_complete=False)
        case_url = self._record_form_url(visit)
        appt_url = self._record_form_url(self.appointment_id) if self.appointment_id else ''
        pet_name = visit.pet_id.name if visit.pet_id else (self.pet_id.name if self.pet_id else '')
        appt_name = self.appointment_id.name if self.appointment_id else ''
        missing = visit.portal_missing_fields or _('لا توجد نواقص مسجلة')

        summary = (self.result_summary or '').strip()
        if summary:
            summary = f'{summary}\n'
        summary += _('افتح الحالة في أودو لإكمال البيانات:\n%s') % case_url

        self.write({
            'odoo_case_url': case_url,
            'result_summary': summary,
        })

        msg = _(
            'تم إنشاء حالة كشف جديدة في Odoo.\n\n'
            'الحيوان: %(pet)s%(appt)s\n\n'
            'الحالة ما زالت غير مكتملة وتحتاج مراجعة:\n\n'
            'النواقص:\n%(missing)s\n\n'
            'رابط الحالة:\n%(url)s'
        ) % {
            'pet': pet_name or '—',
            'appt': (' — %s' % appt_name) if appt_name else '',
            'missing': missing,
            'url': case_url,
        }
        if appt_url:
            msg += _('\n\nالموعد:\n%s') % appt_url

        self.petspot_notify_whatsapp_group(msg)
        self.petspot_notify_chatwoot(self.chatwoot_conversation_id, msg)
        self.petspot_notify_whatsapp_button(
            _('أكمل الحالة في أودو — %s') % (appt_name or pet_name or ''),
            _('افتح كشف %s وأكمل البيانات الناقصة') % (pet_name or ''),
            _('فتح الحالة في أودو'),
            case_url,
        )
        return case_url

    def link_or_create_intake(self, intent='visit', message_text=''):
        """Link portal action to a single WA intake record."""
        self.ensure_one()
        Intake = self.env['petspot.wa.intake'].sudo()
        intake = self.intake_id
        if not intake and self.chatwoot_conversation_id:
            intake = Intake.search(
                [('chatwoot_conversation_id', '=', self.chatwoot_conversation_id)],
                order='id desc',
                limit=1,
            )
        if not intake and self.prefill_phone:
            intake = Intake.search(
                [('sender_phone', 'ilike', self.prefill_phone[-10:])],
                order='id desc',
                limit=1,
            )
        vals = {
            'intent': intent,
            'message_text': message_text or intent,
            'sender_name': self.prefill_owner_name or '',
            'sender_phone': self.prefill_phone or '',
            'chatwoot_conversation_id': self.chatwoot_conversation_id or False,
            'chatwoot_inbox_id': self.chatwoot_inbox_id or False,
            'partner_id': self.partner_id.id if self.partner_id else False,
            'pet_id': self.pet_id.id if self.pet_id else False,
            'appointment_id': self.appointment_id.id if self.appointment_id else False,
            'state': 'confirmed',
        }
        if 'medical_visit_id' in Intake._fields and self.medical_visit_id:
            vals['medical_visit_id'] = self.medical_visit_id.id
        if intake:
            intake.write({k: v for k, v in vals.items() if v})
        else:
            intake = Intake.create(vals)
        self.intake_id = intake.id
        return intake
