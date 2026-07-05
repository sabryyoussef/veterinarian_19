# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

# field_name -> Arabic label
FIELD_LABELS_AR = {
    'diagnosis': 'التشخيص',
    'assessment': 'التقييم / Assessment',
    'plan': 'خطة العلاج',
    'vet_id': 'الطبيب المسؤول',
    'cost': 'التكلفة',
    'payment_status': 'حالة الدفع',
    'follow_up_date': 'موعد المتابعة',
    'vet_notes': 'ملاحظات داخلية',
    'subjective': 'شكوى المالك',
    'objective': 'الفحص',
}


class PetMedicalVisit(models.Model):
    _name = 'pet.medical.visit'
    _inherit = ['pet.medical.visit', 'petspot.notify.mixin']

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
    portal_incomplete = fields.Boolean(
        string='Portal Incomplete',
        default=False,
        index=True,
        tracking=True,
        help='Visit created from portal and still needs staff completion.',
    )
    portal_missing_fields = fields.Text(string='Missing Fields', readonly=True)
    portal_completed_at = fields.Datetime(string='Portal Completed At', readonly=True)
    portal_completion_notified = fields.Boolean(default=False, copy=False)
    portal_incomplete_reminded_at = fields.Datetime(copy=False)
    follow_up_reminded_at = fields.Datetime(copy=False)
    portal_sale_order_id = fields.Many2one('sale.order', string='Portal Sale Draft', copy=False)
    portal_registration_token_id = fields.Many2one(
        'petspot.portal.token',
        string='Staff Registration Token',
        copy=False,
        index=True,
    )

    @api.model
    def _portal_required_fields(self):
        ICP = self.env['ir.config_parameter'].sudo()
        raw = ICP.get_param(
            'petspot_clinic_portal.required_visit_fields',
            'diagnosis,assessment,plan,vet_id',
        )
        return [f.strip() for f in (raw or '').split(',') if f.strip()]

    def _portal_field_is_missing(self, field_name):
        self.ensure_one()
        if field_name not in self._fields:
            return False
        val = self[field_name]
        if field_name == 'payment_status':
            return val in (False, 'pending', 'cancelled')
        if field_name == 'cost':
            return not val or float(val) <= 0
        if isinstance(val, bool):
            return not val
        return not val

    def _compute_portal_missing_list(self):
        self.ensure_one()
        missing = []
        for fname in self._portal_required_fields():
            if self._portal_field_is_missing(fname):
                missing.append(FIELD_LABELS_AR.get(fname, fname))
        return missing

    def refresh_portal_incomplete_state(self, notify_complete=True):
        """Recalc missing fields; auto-complete when checklist is satisfied."""
        for visit in self:
            # Only track portal/chatwoot visits or already-flagged incomplete ones
            if visit.portal_source == 'backend' and not visit.portal_incomplete:
                continue
            missing = visit._compute_portal_missing_list()
            missing_text = '\n'.join(f'- {m}' for m in missing) if missing else ''
            was_incomplete = visit.portal_incomplete
            vals = {'portal_missing_fields': missing_text or False}
            if missing:
                vals['portal_incomplete'] = True
                if visit.status == 'completed' and was_incomplete:
                    vals['status'] = 'in_progress'
            else:
                vals['portal_incomplete'] = False
                if was_incomplete or visit.portal_source in ('portal', 'chatwoot'):
                    vals['status'] = 'completed'
                    if not visit.portal_completed_at:
                        vals['portal_completed_at'] = fields.Datetime.now()
            visit.with_context(skip_portal_incomplete_recalc=True).write(vals)

            if missing:
                # Keep appointment open while visit incomplete
                if visit.appointment_id and visit.appointment_id.state == 'done':
                    visit.appointment_id.with_context(skip_portal_incomplete_recalc=True).write({
                        'state': 'in_progress',
                    })
            else:
                if visit.appointment_id and visit.appointment_id.state in ('confirmed', 'in_progress'):
                    visit.appointment_id.with_context(skip_portal_incomplete_recalc=True).write({
                        'state': 'done',
                    })
                if notify_complete and was_incomplete and not visit.portal_completion_notified:
                    visit._notify_portal_case_completed()

    def _notify_portal_case_completed(self):
        for visit in self:
            pet = visit.pet_id.name if visit.pet_id else '—'
            owner = visit.pet_id.owner_id.name if visit.pet_id and visit.pet_id.owner_id else '—'
            url = visit._petspot_record_form_url(visit)
            msg = _(
                'تم إكمال الحالة في Odoo.\n\n'
                'الحيوان: %(pet)s\n'
                'العميل: %(owner)s\n'
                '%(url)s'
            ) % {'pet': pet, 'owner': owner, 'url': url}
            visit.petspot_notify_whatsapp_group(msg)
            if visit.chatwoot_conversation_id:
                visit.petspot_notify_chatwoot(visit.chatwoot_conversation_id, msg)
            visit.with_context(skip_portal_incomplete_recalc=True).write({
                'portal_completion_notified': True,
            })
            # Optional sale draft
            visit._maybe_create_portal_sale_draft()

    def _maybe_create_portal_sale_draft(self):
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('petspot_clinic_portal.auto_sale_draft', 'False').lower() not in ('1', 'true', 'yes'):
            return False
        if self.portal_sale_order_id or not self.pet_id or not self.pet_id.owner_id:
            return False
        if 'sale.order' not in self.env:
            return False
        try:
            order = self.env['sale.order'].sudo().create({
                'partner_id': self.pet_id.owner_id.id,
                'note': _('من كشف بوابة PetSpot — %s') % (self.reason or self.display_name),
            })
            self.with_context(skip_portal_incomplete_recalc=True).write({
                'portal_sale_order_id': order.id,
            })
            return order
        except Exception:
            _logger.warning('portal sale draft skipped', exc_info=True)
            return False

    def action_mark_portal_complete(self):
        """Manual override: mark case complete even if checklist incomplete."""
        for visit in self:
            visit.with_context(skip_portal_incomplete_recalc=True).write({
                'portal_incomplete': False,
                'portal_missing_fields': False,
                'portal_completed_at': fields.Datetime.now(),
                'status': 'completed',
            })
            if visit.appointment_id:
                visit.appointment_id.write({'state': 'done'})
            visit.message_post(body=_('تم إكمال الحالة يدويًا من بوابة العيادة.'))
            if not visit.portal_completion_notified:
                visit._notify_portal_case_completed()
        return True

    def action_open_odoo_case(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'pet.medical.visit',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get('skip_portal_incomplete_recalc'):
            return res
        tracked = set(self._portal_required_fields()) | {
            'portal_source', 'status', 'diagnosis', 'assessment', 'plan', 'vet_id',
        }
        if tracked.intersection(vals.keys()) or 'portal_incomplete' in vals:
            self.refresh_portal_incomplete_state()
        return res

    @api.model
    def cron_portal_reminders(self):
        """Appointment / follow-up / incomplete-case WhatsApp reminders."""
        ICP = self.env['ir.config_parameter'].sudo()
        incomplete_hours = int(ICP.get_param('petspot_clinic_portal.incomplete_remind_hours', '4'))
        now = fields.Datetime.now()
        cutoff = now - timedelta(hours=incomplete_hours)

        # Incomplete portal cases older than N hours
        incomplete = self.search([
            ('portal_incomplete', '=', True),
            ('create_date', '<=', cutoff),
            '|',
            ('portal_incomplete_reminded_at', '=', False),
            ('portal_incomplete_reminded_at', '<=', cutoff),
        ], limit=30)
        for visit in incomplete:
            pet = visit.pet_id.name if visit.pet_id else '—'
            owner = visit.pet_id.owner_id.name if visit.pet_id and visit.pet_id.owner_id else '—'
            url = visit._petspot_record_form_url(visit)
            missing = visit.portal_missing_fields or '—'
            msg = _(
                'تنبيه: حالة كشف ما زالت غير مكتملة.\n\n'
                'الحيوان: %(pet)s\n'
                'العميل: %(owner)s\n\n'
                'النواقص:\n%(missing)s\n\n'
                'رابط الحالة:\n%(url)s'
            ) % {'pet': pet, 'owner': owner, 'missing': missing, 'url': url}
            visit.petspot_notify_whatsapp_group(msg)
            visit.with_context(skip_portal_incomplete_recalc=True).write({
                'portal_incomplete_reminded_at': now,
            })

        # Follow-up due today
        today = fields.Date.today()
        followups = self.search([
            ('follow_up_date', '=', today),
            ('follow_up_reminded_at', '=', False),
            ('status', 'in', ('completed', 'in_progress', 'scheduled')),
        ], limit=30)
        for visit in followups:
            pet = visit.pet_id.name if visit.pet_id else '—'
            owner = visit.pet_id.owner_id.name if visit.pet_id and visit.pet_id.owner_id else '—'
            msg = _(
                'تذكير متابعة حالة:\n\n'
                'الحيوان: %(pet)s\n'
                'العميل: %(owner)s\n'
                'تاريخ المتابعة: %(date)s\n\n'
                'يرجى التواصل مع العميل أو تحديث الحالة في Odoo.\n%(url)s'
            ) % {
                'pet': pet,
                'owner': owner,
                'date': visit.follow_up_date,
                'url': visit._petspot_record_form_url(visit),
            }
            visit.petspot_notify_whatsapp_group(msg)
            visit.with_context(skip_portal_incomplete_recalc=True).write({
                'follow_up_reminded_at': now,
            })

        # Appointment reminders (tomorrow)
        Appointment = self.env['pet.appointment'].sudo()
        if hasattr(Appointment, 'cron_portal_appointment_reminders'):
            Appointment.cron_portal_appointment_reminders()
