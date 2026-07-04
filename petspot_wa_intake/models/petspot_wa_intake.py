# -*- coding: utf-8 -*-
import json
import logging
import re
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

PETSPOT_GROUP_JID_DEFAULT = '120363409395291215@g.us'
PETSPOT_INBOX_ID_DEFAULT = '3'


class PetspotWaIntake(models.Model):
    _name = 'petspot.wa.intake'
    _description = 'PetSpot WhatsApp Intake'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Reference', required=True, copy=False, default='New', tracking=True)
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('confirmed', 'Confirmed'),
            ('cancelled', 'Cancelled'),
            ('error', 'Error'),
        ],
        default='draft',
        required=True,
        tracking=True,
        index=True,
    )
    intent = fields.Selection(
        [
            ('pet', 'Pet'),
            ('visit', 'Visit / Appointment'),
            ('sale', 'Sale'),
            ('other', 'Other'),
            ('unknown', 'Unknown'),
        ],
        default='unknown',
        required=True,
        tracking=True,
        index=True,
    )
    message_text = fields.Text(string='Message', required=True)
    sender_name = fields.Char()
    sender_phone = fields.Char(index=True)
    sender_jid = fields.Char()
    group_jid = fields.Char(index=True)
    group_name = fields.Char()
    chatwoot_conversation_id = fields.Integer(string='Chatwoot Conversation', index=True)
    chatwoot_inbox_id = fields.Integer(string='Chatwoot Inbox')
    chatwoot_message_id = fields.Integer(string='Chatwoot Message')
    evolution_message_id = fields.Char(string='Evolution Message ID', index=True)
    pet_name = fields.Char(string='Pet Name (extracted)')
    product_name = fields.Char(string='Product (extracted)')
    amount = fields.Float(string='Amount (extracted)')
    confidence = fields.Float(string='Confidence', digits=(3, 2))
    raw_payload = fields.Text(string='Raw Payload')
    error_message = fields.Text(string='Error')

    partner_id = fields.Many2one('res.partner', string='Owner / Customer', tracking=True)
    pet_id = fields.Many2one('pet.pet', string='Pet', tracking=True)
    appointment_id = fields.Many2one('pet.appointment', string='Appointment', tracking=True)
    medical_visit_id = fields.Many2one('pet.medical.visit', string='Medical Visit', tracking=True)
    sale_order_id = fields.Many2one('sale.order', string='Sale Order', tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('petspot.wa.intake') or _('New')
            if vals.get('sender_phone'):
                vals['sender_phone'] = self._sanitize_phone(vals['sender_phone'])
            elif vals.get('sender_jid'):
                vals['sender_phone'] = self._sanitize_phone(vals['sender_jid'])
        records = super().create(vals_list)
        for rec in records:
            try:
                rec._auto_link_partner()
                rec._auto_link_pet()
            except Exception:
                _logger.warning('petspot intake auto-link failed id=%s', rec.id, exc_info=True)
        return records

    @api.model
    def _sanitize_phone(self, value):
        if not value:
            return ''
        text = str(value).split('@', 1)[0]
        return re.sub(r'\D', '', text)

    @api.model
    def _allowed_group_jid(self):
        return (
            self.env['ir.config_parameter']
            .sudo()
            .get_param('petspot_wa_intake.group_jid', PETSPOT_GROUP_JID_DEFAULT)
            .strip()
        )

    @api.model
    def _allowed_inbox_id(self):
        raw = (
            self.env['ir.config_parameter']
            .sudo()
            .get_param('petspot_wa_intake.chatwoot_inbox_id', PETSPOT_INBOX_ID_DEFAULT)
        )
        try:
            return int(raw)
        except (TypeError, ValueError):
            return int(PETSPOT_INBOX_ID_DEFAULT)

    @api.model
    def create_from_webhook(self, payload):
        """Create a draft intake from Chatwoot / n8n / Evolution payload."""
        if not isinstance(payload, dict):
            raise ValidationError(_('Payload must be a JSON object.'))

        group_jid = (payload.get('group_jid') or payload.get('whatsapp_group_jid') or '').strip()
        inbox_id = payload.get('chatwoot_inbox_id') or payload.get('inbox_id')
        try:
            inbox_id = int(inbox_id) if inbox_id not in (None, '') else False
        except (TypeError, ValueError):
            inbox_id = False

        allowed_group = self._allowed_group_jid()
        allowed_inbox = self._allowed_inbox_id()
        if group_jid and group_jid != allowed_group and inbox_id != allowed_inbox:
            raise ValidationError(
                _('Message is not from the PetSpot Sahel group/inbox (group=%s inbox=%s).')
                % (group_jid, inbox_id)
            )
        if not group_jid and inbox_id and inbox_id != allowed_inbox:
            raise ValidationError(_('Chatwoot inbox %s is not the PetSpot Sahel inbox.') % inbox_id)

        evo_msg_id = payload.get('evolution_message_id') or payload.get('message_id') or ''
        if evo_msg_id:
            existing = self.search([('evolution_message_id', '=', str(evo_msg_id))], limit=1)
            if existing:
                return existing

        intent = (payload.get('intent') or 'unknown').strip().lower()
        if intent not in dict(self._fields['intent'].selection):
            intent = self._guess_intent(payload.get('message_text') or payload.get('text') or '')

        message_text = (payload.get('message_text') or payload.get('text') or '').strip()
        if not message_text:
            message_text = '[empty message]'

        vals = {
            'intent': intent,
            'message_text': message_text,
            'sender_name': payload.get('sender_name') or payload.get('push_name') or '',
            'sender_phone': payload.get('sender_phone') or '',
            'sender_jid': payload.get('sender_jid') or '',
            'group_jid': group_jid or allowed_group,
            'group_name': payload.get('group_name') or 'Pet spot sahel branch',
            'chatwoot_conversation_id': payload.get('chatwoot_conversation_id') or False,
            'chatwoot_inbox_id': inbox_id or allowed_inbox,
            'chatwoot_message_id': payload.get('chatwoot_message_id') or False,
            'evolution_message_id': str(evo_msg_id) if evo_msg_id else False,
            'pet_name': payload.get('pet_name') or '',
            'product_name': payload.get('product_name') or '',
            'amount': float(payload.get('amount') or 0.0),
            'confidence': float(payload.get('confidence') or 0.0),
            'raw_payload': json.dumps(payload, ensure_ascii=False, default=str),
            'state': 'draft',
        }
        return self.create(vals)

    @api.model
    def _guess_intent(self, text):
        t = (text or '').lower()
        if any(k in t for k in ('بيع', 'sale', 'sold', 'فاتورة', 'invoice', 'شامبو', 'shampoo')):
            return 'sale'
        if any(k in t for k in ('زيارة', 'visit', 'موعد', 'appointment', 'كشف', 'checkup')):
            return 'visit'
        if any(k in t for k in ('حيوان', 'pet', 'قطة', 'كلب', 'dog', 'cat', 'تسجيل')):
            return 'pet'
        return 'unknown'

    def _auto_link_partner(self):
        Partner = self.env['res.partner'].sudo()
        for rec in self:
            if rec.partner_id or not rec.sender_phone:
                continue
            phone = rec.sender_phone
            variants = {phone, phone[-10:] if len(phone) >= 10 else phone}
            if phone.startswith('20') and len(phone) > 2:
                variants.add('0' + phone[2:])
            partner = Partner.browse()
            phone_fields = ['phone']
            if 'mobile' in Partner._fields:
                phone_fields.append('mobile')
            for v in variants:
                domain = [(phone_fields[0], 'ilike', v)]
                for fname in phone_fields[1:]:
                    domain = ['|', (fname, 'ilike', v)] + domain
                partner = Partner.search(domain, limit=1)
                if partner:
                    break
            if partner:
                rec.partner_id = partner.id

    def _auto_link_pet(self):
        Pet = self.env['pet.pet'].sudo()
        for rec in self:
            if rec.pet_id or not rec.pet_name:
                continue
            domain = [('name', 'ilike', rec.pet_name.strip())]
            if rec.partner_id:
                domain = ['&', ('owner_id', '=', rec.partner_id.id)] + domain
            pet = Pet.search(domain, limit=1)
            if pet:
                rec.pet_id = pet.id

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        self.write({'state': 'draft', 'error_message': False})

    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft intakes can be confirmed.'))
            try:
                rec._confirm_one()
                rec.write({'state': 'confirmed', 'error_message': False})
            except Exception as exc:
                _logger.exception('petspot intake confirm failed id=%s', rec.id)
                rec.write({'state': 'error', 'error_message': str(exc)})
                raise

    def _confirm_one(self):
        self.ensure_one()
        if self.intent == 'pet':
            self._confirm_pet()
        elif self.intent == 'visit':
            self._confirm_visit()
        elif self.intent == 'sale':
            self._confirm_sale()
        else:
            raise UserError(
                _('Intent "%s" cannot auto-create records. Set intent to Pet, Visit, or Sale.')
                % self.intent
            )

    def _ensure_partner(self):
        self.ensure_one()
        if self.partner_id:
            return self.partner_id
        phone = self.sender_phone or self._sanitize_phone(self.sender_jid)
        name = self.sender_name or phone or _('WhatsApp Contact')
        partner_vals = {
            'name': name,
            'phone': phone or False,
            'comment': _('Created from PetSpot WhatsApp intake %s') % self.name,
        }
        Partner = self.env['res.partner'].sudo()
        if 'mobile' in Partner._fields:
            partner_vals['mobile'] = phone or False
        partner = Partner.create(partner_vals)
        self.partner_id = partner.id
        return partner

    def _default_species(self):
        Species = self.env['pet.species'].sudo()
        species = Species.search([('name', 'ilike', 'dog')], limit=1)
        if not species:
            species = Species.search([], limit=1)
        if not species:
            raise UserError(_('No pet species configured. Create a species (e.g. Dog) first.'))
        return species

    def _confirm_pet(self):
        self.ensure_one()
        if self.pet_id:
            return self.pet_id
        partner = self._ensure_partner()
        pet_name = (self.pet_name or '').strip()
        if not pet_name:
            # Try first word after common markers, else use message snippet
            pet_name = (self.message_text or '').strip().split()[0] if self.message_text else _('Pet')
        pet = self.env['pet.pet'].sudo().create({
            'name': pet_name[:64],
            'species_id': self._default_species().id,
            'owner_id': partner.id,
            'behavior_notes': _('From WhatsApp intake %s:\n%s') % (self.name, self.message_text),
        })
        self.pet_id = pet.id
        return pet

    def _confirm_visit(self):
        self.ensure_one()
        # Reuse portal-created appointment/visit — do not duplicate
        if self.appointment_id:
            return self.appointment_id
        if self.medical_visit_id and self.medical_visit_id.appointment_id:
            self.appointment_id = self.medical_visit_id.appointment_id.id
            return self.appointment_id
        pet = self.pet_id
        if not pet:
            if self.pet_name:
                pet = self._confirm_pet()
            else:
                raise UserError(_('Link or set a pet before confirming a visit.'))
        now = fields.Datetime.now()
        appointment = self.env['pet.appointment'].sudo().create({
            'pet_id': pet.id,
            'title': _('WA visit: %s') % (self.pet_name or pet.name),
            'primary_type': 'checkup',
            'is_medical': True,
            'start_datetime': now,
            'end_datetime': now + timedelta(minutes=30),
            'notes': self.message_text,
            'state': 'draft',
            'sync_to_calendar': False,
            'auto_create_facility': False,
        })
        self.appointment_id = appointment.id
        return appointment

    def _confirm_sale(self):
        self.ensure_one()
        partner = self._ensure_partner()
        Product = self.env['product.product'].sudo()
        product = False
        if self.product_name:
            product = Product.search([('name', 'ilike', self.product_name.strip())], limit=1)
        if not product:
            product = Product.search([('sale_ok', '=', True)], limit=1)
        if not product:
            raise UserError(_('No sellable product found. Create a product or set product_name.'))

        order = self.env['sale.order'].sudo().create({
            'partner_id': partner.id,
            'client_order_ref': self.name,
            'note': self.message_text,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': 1,
                'price_unit': self.amount or product.lst_price,
                'name': self.product_name or product.display_name,
            })],
        })
        self.sale_order_id = order.id
        return order
