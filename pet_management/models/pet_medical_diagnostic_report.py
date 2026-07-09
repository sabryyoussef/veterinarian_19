# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class PetMedicalDiagnosticReport(models.Model):
    _name = 'pet.medical.diagnostic.report'
    _description = 'Pet Medical Diagnostic Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    DIAGNOSTIC_TYPE_SELECTION = [
        ('ultrasound', 'Ultrasound / Sonar'),
        ('xray', 'X-Ray'),
        ('lab_blood', 'Lab - Blood'),
        ('lab_chemistry', 'Lab - Biochemistry'),
        ('lab_urine', 'Lab - Urinalysis'),
        ('lab_fecal', 'Lab - Fecal Exam'),
        ('other', 'Other'),
    ]
    STATUS_SELECTION = [
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
    ]

    name = fields.Char(required=True, tracking=True)
    visit_id = fields.Many2one(
        'pet.medical.visit',
        required=True,
        ondelete='cascade',
        index=True,
        tracking=True,
    )
    visit_line_id = fields.Many2one(
        'pet.medical.visit.line',
        string='Visit Line',
        ondelete='set null',
        index=True,
    )
    pet_id = fields.Many2one(
        related='visit_id.pet_id',
        store=True,
        readonly=True,
        index=True,
    )
    product_id = fields.Many2one('product.product', tracking=True)
    diagnostic_type = fields.Selection(
        selection=DIAGNOSTIC_TYPE_SELECTION,
        required=True,
        default='other',
        tracking=True,
    )
    date = fields.Datetime(
        required=True,
        default=fields.Datetime.now,
        tracking=True,
    )
    vet_employee_id = fields.Many2one(
        'hr.employee', string='Veterinarian (Employee)', tracking=True, index=True,
        default=lambda self: self.env.user.employee_id.id if self.env.user.employee_id else False,
        help="Veterinarian (employee) responsible for this diagnostic — used for performance evaluation",
    )
    vet_id = fields.Many2one('res.partner', string='Veterinarian', tracking=True)
    status = fields.Selection(
        selection=STATUS_SELECTION,
        default='draft',
        required=True,
        tracking=True,
    )
    result_summary = fields.Text(tracking=True)
    findings = fields.Html()
    interpretation = fields.Text()
    is_abnormal = fields.Boolean(tracking=True)
    result_values = fields.Text(
        help='Structured values, one per line. Example: WBC=12.5 x10^9/L',
    )
    report_attachment = fields.Binary(attachment=True)
    report_attachment_filename = fields.Char()
    image_ids = fields.Many2many(
        'ir.attachment',
        'pet_medical_diagnostic_report_attachment_rel',
        'report_id',
        'attachment_id',
        string='Images',
    )
    company_id = fields.Many2one(
        related='visit_id.company_id',
        store=True,
        readonly=True,
    )

    @api.model
    def diagnostic_type_for_product(self, product):
        if not product:
            return 'other'
        code = (product.default_code or '').upper()
        mapping = {
            'DIAG-US': 'ultrasound',
            'DIAG-XR': 'xray',
            'DIAG-LAB-CBC': 'lab_blood',
            'DIAG-LAB-CHEM': 'lab_chemistry',
            'DIAG-LAB-URINE': 'lab_urine',
            'DIAG-LAB-FECAL': 'lab_fecal',
        }
        if code in mapping:
            return mapping[code]
        name = (product.display_name or '').lower()
        if 'sonar' in name or 'ultrasound' in name or 'سونار' in name:
            return 'ultrasound'
        if 'x-ray' in name or 'xray' in name or 'أشعة' in name:
            return 'xray'
        if 'cbc' in name or 'blood' in name:
            return 'lab_blood'
        if 'chem' in name or 'biochem' in name:
            return 'lab_chemistry'
        if 'urine' in name or 'urinalysis' in name:
            return 'lab_urine'
        if 'fecal' in name or 'stool' in name:
            return 'lab_fecal'
        return 'other'

    @api.model
    def create_from_visit_line(self, line):
        if not line or line.line_type != 'diagnostic':
            return self.browse()
        existing = self.search([('visit_line_id', '=', line.id)], limit=1)
        if existing:
            return existing
        product = line.product_id
        return self.create({
            'name': line.name or (product.display_name if product else _('Diagnostic Report')),
            'visit_id': line.visit_id.id,
            'visit_line_id': line.id,
            'product_id': product.id if product else False,
            'diagnostic_type': self.diagnostic_type_for_product(product),
            'date': fields.Datetime.now(),
            'vet_id': line.visit_id.vet_id.id if line.visit_id.vet_id else False,
            'status': 'draft',
        })
