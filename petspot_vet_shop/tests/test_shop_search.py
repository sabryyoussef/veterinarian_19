# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "petspot_vet_shop")
class TestPetspotShopSearch(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.brand = cls.env["vetution.brand"].create({
            "name": "P5SearchBrand", "slug": "p5-search-brand", "vetution_id": 92001,
        })
        cls.species = cls.env["vetution.species"].create({
            "name": "Cats", "vetution_id": 92002,
        })
        cls.ingredient = cls.env["vetution.ingredient"].create({
            "name": "Meloxicam", "vetution_id": 92003,
        })
        cls.tmpl = cls.env["product.template"].create({
            "name": "P5 Meloxicam Searchable",
            "type": "consu",
            "list_price": 200.0,
            "is_published": True,
            "vetution_id": 92010,
            "vetution_slug": "p5-meloxicam-searchable",
            "vetution_brand_id": cls.brand.id,
            "vetution_species_ids": [(6, 0, cls.species.ids)],
            "vetution_ingredient_ids": [(6, 0, cls.ingredient.ids)],
            "vetution_price_activated": True,
            "petspot_shop_has_sellable": True,
            "petspot_shop_min_sellable_price": 200.0,
        })
        cls.tmpl.product_variant_id.write({
            "vetution_size_name": "20 ml",
            "vetution_variant_price_activated": True,
            "petspot_shop_sellable": True,
            "petspot_shop_pricing_ready": True,
            "petspot_shop_display_price": 200.0,
            "petspot_shop_availability": "available",
        })

    def test_search_detail_includes_extra_fields(self):
        website = self.env["website"].get_current_website()
        detail = self.env["product.template"]._search_get_detail(
            website, "name asc", {
                "displayImage": True, "displayDescription": True,
                "displayExtraLink": True, "displayDetail": True,
                "display_currency": website.currency_id,
                "petspot_ready_only": False,
            },
        )
        fields = detail.get("search_fields") or []
        self.assertIn("vetution_slug", fields)
        self.assertNotIn("vetution_brand_id.name", fields)
        self.assertTrue(callable(detail.get("search_extra")))

    def test_ready_only_domain(self):
        website = self.env["website"].get_current_website()
        detail = self.env["product.template"]._search_get_detail(
            website, "name asc",
            {"displayImage": True, "displayDescription": False, "displayExtraLink": False,
             "displayDetail": False, "display_currency": website.currency_id,
             "petspot_ready_only": True},
        )
        # base_domain should mention petspot_shop_has_sellable
        blob = str(detail.get("base_domain"))
        self.assertIn("petspot_shop_has_sellable", blob)
