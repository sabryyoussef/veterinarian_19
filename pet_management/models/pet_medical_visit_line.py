# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


DIAGNOSTIC_PRODUCT_CODES = {
    'DIAG-US',
    'DIAG-XR',
    'DIAG-LAB-CBC',
    'DIAG-LAB-CHEM',
    'DIAG-LAB-URINE',
    'DIAG-LAB-FECAL',
}


class PetMedicalVisitLine(models.Model):
    _name = 'pet.medical.visit.line'
    _description = 'Pet Medical Visit Line'
    _order = 'sequence, id'

    visit_id = fields.Many2one(
        'pet.medical.visit',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    line_type = fields.Selection(
        [
            ('consultation', 'Consultation'),
            ('service', 'Service'),
            ('medicine', 'Medicine'),
            ('vaccine', 'Vaccine'),
            ('diagnostic', 'Diagnostic'),
        ],
        required=True,
        default='service',
    )
    product_id = fields.Many2one('product.product', string='Product')
    name = fields.Char(required=True)
    quantity = fields.Float(default=1.0, digits='Product Unit')
    price_unit = fields.Float(digits='Product Price')
    discount = fields.Float(string='Discount %', digits='Discount')
    price_subtotal = fields.Float(
        compute='_compute_price_subtotal',
        store=True,
        digits='Product Price',
    )
    diagnostic_report_id = fields.Many2one(
        'pet.medical.diagnostic.report',
        string='Diagnostic Report',
        readonly=True,
        copy=False,
    )
    company_id = fields.Many2one(
        related='visit_id.company_id',
        store=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        related='visit_id.currency_id',
        store=True,
        readonly=True,
    )

    @api.depends('quantity', 'price_unit', 'discount')
    def _compute_price_subtotal(self):
        for line in self:
            subtotal = (line.quantity or 0.0) * (line.price_unit or 0.0)
            if line.discount:
                subtotal *= (1.0 - (line.discount / 100.0))
            line.price_subtotal = subtotal

    @api.model
    def _is_diagnostic_product(self, product):
        if not product:
            return False
        code = (product.default_code or '').upper()
        if code in DIAGNOSTIC_PRODUCT_CODES or code.startswith('DIAG-'):
            return True
        name = (product.display_name or '').lower()
        keywords = ('sonar', 'ultrasound', 'x-ray', 'xray', 'lab', 'cbc', 'urinalysis', 'fecal', 'سونار', 'أشعة')
        return any(keyword in name for keyword in keywords)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for line in self:
            if line.product_id:
                line.name = line.product_id.display_name
                line.price_unit = line.product_id.list_price
                if line.line_type != 'consultation' and self._is_diagnostic_product(line.product_id):
                    line.line_type = 'diagnostic'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('visit_id'):
                raise ValidationError(
                    _("Save the Medical Visit before adding service lines.")
                )
        lines = super().create(vals_list)
        lines._ensure_diagnostic_reports()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if {'line_type', 'product_id'}.intersection(vals):
            self._ensure_diagnostic_reports()
        return res

    def _ensure_diagnostic_reports(self):
        Report = self.env['pet.medical.diagnostic.report']
        for line in self:
            if line.line_type != 'diagnostic':
                continue
            report = Report.create_from_visit_line(line)
            if report and line.diagnostic_report_id != report:
                line.diagnostic_report_id = report.id
