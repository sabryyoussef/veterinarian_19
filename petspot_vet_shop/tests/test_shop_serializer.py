# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.petspot_vet_shop.models.product_template import PROHIBITED_PAYLOAD_KEYS


@tagged("post_install", "-at_install", "petspot_vet_shop")
class TestPetspotShopSerializer(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.brand = cls.env["vetution.brand"].create({
            "name": "P5 Brand", "slug": "p5-brand", "vetution_id": 91001,
        })
        cls.species = cls.env["vetution.species"].create({
            "name": "Dogs", "vetution_id": 91002,
        })
        cls.ingredient = cls.env["vetution.ingredient"].create({
            "name": "Amox", "vetution_id": 91003,
        })
        cls.conn = cls.env["vetution.connection"].search([("active", "=", True)], limit=1)
        if not cls.conn:
            cls.conn = cls.env["vetution.connection"].create({
                "name": "P5 Test Conn", "active": True,
            })
        cls.tmpl = cls.env["product.template"].create({
            "name": "P5 Serializer Drug",
            "type": "consu",
            "list_price": 150.0,
            "is_published": True,
            "vetution_id": 91010,
            "vetution_slug": "p5-serializer-drug",
            "vetution_brand_id": cls.brand.id,
            "vetution_species_ids": [(6, 0, cls.species.ids)],
            "vetution_ingredient_ids": [(6, 0, cls.ingredient.ids)],
            "vetution_price_activated": True,
            "vetution_cold_chain": True,
        })
        cls.variant = cls.tmpl.product_variant_id
        cls.variant.write({
            "vetution_size_id": 91011,
            "vetution_size_name": "10 Tablets",
            "vetution_variant_price_activated": True,
        })
        cls.env["vetution.supplier.offer"].create({
            "connection_id": cls.conn.id,
            "offer_type": "vetution",
            "product_id": cls.variant.id,
            "vetution_drug_id": cls.tmpl.vetution_id,
            "vetution_size_id": 91011,
            "effective_cost": 100.0,
            "supplier_price": 100.0,
            "availability_state": "available",
            "show": True,
            "show_price": True,
            "is_stale": False,
            "raw_json": '{"secret": true, "effective_cost": 100}',
        })
        cls.variant._compute_petspot_shop_state()
        cls.tmpl._compute_petspot_shop_has_sellable()

    def test_payload_includes_safe_fields(self):
        payload = self.tmpl._get_petspot_shop_payload()
        self.assertEqual(payload["id"], self.tmpl.id)
        self.assertEqual(payload["brand"], "P5 Brand")
        self.assertTrue(payload["cold_chain"])
        self.assertTrue(payload["variants"])
        v = payload["variants"][0]
        self.assertTrue(v["pricing_ready"])
        self.assertTrue(v["add_to_cart_allowed"])
        self.assertEqual(v["selling_price"], 150.0)

    def test_payload_excludes_prohibited(self):
        payload = self.tmpl._get_petspot_shop_payload()
        blob = str(payload)
        for key in PROHIBITED_PAYLOAD_KEYS:
            self.assertNotIn(f"'{key}'", blob)
            self.assertNotIn(f'"{key}"', blob)
        self.assertNotIn("effective_cost", payload)
        self.assertNotIn("raw_json", payload)
        self.assertNotIn("secret", blob)

    def test_default_variant_is_sellable(self):
        payload = self.tmpl._get_petspot_shop_payload()
        default = next(v for v in payload["variants"] if v["is_default"])
        self.assertTrue(default["add_to_cart_allowed"])
