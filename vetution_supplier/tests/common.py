# -*- coding: utf-8 -*-
"""Shared fixtures for vetution_supplier tests."""

from unittest.mock import patch

from odoo.tests.common import TransactionCase


SAMPLE_DRUG = {
    "id": 900419,
    "slug": "test-bravecto-phase1",
    "name": "TEST BRAVECTO",
    "show_price": True,
    "prices": [
        {
            "1 Tablet | 20-40 Kg": {
                "vetution": {
                    "drug_size_id": 900585,
                    "name": "1 Tablet | 20-40 Kg",
                    "price": 1959,
                    "user_price": 0,
                    "show": 1,
                    "qty": "19",
                    "out_of_stock": 0,
                    "expire_date": "2027-12-31",
                    "offer": 1,
                    "discount": "3",
                    "express": 1,
                    "old_price_offer": 2020,
                },
                "vendors": [
                    {
                        "vendor_drug_size_id": 900075,
                        "vendor_id": 42,
                        "vendor_name": "b",
                        "price": 2020,
                        "qty": 97,
                        "out_of_stock": 0,
                        "expire_date": None,
                    }
                ],
            }
        }
    ],
}


class VetutionSupplierCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Connection = cls.env["vetution.connection"]
        cls.Offer = cls.env["vetution.supplier.offer"]
        cls.Sync = cls.env["vetution.commercial.sync"]
        cls.partner = cls.env.ref("vetution_supplier.res_partner_vetution")
        cls.connection = cls.Connection.search([], limit=1)
        if not cls.connection:
            cls.connection = cls.Connection.create(
                {
                    "name": "Test Vetution Conn",
                    "phone": "01000059085",
                    "supplier_partner_id": cls.partner.id,
                }
            )
        if not cls.connection.supplier_partner_id:
            cls.connection.supplier_partner_id = cls.partner

        # Use high synthetic IDs that cannot collide with the imported catalog.
        tmpl = cls.env["product.template"].create(
            {
                "name": "Test BRAVECTO Phase1",
                "type": "consu",
                "list_price": 1.0,
                "vetution_id": 900419,
                "vetution_slug": "test-bravecto-phase1",
            }
        )
        cls.variant = tmpl.product_variant_id
        cls.variant.vetution_size_id = 900585

    def _patch_http(self, responses):
        def _fake(_model_self, connection, method, path, body=None, token=None, timeout=40):
            if callable(responses):
                return responses(connection, method, path, body=body, token=token)
            if not isinstance(responses, list) or not responses:
                raise AssertionError(f"Unexpected HTTP {method} {path}")
            return responses.pop(0)

        return patch.object(type(self.env["vetution.commercial.sync"]), "_http", _fake)
