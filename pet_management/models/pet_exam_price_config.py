# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PetExamPriceConfig(models.Model):
    _name = 'pet.exam.price.config'
    _description = 'Exam Price by Visit Type'
    _order = 'visit_type, company_id'

    VISIT_TYPE_SELECTION = [
        ('checkup', 'Regular Exam'),
        ('emergency', 'Emergency Exam'),
        ('home_visit', 'Home Visit'),
        ('vaccination', 'Vaccination'),
        ('surgery', 'Surgery'),
        ('dental', 'Dental'),
        ('grooming', 'Grooming'),
        ('other', 'Other'),
    ]

    visit_type = fields.Selection(
        selection=VISIT_TYPE_SELECTION,
        required=True,
        index=True,
    )
    price = fields.Float(required=True, default=0.0)
    currency_id = fields.Many2one(
        'res.currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    _sql_constraints = [
        (
            'visit_type_company_uniq',
            'unique(visit_type, company_id)',
            'Each visit type can only have one exam price per company.',
        ),
    ]

    @api.constrains('price')
    def _check_price(self):
        for rec in self:
            if rec.price < 0:
                raise ValidationError(_('Exam price cannot be negative.'))

    @api.model
    def get_price_for_visit_type(self, visit_type, company=None):
        company = company or self.env.company
        if not visit_type:
            return 0.0
        config = self.search([
            ('visit_type', '=', visit_type),
            ('company_id', '=', company.id),
            ('active', '=', True),
        ], limit=1)
        return config.price if config else 0.0

    @api.model
    def get_price_map(self, company=None):
        company = company or self.env.company
        configs = self.search([
            ('company_id', '=', company.id),
            ('active', '=', True),
        ])
        return {cfg.visit_type: cfg.price for cfg in configs}

    @api.model
    def _load_default_data(self):
        """Seed consultation product, diagnostic products, and exam prices."""
        Product = self.env['product.product'].sudo()
        ProductTemplate = self.env['product.template'].sudo()
        Category = self.env['product.category'].sudo()
        services = Category.search([('name', 'ilike', 'Services')], limit=1)
        if not services:
            services = Category.create({'name': 'Services'})

        consultation = Product.search([('default_code', '=', 'EXAM')], limit=1)
        if consultation:
            consultation.write({
                'name': 'Consultation (كشف)',
                'type': 'service',
                'sale_ok': True,
                'purchase_ok': False,
                'available_in_pos': True,
            })
            template = consultation.product_tmpl_id
        else:
            template = ProductTemplate.create({
                'name': 'Consultation (كشف)',
                'default_code': 'EXAM',
                'type': 'service',
                'list_price': 1000.0,
                'sale_ok': True,
                'purchase_ok': False,
                'available_in_pos': True,
                'categ_id': services.id,
            })
            consultation = template.product_variant_id

        module = self.env['ir.module.module'].search([('name', '=', 'pet_management')], limit=1)
        if module:
            self.env['ir.model.data'].sudo()._update_xmlids([{
                'xml_id': 'pet_management.product_consultation_exam',
                'record': consultation,
                'noupdate': True,
            }])

        emergency_exam = Product.search([('default_code', 'ilike', 'emergency')], limit=1)
        if not emergency_exam:
            emergency_exam = Product.search([('name', 'ilike', 'emergency exam')], limit=1)
        if emergency_exam and emergency_exam != consultation:
            emergency_exam.write({'active': False})

        diagnostic_products = [
            ('DIAG-US', 'Ultrasound / Sonar (سونار)', 500.0),
            ('DIAG-XR', 'X-Ray (أشعة)', 400.0),
            ('DIAG-LAB-CBC', 'Lab - Complete Blood Count', 300.0),
            ('DIAG-LAB-CHEM', 'Lab - Biochemistry Panel', 450.0),
            ('DIAG-LAB-URINE', 'Lab - Urinalysis', 200.0),
            ('DIAG-LAB-FECAL', 'Lab - Fecal Exam', 150.0),
        ]
        xmlids = {
            'DIAG-US': 'product_diagnostic_ultrasound',
            'DIAG-XR': 'product_diagnostic_xray',
            'DIAG-LAB-CBC': 'product_diagnostic_lab_cbc',
            'DIAG-LAB-CHEM': 'product_diagnostic_lab_chem',
            'DIAG-LAB-URINE': 'product_diagnostic_lab_urine',
            'DIAG-LAB-FECAL': 'product_diagnostic_lab_fecal',
        }
        xmlid_updates = []
        for code, name, price in diagnostic_products:
            product = Product.search([('default_code', '=', code)], limit=1)
            if product:
                product.write({
                    'name': name,
                    'type': 'service',
                    'list_price': price,
                    'sale_ok': True,
                    'purchase_ok': False,
                    'available_in_pos': True,
                    'categ_id': services.id,
                })
            else:
                tmpl = ProductTemplate.create({
                    'name': name,
                    'default_code': code,
                    'type': 'service',
                    'list_price': price,
                    'sale_ok': True,
                    'purchase_ok': False,
                    'available_in_pos': True,
                    'categ_id': services.id,
                })
                product = tmpl.product_variant_id
            xmlid_updates.append({
                'xml_id': 'pet_management.%s' % xmlids[code],
                'record': product,
                'noupdate': True,
            })
        if xmlid_updates:
            self.env['ir.model.data'].sudo()._update_xmlids(xmlid_updates)

        default_prices = {
            'checkup': 1000.0,
            'emergency': 1500.0,
            'home_visit': 2000.0,
        }
        for company in self.env['res.company'].sudo().search([]):
            for visit_type, price in default_prices.items():
                config = self.search([
                    ('visit_type', '=', visit_type),
                    ('company_id', '=', company.id),
                ], limit=1)
                if not config:
                    self.create({
                        'visit_type': visit_type,
                        'price': price,
                        'company_id': company.id,
                        'currency_id': company.currency_id.id,
                    })
