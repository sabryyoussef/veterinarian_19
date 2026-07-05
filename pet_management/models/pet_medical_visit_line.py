# -*- coding: utf-8 -*-
from odoo import api, fields, models


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

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for line in self:
            if line.product_id:
                line.name = line.product_id.display_name
                line.price_unit = line.product_id.list_price
