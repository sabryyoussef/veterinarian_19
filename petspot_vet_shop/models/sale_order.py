# -*- coding: utf-8 -*-
"""Server-side cart guards for Vetution-backed products."""

from odoo import _, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _verify_updated_quantity(self, order_line, product_id, quantity, uom_id, **kwargs):
        """Block unsafe Vetution variants before cart mutation."""
        quantity, warning = super()._verify_updated_quantity(
            order_line, product_id, quantity, uom_id, **kwargs
        )
        if quantity <= 0:
            return quantity, warning
        product = self.env["product.product"].browse(product_id)
        if not product.exists():
            return quantity, warning
        ok, message = product._petspot_cart_eligibility()
        if not ok:
            return 0, message or _("This product cannot be added to the cart.")
        return quantity, warning

    def _check_cart_is_ready_to_be_paid(self):
        """Prevent checkout when any line became commercially blocked."""
        self.ensure_one()
        super()._check_cart_is_ready_to_be_paid()
        unsafe = []
        for line in self.order_line:
            product = line.product_id
            if not product.product_tmpl_id.vetution_id:
                continue
            ok, message = product._petspot_cart_eligibility()
            if not ok:
                unsafe.append(f"{product.display_name}: {message}")
        if unsafe:
            raise UserError(
                _("Some products in your cart are no longer available for purchase:\n\n%s\n\n"
                  "Please remove or update them before checkout.")
                % "\n".join(unsafe)
            )

    def _petspot_cart_warnings(self):
        """Return list of {line_id, product, message} for cart page display (no silent removal)."""
        self.ensure_one()
        warnings = []
        for line in self.order_line:
            product = line.product_id
            if not product.product_tmpl_id.vetution_id:
                continue
            ok, message = product._petspot_cart_eligibility()
            if not ok:
                warnings.append({
                    "line_id": line.id,
                    "product_id": product.id,
                    "product_name": product.display_name,
                    "message": message,
                })
        return warnings
