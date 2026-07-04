# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, _


class PetAppointment(models.Model):
    _name = 'pet.appointment'
    _inherit = ['pet.appointment', 'petspot.notify.mixin']

    portal_source = fields.Selection(
        [
            ('backend', 'Backend'),
            ('portal', 'Clinic Portal'),
            ('chatwoot', 'Chatwoot / WhatsApp'),
        ],
        default='backend',
        string='Portal Source',
    )
    chatwoot_conversation_id = fields.Integer(index=True, string='Chatwoot Conversation')
    portal_slot_id = fields.Many2one('petspot.clinic.slot', string='Portal Slot', index=True)
    appointment_reminded_at = fields.Datetime(copy=False)

    @api.model
    def _portal_default_resource(self):
        ICP = self.env['ir.config_parameter'].sudo()
        rid = ICP.get_param('petspot_clinic_portal.default_resource_id', '')
        if rid:
            try:
                partner = self.env['res.partner'].sudo().browse(int(rid))
                if partner.exists():
                    return partner.id
            except Exception:
                pass
        return False

    @api.model
    def cron_portal_appointment_reminders(self):
        """Remind group about appointments in the next 24 hours."""
        now = fields.Datetime.now()
        soon = now + timedelta(hours=24)
        appts = self.search([
            ('state', 'in', ('confirmed', 'in_progress')),
            ('start_datetime', '>=', now),
            ('start_datetime', '<=', soon),
            ('appointment_reminded_at', '=', False),
            ('portal_source', 'in', ('portal', 'chatwoot')),
        ], limit=30)
        for appt in appts:
            pet = appt.pet_id.name if appt.pet_id else '—'
            owner = appt.owner_id.name if appt.owner_id else '—'
            msg = _(
                'تذكير بموعد كشف PetSpot:\n\n'
                'العميل: %(owner)s\n'
                'الحيوان: %(pet)s\n'
                'الموعد: %(when)s\n\n'
                'يرجى التأكيد أو المتابعة.\n%(url)s'
            ) % {
                'owner': owner,
                'pet': pet,
                'when': fields.Datetime.to_string(appt.start_datetime),
                'url': appt._petspot_record_form_url(appt),
            }
            appt.petspot_notify_whatsapp_group(msg)
            appt.write({'appointment_reminded_at': now})
