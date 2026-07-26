# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "petspot_vet_shop")
class TestPetspotShopCart(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env.ref("vetution_supplier.res_partner_vetution")
        cls.customer = cls.env["res.partner"].create({"name": "P5 Customer"})
        cls.conn = cls.env["vetution.connection"].search([], limit=1)
        if not cls.conn:
            cls.conn = cls.env["vetution.connection"].create({
                "name": "P5 Cart Conn", "phone": "01000000001",
                "supplier_partner_id": cls.partner.id,
            })
        cls.website = cls.env["website"].get_current_website()

    def _make(self, avail="available", price=150.0, activated=True):
        tmpl = self.env["product.template"].create({
            "name": f"P5 Cart {avail}",
            "type": "consu",
            "list_price": price,
            "is_published": True,
            "vetution_id": 94000 + abs(hash(avail)) % 900,
            "vetution_slug": f"p5-cart-{avail}",
            "vetution_price_activated": activated,
        })
        variant = tmpl.product_variant_id
        variant.write({
            "vetution_size_id": 94000 + abs(hash(avail + "s")) % 900,
            "vetution_size_name": "Pack",
            "vetution_variant_price_activated": activated and price > 1.01,
        })
        self.env["vetution.supplier.offer"].create({
            "connection_id": self.conn.id,
            "offer_type": "vetution",
            "product_id": variant.id,
            "vetution_drug_id": tmpl.vetution_id,
            "vetution_size_id": variant.vetution_size_id,
            "effective_cost": 100.0,
            "supplier_price": 100.0,
            "availability_state": avail,
            "show": True,
            "show_price": avail != "price_hidden",
            "is_stale": avail == "stale",
        })
        variant._compute_petspot_shop_state()
        return tmpl, variant

    def test_available_allowed(self):
        _t, v = self._make("available")
        ok, msg = v._petspot_cart_eligibility()
        self.assertTrue(ok, msg)

    def test_limited_allowed(self):
        _t, v = self._make("limited")
        ok, _msg = v._petspot_cart_eligibility()
        self.assertTrue(ok)

    def test_oos_blocked(self):
        _t, v = self._make("out_of_stock")
        ok, msg = v._petspot_cart_eligibility()
        self.assertFalse(ok)
        self.assertIn("out of stock", msg.lower())

    def test_unknown_blocked(self):
        _t, v = self._make("unknown")
        ok, msg = v._petspot_cart_eligibility()
        self.assertFalse(ok)
        self.assertIn("request", msg.lower())

    def test_expired_blocked(self):
        _t, v = self._make("expired")
        self.assertFalse(v._petspot_cart_eligibility()[0])

    def test_stale_blocked(self):
        _t, v = self._make("stale")
        self.assertFalse(v._petspot_cart_eligibility()[0])

    def test_placeholder_blocked(self):
        _t, v = self._make("available", price=1.0, activated=False)
        ok, msg = v._petspot_cart_eligibility()
        self.assertFalse(ok)
        self.assertIn("pricing", msg.lower())

    def test_verify_updated_quantity_blocks(self):
        _t, v = self._make("out_of_stock")
        so = self.env["sale.order"].create({
            "partner_id": self.customer.id,
            "website_id": self.website.id,
        })
        qty, warning = so._verify_updated_quantity(
            self.env["sale.order.line"], v.id, 1.0, v.uom_id.id
        )
        self.assertEqual(qty, 0)
        self.assertTrue(warning)

    def test_checkout_blocks_unsafe_existing_line(self):
        _t, v = self._make("available")
        so = self.env["sale.order"].create({
            "partner_id": self.customer.id,
            "website_id": self.website.id,
        })
        line = self.env["sale.order.line"].create({
            "order_id": so.id,
            "product_id": v.id,
            "product_uom_qty": 1,
        })
        # Simulate commercial state change after add
        offer = self.env["vetution.supplier.offer"].search([("product_id", "=", v.id)], limit=1)
        offer.write({"availability_state": "out_of_stock"})
        with self.assertRaises(UserError):
            so._check_cart_is_ready_to_be_paid()
        warnings = so._petspot_cart_warnings()
        self.assertTrue(any(w["line_id"] == line.id for w in warnings))
