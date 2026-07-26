# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "petspot_vet_shop")
class TestPetspotShopAvailability(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env.ref("vetution_supplier.res_partner_vetution")
        cls.conn = cls.env["vetution.connection"].search([], limit=1)
        if not cls.conn:
            cls.conn = cls.env["vetution.connection"].create({
                "name": "P5 Avail Conn", "phone": "01000000000",
                "supplier_partner_id": cls.partner.id,
            })
        cls.tmpl = cls.env["product.template"].create({
            "name": "P5 Avail Drug",
            "type": "consu",
            "list_price": 150.0,
            "is_published": True,
            "vetution_id": 93010,
            "vetution_slug": "p5-avail-drug",
            "vetution_price_activated": True,
        })
        cls.variant = cls.tmpl.product_variant_id
        cls.variant.write({
            "vetution_size_id": 93011,
            "vetution_size_name": "10 Tabs",
            "vetution_variant_price_activated": True,
        })

    def _offer(self, **kw):
        vals = {
            "connection_id": self.conn.id,
            "offer_type": "vetution",
            "product_id": self.variant.id,
            "vetution_drug_id": self.tmpl.vetution_id,
            "vetution_size_id": 93011,
            "effective_cost": 100.0,
            "supplier_price": 100.0,
            "availability_state": "available",
            "show": True,
            "show_price": True,
            "is_stale": False,
        }
        vals.update(kw)
        return self.env["vetution.supplier.offer"].create(vals)

    def test_available_sellable(self):
        self._offer(availability_state="available")
        self.variant._compute_petspot_shop_state()
        self.assertTrue(self.variant.petspot_shop_sellable)
        self.assertEqual(self.variant.petspot_shop_availability, "available")

    def test_oos_notify(self):
        self._offer(availability_state="out_of_stock")
        self.variant._compute_petspot_shop_state()
        self.assertFalse(self.variant.petspot_shop_sellable)
        self.assertTrue(self.variant.petspot_shop_notify_allowed)

    def test_unknown_request(self):
        self._offer(availability_state="unknown")
        self.variant._compute_petspot_shop_state()
        self.assertFalse(self.variant.petspot_shop_sellable)
        self.assertTrue(self.variant.petspot_shop_request_allowed)

    def test_placeholder_hidden(self):
        self.tmpl.list_price = 1.0
        self.tmpl.vetution_price_activated = False
        self._offer(availability_state="available")
        self.variant._compute_petspot_shop_state()
        self.assertFalse(self.variant.petspot_shop_pricing_ready)
        self.assertEqual(self.variant.petspot_shop_display_price, 0.0)

    def test_expired_blocked(self):
        self._offer(availability_state="expired")
        self.variant._compute_petspot_shop_state()
        self.assertFalse(self.variant.petspot_shop_sellable)
        self.assertEqual(self.variant.petspot_shop_block_reason, "expired")

    def test_expiry_display_unknown(self):
        offer = self._offer(availability_state="available", expiry_is_exact=False)
        info = self.variant._petspot_expiry_display(offer)
        self.assertEqual(info["state"], "unknown")
        self.assertIn("fulfilment", info["text"])
