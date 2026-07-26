# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged, HttpCase

from odoo.addons.petspot_vet_shop.models.product_template import PROHIBITED_PAYLOAD_KEYS


@tagged("post_install", "-at_install", "petspot_vet_shop")
class TestPetspotShopSecurity(TransactionCase):
    def test_payload_route_model_never_returns_cost_keys(self):
        tmpl = self.env["product.template"].search([
            ("vetution_id", "!=", False),
            ("vetution_price_activated", "=", True),
        ], limit=1)
        if not tmpl:
            self.skipTest("No activated template in DB")
        payload = tmpl._get_petspot_shop_payload()
        flat = str(payload)
        for key in PROHIBITED_PAYLOAD_KEYS:
            self.assertNotIn(key, payload)
            # Ensure nested variants also clean
            for v in payload.get("variants") or []:
                self.assertNotIn(key, v)

    def test_public_cannot_read_offer_cost_via_serializer(self):
        """Serializer is the public contract — cost fields must be absent even for sudo env."""
        tmpl = self.env["product.template"].search([
            ("vetution_price_activated", "=", True),
        ], limit=1)
        if not tmpl:
            self.skipTest("No activated template")
        payload = tmpl.sudo()._get_petspot_shop_payload()
        self.assertNotIn("effective_cost", str(payload))
        self.assertNotIn("supplier_price", str(payload))
        self.assertNotIn("raw_json", str(payload))
