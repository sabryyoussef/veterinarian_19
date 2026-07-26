# -*- coding: utf-8 -*-
"""Website helpers: cart warnings injection, shop domain filters."""

from odoo import models


class Website(models.Model):
    _inherit = "website"

    def sale_product_domain(self):
        """Keep native domain; readiness filtering is applied via search options / controller."""
        return super().sale_product_domain()
