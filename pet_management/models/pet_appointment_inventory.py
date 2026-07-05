from odoo import models, fields, api, _ # type: ignore
from odoo.exceptions import ValidationError # type: ignore

# Check if stock module is installed
try:
    # This will work if stock module is installed
    from odoo.addons.stock.models.stock_move import StockMove
    STOCK_INSTALLED = True
except ImportError:
    STOCK_INSTALLED = False

class PetAppointmentInventory(models.Model):
    _name = 'pet.appointment.inventory'
    _description = 'Appointment Inventory Item'
    _order = 'appointment_id, product_id'

    appointment_id = fields.Many2one('pet.appointment', required=True, ondelete='cascade', 
                                   help="Appointment this inventory item belongs to")
    product_id = fields.Many2one('product.product', required=True, 
                               help="Product used during appointment")
    quantity = fields.Float(required=True, default=1.0, 
                          help="Quantity of product used")
    unit_price = fields.Float(related='product_id.list_price', store=True,
                            help="Unit price of the product")
    total_cost = fields.Float(compute='_compute_total_cost', store=True,
                            help="Total cost (quantity × unit price)")
    notes = fields.Text(help="Additional notes about this inventory item usage")
    
    @api.depends('quantity', 'unit_price')
    def _compute_total_cost(self):
        """Compute total cost for this inventory item"""
        for rec in self:
            rec.total_cost = rec.quantity * rec.unit_price

    @api.constrains('quantity')
    def _check_quantity(self):
        """Validate quantity is positive"""
        for rec in self:
            if rec.quantity <= 0:
                raise ValidationError(_('Quantity must be greater than zero.'))

    def _is_stock_module_installed(self):
        """Check if stock module is installed and active"""
        try:
            return self.env['ir.module.module'].search([
                ('name', '=', 'stock'),
                ('state', '=', 'installed')
            ]).exists() and 'stock.move' in self.env
        except:
            return False

    def action_create_stock_move(self):
        """Create stock move for this inventory item if stock module is installed"""
        if not STOCK_INSTALLED:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Warning',
                    'message': 'Stock module is not installed. Please install the Stock module to use this feature.',
                    'type': 'warning',
                    'sticky': True,
                }
            }

        if self.stock_move_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Info',
                    'message': 'Stock move already exists for this item.',
                    'type': 'info',
                    'sticky': False,
                }
            }
        
        # Create stock move
        move_vals = {
            'name': f"Pet Appointment: {self.appointment_id.title}",
            'product_id': self.product_id.id,
            'product_uom_qty': self.quantity,
            'product_uom': self.product_id.uom_id.id,
            'location_id': self.env.ref('stock.stock_location_stock').id,  # Stock location
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,  # Customer location
            'origin': f"Pet Appointment: {self.appointment_id.name}",
            'state': 'draft',
        }
        
        move = self.env['stock.move'].create(move_vals)
        self.stock_move_id = move.id
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': 'Stock move created successfully.',
                'type': 'success',
                'sticky': True,
            }
        }


# Conditionally add stock_move_id field if stock module is installed
if STOCK_INSTALLED:
    PetAppointmentInventory.stock_move_id = fields.Many2one('stock.move', readonly=True,
                                                           help="Related stock move for inventory tracking")
