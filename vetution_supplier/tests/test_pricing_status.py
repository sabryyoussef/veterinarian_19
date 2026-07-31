# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestPetspotPricingStatus(TransactionCase):
    def test_selection_values(self):
        field = self.env["product.product"]._fields["petspot_pricing_status"]
        keys = {k for k, _ in field.selection}
        self.assertEqual(
            keys,
            {
                "priced",
                "blocked_missing_offer",
                "blocked_invalid_offer",
                "blocked_mapping",
                "blocked_stale_offer",
                "blocked_source_hidden",
                "manual_review",
                "non_retail",
            },
        )

    def test_non_retail_service(self):
        Product = self.env["product.product"]
        tmpl = self.env["product.template"].create(
            {"name": "Exam Service", "type": "service", "list_price": 100}
        )
        variant = tmpl.product_variant_id
        status = Product.petspot_pricing_status_for_variant(variant)
        self.assertEqual(status, "non_retail")
