# -*- coding: utf-8 -*-
import logging
import re
from datetime import timedelta

from odoo import fields, http, _
from odoo.http import request
from odoo.exceptions import ValidationError, UserError

from odoo.addons.integration_bridge_core.controllers.bridge_base import BridgeControllerBase

_logger = logging.getLogger(__name__)


class PetspotClinicPortalController(BridgeControllerBase):

    # ── Token API (Chatwoot / n8n) ──────────────────────────────────────────

    @http.route(
        '/petspot/portal/token',
        type='http',
        auth='public',
        methods=['POST', 'OPTIONS'],
        csrf=False,
        cors='*',
    )
    def portal_token_api(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({'ok': True})
        auth = self._validate_token(expected_platform=None)
        if auth == 'IP_BLOCKED':
            return self._json_response({'ok': False, 'error': 'ip_blocked'}, status=403)
        if not auth:
            return self._json_response({'ok': False, 'error': 'unauthorized'}, status=401)
        payload = self._get_json_payload(**kwargs)
        try:
            result = request.env['petspot.portal.token'].sudo().mint_from_api(payload)
        except Exception as exc:
            _logger.warning('portal token mint failed: %s', exc)
            return self._json_response({'ok': False, 'error': str(exc)}, status=400)
        return self._json_response({'ok': True, **result})

    @http.route('/petspot/portal/health', type='http', auth='public', methods=['GET'], csrf=False)
    def portal_health(self, **kwargs):
        return self._json_response({'ok': True, 'module': 'petspot_clinic_portal'})

    def _token_from_short_code(self, code, roles=None):
        Token = request.env['petspot.portal.token'].sudo()
        domain = [('short_code', '=', code)]
        if roles:
            domain.append(('role', 'in', list(roles)))
        # Prefer open tokens when duplicates exist
        rec = Token.search(domain + [('state', '=', 'open')], limit=1, order='id desc')
        if not rec:
            rec = Token.search(domain, limit=1, order='id desc')
        if not rec:
            # fallback: treat code as full token (old links)
            rec = Token.search([('token', '=', code)], limit=1)
        return rec

    @http.route(
        ['/p/b/<string:code>', '/p/book/<string:code>'],
        type='http',
        auth='public',
        methods=['GET', 'POST'],
        csrf=False,
    )
    def portal_short_book(self, code, **post):
        """Serve booking form on short URL (no redirect — WhatsApp WebView friendly)."""
        rec = self._token_from_short_code(code, roles=('patient', 'staff'))
        if not rec:
            return self._portal_error(_('رابط غير صالح'))
        return self.portal_book(rec.token, **post)

    @http.route(
        ['/p/e/<string:code>', '/p/exam/<string:code>'],
        type='http',
        auth='public',
        methods=['GET', 'POST'],
        csrf=False,
    )
    def portal_short_exam(self, code, **post):
        """Serve exam form on short URL (no redirect — WhatsApp WebView friendly)."""
        rec = self._token_from_short_code(code, roles=('vet',))
        if not rec:
            return self._portal_error(_('رابط غير صالح'))
        return self.portal_exam(rec.token, **post)

    @http.route('/p/<string:code>', type='http', auth='public', methods=['GET', 'POST'], csrf=False)
    def portal_short_auto(self, code, **post):
        rec = self._token_from_short_code(code)
        if not rec:
            return self._portal_error(_('رابط غير صالح'))
        if rec.role == 'vet':
            return self.portal_exam(rec.token, **post)
        return self.portal_book(rec.token, **post)




    @http.route(
        '/petspot/portal/lookup',
        type='http',
        auth='public',
        methods=['POST', 'OPTIONS'],
        csrf=False,
        cors='*',
    )
    def portal_lookup_api(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return self._json_response({'ok': True})
        auth = self._validate_token(expected_platform=None)
        if auth == 'IP_BLOCKED':
            return self._json_response({'ok': False, 'error': 'ip_blocked'}, status=403)
        if not auth:
            return self._json_response({'ok': False, 'error': 'unauthorized'}, status=401)
        payload = self._get_json_payload(**kwargs)
        try:
            result = request.env['petspot.portal.token'].sudo().lookup_open_appointment(payload)
        except Exception as exc:
            _logger.warning('portal lookup failed: %s', exc)
            return self._json_response({'ok': False, 'error': str(exc)}, status=400)
        return self._json_response(result)

    # ── Chatwoot dashboard app (hosted on Odoo) ─────────────────────────────

    @http.route('/petspot/portal/cw_app', type='http', auth='public', methods=['GET'], csrf=False)
    def portal_cw_app(self, **kwargs):
        """Lightweight UI; minting is done via bridge dashboard (secret stays server-side)."""
        conversation_id = kwargs.get('conversation_id') or request.params.get('conversation_id') or ''
        return request.render('petspot_clinic_portal.cw_app', {
            'conversation_id': conversation_id,
        })

    # ── Booking (patient) ───────────────────────────────────────────────────

    @http.route(
        '/petspot/portal/book/<string:token>',
        type='http',
        auth='public',
        methods=['GET', 'POST'],
        csrf=False,
        website=False,
    )
    def portal_book(self, token, **post):
        Token = request.env['petspot.portal.token'].sudo()
        rec = Token.search([('token', '=', token), ('role', 'in', ('patient', 'staff'))], limit=1)
        if not rec:
            return self._portal_error(_('رابط غير صالح'))
        try:
            rec.validate_token(allow_used=True)
        except ValidationError as exc:
            return self._portal_error(str(exc))

        form_action = request.httprequest.path

        if request.httprequest.method == 'POST':
            try:
                self._submit_booking(rec, post)
                # Render in-place (no redirect) — WhatsApp in-app browser often fails on 3xx.
                return request.render('petspot_clinic_portal.done_page', {'token_rec': rec})
            except Exception as exc:
                _logger.warning('portal book failed: %s', exc)
                return request.render('petspot_clinic_portal.book_form', {
                    'token_rec': rec,
                    'error': str(exc),
                    'species_list': request.env['pet.species'].sudo().search([]),
                    'form': post,
                    'form_action': form_action,
                })

        return request.render('petspot_clinic_portal.book_form', {
            'token_rec': rec,
            'error': False,
            'species_list': request.env['pet.species'].sudo().search([]),
            'form': {
                'owner_name': rec.prefill_owner_name or (rec.partner_id.name if rec.partner_id else ''),
                'phone': rec.prefill_phone or '',
                'pet_name': rec.prefill_pet_name or (rec.pet_id.name if rec.pet_id else ''),
            },
            'form_action': form_action,
        })


    def _submit_booking(self, token_rec, post):
        owner_name = (post.get('owner_name') or '').strip()
        phone = re.sub(r'\D', '', post.get('phone') or '')
        pet_name = (post.get('pet_name') or '').strip()
        notes = (post.get('notes') or '').strip()
        service = (post.get('service_type') or 'checkup').strip()
        species_id = post.get('species_id')
        start_raw = (post.get('start_datetime') or '').strip()

        if not owner_name or not phone or not pet_name:
            raise UserError(_('الاسم ورقم الهاتف واسم الحيوان مطلوبة.'))
        if not start_raw:
            raise UserError(_('موعد الزيارة مطلوب.'))

        start_norm = start_raw.replace('T', ' ').strip()
        if len(start_norm) == 16:
            start_norm += ':00'
        start_dt = fields.Datetime.to_datetime(start_norm[:19])

        duration = token_rec._default_duration_minutes()
        end_dt = start_dt + timedelta(minutes=duration)

        Partner = request.env['res.partner'].sudo()
        partner = token_rec.partner_id
        if not partner:
            partner = Partner.search([('phone', 'ilike', phone[-10:])], limit=1)
        if not partner:
            partner = Partner.create({
                'name': owner_name,
                'phone': phone,
                'comment': _('من بوابة PetSpot / Chatwoot'),
            })
        else:
            partner.write({'name': owner_name, 'phone': phone})

        Species = request.env['pet.species'].sudo()
        species = Species.browse(int(species_id)) if species_id else Species.browse()
        if not species:
            species = Species.search([('name', 'ilike', 'dog')], limit=1) or Species.search([], limit=1)
        if not species:
            raise UserError(_('لا يوجد نوع حيوان معرّف في النظام.'))

        Pet = request.env['pet.pet'].sudo()
        pet = token_rec.pet_id
        if not pet:
            pet = Pet.search([
                ('owner_id', '=', partner.id),
                ('name', 'ilike', pet_name),
            ], limit=1)
        if not pet:
            pet = Pet.create({
                'name': pet_name[:64],
                'species_id': species.id,
                'owner_id': partner.id,
                'behavior_notes': notes or False,
            })

        service_flags = {
            'checkup': {'is_medical': True, 'primary_type': 'checkup', 'title': 'كشف طبي'},
            'grooming': {'is_grooming': True, 'primary_type': 'other', 'title': 'تجميل / عناية'},
            'boarding': {'is_boarding': True, 'primary_type': 'other', 'title': 'إيواء'},
            'vaccination': {'is_vaccination': True, 'primary_type': 'checkup', 'title': 'تطعيم'},
            'training': {'is_training': True, 'primary_type': 'other', 'title': 'تدريب'},
            'emergency': {'is_medical': True, 'primary_type': 'emergency', 'title': 'طوارئ'},
        }
        flags = service_flags.get(service) or service_flags['checkup']

        appt_vals = {
            'pet_id': pet.id,
            'title': flags['title'],
            'primary_type': flags['primary_type'],
            'start_datetime': start_dt,
            'end_datetime': end_dt,
            'notes': notes or False,
            'state': 'confirmed',
            # Avoid broken calendar_event_id dependency on this DB
            'sync_to_calendar': False,
            'auto_create_facility': False,
        }
        # Optional audit fields (module extension)
        Appointment = request.env['pet.appointment'].sudo()
        if 'portal_source' in Appointment._fields:
            appt_vals['portal_source'] = (
                'chatwoot' if token_rec.chatwoot_conversation_id else 'portal'
            )
        if 'chatwoot_conversation_id' in Appointment._fields:
            appt_vals['chatwoot_conversation_id'] = token_rec.chatwoot_conversation_id or False
        for flag_name in ('is_medical', 'is_grooming', 'is_boarding', 'is_vaccination', 'is_training'):
            if flag_name in Appointment._fields and flags.get(flag_name):
                appt_vals[flag_name] = True
        appointment = Appointment.create(appt_vals)

        token_rec.write({
            'state': 'used',
            'partner_id': partner.id,
            'pet_id': pet.id,
            'appointment_id': appointment.id,
            'result_summary': _('موعد %s — %s — %s') % (appointment.name, pet.name, partner.name),
        })

        # Optional intake link
        if 'petspot.wa.intake' in request.env:
            try:
                request.env['petspot.wa.intake'].sudo().create({
                    'intent': 'visit',
                    'message_text': notes or str(flags['title']),
                    'sender_name': owner_name,
                    'sender_phone': phone,
                    'pet_name': pet_name,
                    'chatwoot_conversation_id': token_rec.chatwoot_conversation_id or False,
                    'chatwoot_inbox_id': token_rec.chatwoot_inbox_id or False,
                    'partner_id': partner.id,
                    'pet_id': pet.id,
                    'appointment_id': appointment.id,
                    'state': 'confirmed',
                })
            except Exception:
                _logger.warning('portal booking: intake create skipped', exc_info=True)

        # Auto-create vet exam token + post link to WhatsApp group / Chatwoot
        try:
            token_rec.create_exam_token_and_notify()
        except Exception:
            _logger.exception('portal booking: auto exam token/notify failed')



    # ── Exam (vet) ──────────────────────────────────────────────────────────

    @http.route(
        '/petspot/portal/exam/<string:token>',
        type='http',
        auth='public',
        methods=['GET', 'POST'],
        csrf=False,
        website=False,
    )
    def portal_exam(self, token, **post):
        Token = request.env['petspot.portal.token'].sudo()
        rec = Token.search([('token', '=', token), ('role', '=', 'vet')], limit=1)
        if not rec:
            return self._portal_error(_('رابط غير صالح'))
        try:
            rec.validate_token(allow_used=False)
        except ValidationError as exc:
            return self._portal_error(str(exc))

        appointment = rec.appointment_id
        pet = rec.pet_id or (appointment.pet_id if appointment else False)
        if not pet:
            return self._portal_error(_('لا يوجد حيوان مرتبط بهذا الرابط.'))

        form_action = request.httprequest.path

        if request.httprequest.method == 'POST':
            try:
                self._submit_exam(rec, pet, appointment, post)
                # Render in-place (no redirect) — WhatsApp in-app browser often fails on 3xx.
                return request.render('petspot_clinic_portal.done_page', {'token_rec': rec})
            except Exception as exc:
                _logger.warning('portal exam failed: %s', exc)
                return request.render('petspot_clinic_portal.exam_form', {
                    'token_rec': rec,
                    'pet': pet,
                    'appointment': appointment,
                    'error': str(exc),
                    'form': post,
                    'form_action': form_action,
                })

        return request.render('petspot_clinic_portal.exam_form', {
            'token_rec': rec,
            'pet': pet,
            'appointment': appointment,
            'error': False,
            'form': {},
            'form_action': form_action,
        })


    def _submit_exam(self, token_rec, pet, appointment, post):
        reason = (post.get('reason') or '').strip() or _('كشف روتيني')
        visit_vals = {
            'pet_id': pet.id,
            'appointment_id': appointment.id if appointment else False,
            'date': fields.Datetime.now(),
            'reason': reason,
            'visit_type': post.get('visit_type') or 'checkup',
            'status': 'completed',
            'subjective': post.get('subjective') or False,
            'objective': post.get('objective') or False,
            'assessment': post.get('assessment') or False,
            'plan': post.get('plan') or False,
            'diagnosis': post.get('diagnosis') or False,
            'vital_signs': post.get('vital_signs') or False,
            'medications_prescribed': post.get('medications') or False,
            'follow_up_notes': post.get('reminder_text') or False,
            'portal_source': 'chatwoot' if token_rec.chatwoot_conversation_id else 'portal',
            'chatwoot_conversation_id': token_rec.chatwoot_conversation_id or False,
        }
        follow_up = (post.get('follow_up_date') or '').strip()
        if follow_up:
            visit_vals['follow_up_date'] = follow_up

        visit = request.env['pet.medical.visit'].sudo().create(visit_vals)

        if appointment:
            appointment.sudo().write({
                'state': 'done',
                'follow_up_date': follow_up or False,
                'follow_up_notes': post.get('reminder_text') or False,
                'medical_visit_id': visit.id,
            })

        if follow_up:
            reminder_text = (post.get('reminder_text') or '').strip() or _(
                'متابعة للكشف — %s'
            ) % pet.name
            request.env['pet.notification'].sudo().create({
                'name': _('متابعة: %s') % pet.name,
                'pet_id': pet.id,
                'notification_type': 'medical_visit_due',
                'message': reminder_text,
                'priority': 'medium',
                'status': 'draft',
                'date_scheduled': follow_up + ' 09:00:00',
                'related_medical_visit_id': visit.id,
                'related_appointment_id': appointment.id if appointment else False,
                'send_email': False,
                'send_in_app': True,
            })
            # Activity for staff
            if appointment:
                try:
                    appointment.sudo().activity_schedule(
                        'mail.mail_activity_data_todo',
                        date_deadline=follow_up,
                        summary=_('متابعة %s') % pet.name,
                        note=reminder_text,
                    )
                except Exception:
                    _logger.warning('portal exam: activity schedule skipped', exc_info=True)

        token_rec.write({
            'state': 'used',
            'medical_visit_id': visit.id,
            'pet_id': pet.id,
            'result_summary': _('كشف %s — %s') % (pet.name, reason),
        })
        # Send Odoo case link so staff can open the visit and fill missing data
        try:
            token_rec.notify_odoo_case_after_exam()
        except Exception:
            _logger.exception('portal exam: Odoo case notify failed')

    # ── Done ────────────────────────────────────────────────────────────────

    @http.route(
        '/petspot/portal/done/<string:token>',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
        website=False,
    )
    def portal_done(self, token, **kwargs):
        rec = request.env['petspot.portal.token'].sudo().search([('token', '=', token)], limit=1)
        if not rec:
            return self._portal_error(_('رابط غير صالح'))
        return request.render('petspot_clinic_portal.done_page', {'token_rec': rec})

    def _portal_error(self, message):
        return request.render('petspot_clinic_portal.error_page', {'message': message})
