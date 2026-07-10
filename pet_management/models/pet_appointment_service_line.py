from odoo import models, fields, api, _  # type: ignore
from odoo.exceptions import ValidationError  # type: ignore


class PetAppointmentServiceLine(models.Model):
    _name = 'pet.appointment.service.line'
    _description = 'Appointment Additional Service Line'
    _order = 'appointment_id, sequence, id'

    appointment_id = fields.Many2one(
        'pet.appointment', required=True, ondelete='cascade', index=True,
        help="Appointment this service line belongs to")
    sequence = fields.Integer(default=10, help="Display order")
    product_id = fields.Many2one(
        'product.product', string='Service/Product',
        help="Optional product; used for invoicing when set")
    name = fields.Char(
        string='Description', required=True,
        help="Description of the extra service or charge")
    quantity = fields.Float(default=1.0, help="Quantity")
    price_unit = fields.Float(string='Unit Price', help="Unit price")
    discount = fields.Float(string='Disc. %', default=0.0, help="Discount percentage")
    price_subtotal = fields.Monetary(
        compute='_compute_price_subtotal', store=True, currency_field='currency_id',
        string='Subtotal', help="Line total (qty × unit price − discount)")
    currency_id = fields.Many2one(
        related='appointment_id.currency_id', store=True, readonly=True,
        help="Currency")
    invoice_synced = fields.Boolean(
        string='From Invoice', default=False, copy=False,
        help='Created/updated from invoice or sale order lines; replaced on re-sync',
    )
    sale_line_id = fields.Many2one(
        'sale.order.line',
        string='Sale Order Line',
        copy=False,
        index=True,
        ondelete='set null',
        help='Stable link to the generated sale order line.',
    )
    invoice_line_ids = fields.One2many(
        'account.move.line',
        'appointment_service_line_id',
        string='Invoice Lines',
    )
    medical_visit_line_id = fields.Many2one(
        'pet.medical.visit.line',
        string='Medical Visit Line',
        copy=False,
        index=True,
        ondelete='set null',
        help='When this extra mirrors a medical visit line, keep the source identity.',
    )

    @api.depends('quantity', 'price_unit', 'discount')
    def _compute_price_subtotal(self):
        for line in self:
            gross = (line.quantity or 0.0) * (line.price_unit or 0.0)
            line.price_subtotal = gross * (1.0 - (line.discount or 0.0) / 100.0)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for line in self:
            if line.product_id:
                if not line.name:
                    line.name = line.product_id.display_name
                if not line.price_unit:
                    line.price_unit = line.product_id.list_price

    @api.constrains('quantity')
    def _check_quantity(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_('Quantity must be greater than zero.'))

    def _resync_appointments(self):
        if self.env.context.get('skip_appointment_so_resync'):
            return
        appointments = self.mapped('appointment_id')
        if appointments:
            appointments._resync_draft_sale_order()

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._resync_appointments()
        return lines

    def write(self, vals):
        res = super().write(vals)
        self._resync_appointments()
        return res

    def unlink(self):
        if self.env.context.get('skip_appointment_so_resync'):
            return super().unlink()
        appointments = self.mapped('appointment_id')
        res = super().unlink()
        appointments._resync_draft_sale_order()
        return res
