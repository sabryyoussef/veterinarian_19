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
        rec = self._token_from_short_code(code, roles=('patient', 'staff', 'staff_register'))
        if not rec:
            return self._portal_error(_('رابط غير صالح'))
        return self.portal_book(rec.token, **post)

    @http.route(
        ['/p/s/r/<string:code>', '/p/staff/register/<string:code>'],
        type='http',
        auth='public',
        methods=['GET', 'POST'],
        csrf=False,
    )
    def portal_short_staff_register(self, code, **post):
        rec = self._token_from_short_code(code, roles=('staff', 'staff_register'))
        if not rec:
            return self._portal_error(_('رابط غير صالح'))
        return self.portal_book(rec.token, staff_mode=True, **post)

    @http.route(
        ['/p/s/p/<string:code>', '/p/staff/payment/<string:code>'],
        type='http',
        auth='public',
        methods=['GET', 'POST'],
        csrf=False,
    )
    def portal_short_staff_payment(self, code, **post):
        rec = self._token_from_short_code(code, roles=('staff_payment',))
        if not rec:
            return self._portal_error(_('رابط غير صالح'))
        return self.portal_payment_placeholder(rec.token, **post)

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
        if rec.role == 'staff_payment':
            return self.portal_payment_placeholder(rec.token, **post)
        if rec.role in ('staff', 'staff_register'):
            return self.portal_book(rec.token, staff_mode=True, **post)
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
    def portal_book(self, token, staff_mode=False, **post):
        Token = request.env['petspot.portal.token'].sudo()
        rec = Token.search([
            ('token', '=', token),
            ('role', 'in', ('patient', 'staff', 'staff_register')),
        ], limit=1)
        if not rec:
            return self._portal_error(_('رابط غير صالح'))
        try:
            rec.validate_token(allow_used=True)
        except ValidationError as exc:
            return self._portal_error(str(exc))

        staff_mode = staff_mode or rec.role in ('staff', 'staff_register')
        form_action = request.httprequest.path

        Slot = request.env['petspot.clinic.slot'].sudo()
        Slot.ensure_upcoming_slots(days=7)
        slots = Slot.get_available_slots(limit=30)

        if request.httprequest.method == 'POST':
            try:
                self._submit_booking(rec, post)
                return request.render('petspot_clinic_portal.done_page', {
                    'token_rec': rec,
                    'staff_mode': staff_mode,
                })
            except Exception as exc:
                _logger.warning('portal book failed: %s', exc)
                return request.render('petspot_clinic_portal.book_form', {
                    'token_rec': rec,
                    'error': str(exc),
                    'species_list': request.env['pet.species'].sudo().search([]),
                    'slots': slots,
                    'form': post,
                    'form_action': form_action,
                    'staff_mode': staff_mode,
                })

        return request.render('petspot_clinic_portal.book_form', {
            'token_rec': rec,
            'error': False,
            'species_list': request.env['pet.species'].sudo().search([]),
            'slots': slots,
            'form': {
                'owner_name': rec.prefill_owner_name or (rec.partner_id.name if rec.partner_id else ''),
                'phone': rec.prefill_phone or '',
                'pet_name': rec.prefill_pet_name or (rec.pet_id.name if rec.pet_id else ''),
            },
            'form_action': form_action,
            'staff_mode': staff_mode,
        })

    def portal_payment_placeholder(self, token, **kwargs):
        """Phase 2: read-only payment status; full payment form in Phase 5."""
        Token = request.env['petspot.portal.token'].sudo()
        rec = Token.search([('token', '=', token), ('role', '=', 'staff_payment')], limit=1)
        if not rec:
            return self._portal_error(_('رابط غير صالح'))
        try:
            rec.validate_token(allow_used=True)
        except ValidationError as exc:
            return self._portal_error(str(exc))

        visit = rec.medical_visit_id
        appt = rec.appointment_id or (visit.appointment_id if visit else False)
        payment = Token._payment_summary_for_visit(visit) if visit else Token._payment_summary_for_appointment(appt)

        return request.render('petspot_clinic_portal.payment_placeholder', {
            'token_rec': rec,
            'visit': visit,
            'appointment': appt,
            'payment': payment,
        })

    def _submit_booking(self, token_rec, post):
        from odoo.addons.petspot_clinic_portal.models.phone_utils import normalize_eg_phone

        owner_name = (post.get('owner_name') or '').strip()
        phone = normalize_eg_phone(post.get('phone') or '')
        pet_name = (post.get('pet_name') or '').strip()
        notes = (post.get('notes') or '').strip()
        service = (post.get('service_type') or 'checkup').strip()
        species_id = post.get('species_id')
        breed_name = (post.get('breed_name') or '').strip()
        age_years = (post.get('age_years') or '').strip()
        weight_kg = (post.get('weight_kg') or '').strip()
        slot_id = post.get('slot_id')

        if not owner_name or not phone or not pet_name:
            raise UserError(_('الاسم ورقم الهاتف واسم الحيوان مطلوبة.'))

        Slot = request.env['petspot.clinic.slot'].sudo()
        slot = Slot.browse()
        if slot_id:
            slot = Slot.browse(int(slot_id))
            if not slot.exists():
                raise UserError(_('الموعد المختار غير صالح.'))
            slot.reserve_for_appointment()
            start_dt = slot.start_datetime
            end_dt = slot.end_datetime
        else:
            # Fallback free datetime if no slots configured
            start_raw = (post.get('start_datetime') or '').strip()
            if not start_raw:
                raise UserError(_('اختر موعدًا من القائمة.'))
            start_norm = start_raw.replace('T', ' ').strip()
            if len(start_norm) == 16:
                start_norm += ':00'
            start_dt = fields.Datetime.to_datetime(start_norm[:19])
            duration = token_rec._default_duration_minutes()
            end_dt = start_dt + timedelta(minutes=duration)

        Token = request.env['petspot.portal.token'].sudo()
        partner = token_rec.partner_id or Token.find_or_create_partner(phone, owner_name)

        Species = request.env['pet.species'].sudo()
        species = Species.browse(int(species_id)) if species_id else Species.browse()
        if not species:
            species = Species.search([('name', 'ilike', 'dog')], limit=1) or Species.search([], limit=1)
        if not species:
            raise UserError(_('لا يوجد نوع حيوان معرّف في النظام.'))

        breed_id = False
        if breed_name and 'pet.breed' in request.env:
            breed = request.env['pet.breed'].sudo().search([
                ('name', 'ilike', breed_name),
            ], limit=1)
            if breed:
                breed_id = breed.id

        extra = {'notes': notes, 'breed_id': breed_id}
        pet = token_rec.pet_id or Token.find_or_create_pet(partner, pet_name, species, extra)
        if age_years and 'date_of_birth' in pet._fields:
            try:
                years = float(age_years)
                # store approximate note only
                note = (pet.behavior_notes or '') + (f'\nعمر تقريبي: {years} سنة')
                pet.write({'behavior_notes': note.strip()})
            except Exception:
                pass
        if weight_kg and 'pet.weight.history' in request.env:
            try:
                request.env['pet.weight.history'].sudo().create({
                    'pet_id': pet.id,
                    'weight_kg': float(weight_kg),
                    'date': fields.Date.today(),
                })
            except Exception:
                _logger.warning('portal booking: weight history skipped', exc_info=True)

        service_flags = {
            'checkup': {'is_medical': True, 'primary_type': 'checkup', 'title': 'كشف طبي'},
            'grooming': {'is_grooming': True, 'primary_type': 'other', 'title': 'تجميل / عناية'},
            'boarding': {'is_boarding': True, 'primary_type': 'other', 'title': 'إيواء'},
            'vaccination': {'is_vaccination': True, 'primary_type': 'checkup', 'title': 'تطعيم'},
            'training': {'is_training': True, 'primary_type': 'other', 'title': 'تدريب'},
            'emergency': {'is_medical': True, 'primary_type': 'emergency', 'title': 'طوارئ'},
        }
        flags = service_flags.get(service) or service_flags['checkup']

        Appointment = request.env['pet.appointment'].sudo()
        appt_vals = {
            'pet_id': pet.id,
            'title': flags['title'],
            'primary_type': flags['primary_type'],
            'start_datetime': start_dt,
            'end_datetime': end_dt,
            'notes': notes or False,
            'state': 'confirmed',
            # Portal appointments: calendar sync permanently gated (broken path in pet_management)
            'sync_to_calendar': False,
            'auto_create_facility': False,
            'portal_source': 'chatwoot' if token_rec.chatwoot_conversation_id else 'portal',
            'chatwoot_conversation_id': token_rec.chatwoot_conversation_id or False,
        }
        if slot:
            appt_vals['portal_slot_id'] = slot.id
        resource_id = Appointment._portal_default_resource()
        if resource_id:
            appt_vals['resource_id'] = resource_id
        for flag_name in ('is_medical', 'is_grooming', 'is_boarding', 'is_vaccination', 'is_training'):
            if flag_name in Appointment._fields and flags.get(flag_name):
                appt_vals[flag_name] = True
        appointment = Appointment.create(appt_vals)

        token_rec.write({
            'state': 'used',
            'partner_id': partner.id,
            'pet_id': pet.id,
            'appointment_id': appointment.id,
            'prefill_phone': phone,
            'prefill_owner_name': owner_name,
            'result_summary': _('موعد %s — %s — %s') % (appointment.name, pet.name, partner.name),
        })

        try:
            token_rec.link_or_create_intake(intent='visit', message_text=notes or flags['title'])
        except Exception:
            _logger.warning('portal booking: intake link skipped', exc_info=True)

        request.env['petspot.portal.submit.log'].sudo().create({
            'name': _('حجز %s') % appointment.name,
            'submit_type': 'book',
            'token_id': token_rec.id,
            'phone': phone,
            'partner_id': partner.id,
            'pet_id': pet.id,
            'appointment_id': appointment.id,
            'chatwoot_conversation_id': token_rec.chatwoot_conversation_id or False,
            'source': 'chatwoot' if token_rec.chatwoot_conversation_id else 'whatsapp_group',
        })

        try:
            token_rec.create_exam_token_and_notify()
        except Exception:
            _logger.exception('portal booking: auto exam token/notify failed')

        if token_rec.role in ('staff', 'staff_register'):
            appointment.sudo().write({'portal_registration_token_id': token_rec.id})

    def _portal_products_for_category(self, param_key, default_name):
        ICP = request.env['ir.config_parameter'].sudo()
        cat_name = ICP.get_param(param_key, default_name)
        Category = request.env['product.category'].sudo()
        category = Category.search([('name', 'ilike', cat_name)], limit=1)
        domain = [('sale_ok', '=', True), ('active', '=', True)]
        if category:
            domain.append(('categ_id', 'child_of', category.id))
        return request.env['product.product'].sudo().search(domain, order='name', limit=100)

    def _portal_exam_catalog(self):
        ICP = request.env['ir.config_parameter'].sudo()
        consultation = request.env['product.product'].sudo().browse()
        default_id = ICP.get_param('petspot_clinic_portal.default_consultation_product_id', '')
        if default_id:
            try:
                consultation = request.env['product.product'].sudo().browse(int(default_id))
                if not consultation.exists():
                    consultation = request.env['product.product'].sudo().browse()
            except Exception:
                consultation = request.env['product.product'].sudo().browse()
        if not consultation:
            consultation = self._portal_products_for_category(
                'petspot_clinic_portal.category_services', 'Services'
            )[:1]
        return {
            'consultation_product': consultation,
            'service_products': self._portal_products_for_category(
                'petspot_clinic_portal.category_services', 'Services'
            ),
            'medicine_products': self._portal_products_for_category(
                'petspot_clinic_portal.category_medicines', 'Drugs'
            ),
            'vaccine_products': self._portal_products_for_category(
                'petspot_clinic_portal.category_vaccines', 'Drugs'
            ),
        }

    def _parse_exam_line_posts(self, post, line_type):
        """Parse repeated product/qty fields from portal exam form."""
        Product = request.env['product.product'].sudo()
        product_ids = request.httprequest.form.getlist('%s_product_id' % line_type)
        quantities = request.httprequest.form.getlist('%s_qty' % line_type)
        lines = []
        for idx, pid_raw in enumerate(product_ids):
            if not pid_raw:
                continue
            try:
                product = Product.browse(int(pid_raw))
            except Exception:
                continue
            if not product.exists():
                continue
            qty_raw = quantities[idx] if idx < len(quantities) else '1'
            try:
                qty = float(qty_raw or 1)
            except Exception:
                qty = 1.0
            if qty <= 0:
                continue
            lines.append({
                'line_type': line_type,
                'product_id': product.id,
                'name': product.display_name,
                'quantity': qty,
                'price_unit': product.list_price,
            })
        return lines

    def _build_visit_line_vals(self, visit, post):
        line_vals = []
        consultation_product_id = post.get('consultation_product_id')
        consultation_fee = post.get('consultation_fee')
        if consultation_product_id:
            product = request.env['product.product'].sudo().browse(int(consultation_product_id))
            if product.exists():
                price = product.list_price
                if consultation_fee:
                    try:
                        price = float(consultation_fee)
                    except Exception:
                        pass
                line_vals.append({
                    'line_type': 'consultation',
                    'product_id': product.id,
                    'name': product.display_name,
                    'quantity': 1.0,
                    'price_unit': price,
                })
        elif consultation_fee:
            try:
                fee = float(consultation_fee)
            except Exception:
                fee = 0.0
            if fee > 0:
                line_vals.append({
                    'line_type': 'consultation',
                    'name': _('رسوم الكشف'),
                    'quantity': 1.0,
                    'price_unit': fee,
                })
        for line_type in ('service', 'medicine', 'vaccine'):
            line_vals.extend(self._parse_exam_line_posts(post, line_type))
        discount_amount = 0.0
        if post.get('discount_amount'):
            try:
                discount_amount = max(float(post.get('discount_amount') or 0), 0.0)
            except Exception:
                discount_amount = 0.0
        return line_vals, discount_amount



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
        catalog = self._portal_exam_catalog()

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
                    'catalog': catalog,
                })

        return request.render('petspot_clinic_portal.exam_form', {
            'token_rec': rec,
            'pet': pet,
            'appointment': appointment,
            'error': False,
            'form': {},
            'form_action': form_action,
            'catalog': catalog,
        })


    def _submit_exam(self, token_rec, pet, appointment, post):
        reason = (post.get('reason') or '').strip() or _('كشف روتيني')
        source = 'chatwoot' if token_rec.chatwoot_conversation_id else 'portal'
        visit_vals = {
            'pet_id': pet.id,
            'appointment_id': appointment.id if appointment else False,
            'date': fields.Datetime.now(),
            'reason': reason,
            'visit_type': post.get('visit_type') or 'checkup',
            # Incomplete until staff fills required checklist in Odoo
            'status': 'in_progress',
            'portal_incomplete': True,
            'subjective': post.get('subjective') or False,
            'objective': post.get('objective') or False,
            'assessment': post.get('assessment') or False,
            'plan': post.get('plan') or False,
            'diagnosis': post.get('diagnosis') or False,
            'vital_signs': post.get('vital_signs') or False,
            'medications_prescribed': post.get('medications') or False,
            'follow_up_notes': post.get('reminder_text') or False,
            'portal_source': source,
            'chatwoot_conversation_id': token_rec.chatwoot_conversation_id or False,
        }
        follow_up = (post.get('follow_up_date') or '').strip()
        if follow_up:
            visit_vals['follow_up_date'] = follow_up

        Visit = request.env['pet.medical.visit'].sudo()
        visit = Visit.with_context(skip_portal_incomplete_recalc=True).create(visit_vals)

        line_vals, discount_amount = self._build_visit_line_vals(visit, post)
        if line_vals:
            visit.write({
                'line_ids': [(0, 0, vals) for vals in line_vals],
                'discount_amount': discount_amount,
            })

        registration_token_id = False
        if appointment and appointment.portal_registration_token_id:
            registration_token_id = appointment.portal_registration_token_id.id
        elif token_rec.role == 'staff_register':
            registration_token_id = token_rec.id
        if registration_token_id:
            visit.write({'portal_registration_token_id': registration_token_id})

        visit.refresh_portal_incomplete_state(notify_complete=False)

        if appointment:
            appointment.sudo().write({
                'state': 'in_progress',
                'follow_up_date': follow_up or False,
                'follow_up_notes': post.get('reminder_text') or False,
                'medical_visit_id': visit.id,
            })

        # Optional exam photos
        files = request.httprequest.files.getlist('photos') if request.httprequest.files else []
        for upload in files:
            if not upload or not upload.filename:
                continue
            try:
                import base64
                data = base64.b64encode(upload.read())
                request.env['ir.attachment'].sudo().create({
                    'name': upload.filename,
                    'datas': data,
                    'res_model': 'pet.medical.visit',
                    'res_id': visit.id,
                    'mimetype': upload.content_type or 'application/octet-stream',
                })
            except Exception:
                _logger.warning('portal exam: photo attach skipped', exc_info=True)

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
            'result_summary': _('كشف %s — %s (غير مكتمل) — الإجمالي %s') % (
                pet.name, reason, visit.amount_total or visit.cost or 0,
            ),
        })

        try:
            token_rec.link_or_create_intake(intent='visit', message_text=reason)
        except Exception:
            _logger.warning('portal exam: intake link skipped', exc_info=True)

        request.env['petspot.portal.submit.log'].sudo().create({
            'name': _('كشف %s') % pet.name,
            'submit_type': 'exam',
            'token_id': token_rec.id,
            'phone': token_rec.prefill_phone or '',
            'partner_id': token_rec.partner_id.id if token_rec.partner_id else (
                pet.owner_id.id if pet.owner_id else False
            ),
            'pet_id': pet.id,
            'appointment_id': appointment.id if appointment else False,
            'medical_visit_id': visit.id,
            'chatwoot_conversation_id': token_rec.chatwoot_conversation_id or False,
            'source': 'chatwoot' if token_rec.chatwoot_conversation_id else 'whatsapp_group',
            'notes': visit.portal_missing_fields or '',
        })

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
