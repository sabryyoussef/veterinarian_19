# -*- coding: utf-8 -*-
"""Phase 6 tests: controlled batch pricing expansion + expanded-shop safety.

Covers: batch activation (single + multi), policy formula, rollback/reapply,
idempotency, existing-price protection (locks), mixed-eligibility default +
no price leak to ineligible siblings, placeholder hiding, prohibited keys,
bulk offer-map (bounded queries), and batch-size guards.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

PROHIBITED = {"effective_cost", "supplier_price", "supplier_user_price",
              "supplier_cost", "raw_json", "access_token"}


@tagged("post_install", "-at_install", "petspot_vet_shop", "phase6")
class TestPhase6Pricing(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env.ref("vetution_supplier.res_partner_vetution")
        cls.conn = cls.env["vetution.connection"].search([], limit=1)
        if not cls.conn:
            cls.conn = cls.env["vetution.connection"].create({
                "name": "P6 Conn", "phone": "01000000009",
                "supplier_partner_id": cls.partner.id,
            })
        cls.conn.write({
            "default_markup_percent": 20.0, "fixed_markup_amount": 0.0,
            "min_gross_margin_percent": 15.0, "min_gross_profit_amount": 50.0,
            "price_rounding": 5.0, "max_auto_price_change_percent": 5000.0,
            "minimum_expiry_days": 90, "stale_after_hours": 100000,
        })
        cls.Pricing = cls.env["vetution.pricing"]
        cls._seq = iter(range(96000, 99000))

    # ---- builders ----
    def _next(self):
        return next(self._seq)

    def _offer(self, variant, tmpl, cost=100.0, avail="available"):
        return self.env["vetution.supplier.offer"].create({
            "connection_id": self.conn.id, "offer_type": "vetution",
            "product_id": variant.id, "vetution_drug_id": tmpl.vetution_id,
            "vetution_size_id": variant.vetution_size_id,
            "effective_cost": cost, "supplier_price": cost,
            "availability_state": avail, "show": True,
            "show_price": avail != "price_hidden",
            "is_stale": avail == "stale",
            "active_for_procurement": avail in ("available", "limited"),
            "expiry_is_exact": False,
        })

    def _make_single(self, cost=100.0, avail="available", locked=False, price=1.0):
        vid = self._next()
        tmpl = self.env["product.template"].create({
            "name": f"P6 single {vid}", "type": "consu", "list_price": price,
            "is_published": True, "vetution_id": vid, "vetution_slug": f"p6-s-{vid}",
            "vetution_sale_price_locked": locked,
        })
        v = tmpl.product_variant_id
        v.write({"vetution_size_id": vid, "vetution_size_name": "Pack"})
        self._offer(v, tmpl, cost=cost, avail=avail)
        v._compute_petspot_shop_state()
        return tmpl

    def _make_multi(self, states):
        """states: list of (cost, availability). Creates a Pack Size multi template."""
        did = self._next()
        attr = self.env["product.attribute"].create({
            "name": "Pack Size", "create_variant": "always"})
        vals = self.env["product.attribute.value"].create(
            [{"name": f"Sz{i}-{did}", "attribute_id": attr.id} for i in range(len(states))])
        tmpl = self.env["product.template"].create({
            "name": f"P6 multi {did}", "type": "consu", "list_price": 1.0,
            "is_published": True, "vetution_id": did, "vetution_slug": f"p6-m-{did}",
            "attribute_line_ids": [(0, 0, {"attribute_id": attr.id,
                                           "value_ids": [(6, 0, vals.ids)]})],
        })
        for v, (cost, avail) in zip(tmpl.product_variant_ids, states):
            sid = self._next()
            v.write({"vetution_size_id": sid, "vetution_size_name": f"{cost}g"})
            self._offer(v, tmpl, cost=cost, avail=avail)
        tmpl.product_variant_ids._compute_petspot_shop_state()
        tmpl._compute_petspot_shop_has_sellable()
        return tmpl

    # ---- tests ----
    def test_single_policy_formula(self):
        tmpl = self._make_single(cost=100.0)
        log = self.Pricing.activate_template_price(self.conn, tmpl, dry_run=False)
        self.assertFalse(log.skipped)
        self.assertGreater(tmpl.list_price, 100.0)          # price > cost
        self.assertGreaterEqual(log.gross_profit, 50.0 - 1e-6)
        self.assertGreaterEqual(log.gross_margin_percent, 15.0 - 1e-6)
        self.assertAlmostEqual(tmpl.list_price % 5.0, 0.0, places=6)  # rounded to 5
        self.assertTrue(tmpl.vetution_price_activated)

    def test_manual_lock_not_overwritten(self):
        tmpl = self._make_single(cost=100.0, locked=True, price=1.0)
        log = self.Pricing.activate_template_price(self.conn, tmpl, dry_run=False)
        self.assertTrue(log.skipped)
        self.assertEqual(log.skip_reason, "sale_price_locked")
        self.assertEqual(tmpl.list_price, 1.0)

    def test_multi_anchor_and_no_leak_and_default(self):
        # 2 eligible (cost 100, 200) + 1 ineligible OOS
        tmpl = self._make_multi([(100.0, "available"), (200.0, "available"),
                                 (150.0, "out_of_stock")])
        self.Pricing.activate_multi_template(self.conn, tmpl, dry_run=False,
                                             block_ineligible=False)
        tmpl.product_variant_ids._compute_petspot_shop_state()
        tmpl._compute_petspot_shop_has_sellable()
        # anchor = cheapest eligible selling price
        elig = tmpl.product_variant_ids.filtered("vetution_variant_price_activated")
        self.assertEqual(len(elig), 2)
        cheapest = min(elig.mapped("lst_price"))
        self.assertAlmostEqual(tmpl.list_price, cheapest, places=2)
        # ineligible sibling remains ACTIVE (not archived) but not price-activated
        oos = tmpl.product_variant_ids - elig
        self.assertEqual(len(oos), 1)
        self.assertTrue(oos.active)
        self.assertFalse(oos.vetution_variant_price_activated)
        # serializer: no leaked price on ineligible sibling, blocked from cart
        payload = tmpl._get_petspot_shop_payload()
        for vp in payload["variants"]:
            if vp["id"] == oos.id:
                self.assertFalse(vp["pricing_ready"])
                self.assertEqual(vp["selling_price"], 0.0)
                self.assertFalse(vp["add_to_cart_allowed"])
            else:
                self.assertTrue(vp["add_to_cart_allowed"])
                self.assertGreater(vp["selling_price"], 1.01)
        # default variant is sellable, cheapest
        dv = self.env["product.product"].browse(payload["default_variant_id"])
        self.assertTrue(dv.petspot_shop_sellable)

    def test_rollback_and_reapply_idempotent(self):
        tmpl = self._make_single(cost=120.0)
        logs = self.Pricing.activate_template_price(self.conn, tmpl, dry_run=False)
        first_price = tmpl.list_price
        self.assertGreater(first_price, 1.01)
        self.Pricing.rollback_logs(logs)
        tmpl.invalidate_recordset()
        self.assertLessEqual(tmpl.list_price, 1.01)       # restored to placeholder
        self.assertFalse(tmpl.vetution_price_activated)
        # reapply -> identical result (idempotent)
        self.Pricing.activate_template_price(self.conn, tmpl, dry_run=False)
        tmpl.invalidate_recordset()
        self.assertAlmostEqual(tmpl.list_price, first_price, places=2)

    def test_multi_rollback_restores_extras(self):
        tmpl = self._make_multi([(100.0, "available"), (250.0, "available")])
        logs = self.Pricing.activate_multi_template(self.conn, tmpl, dry_run=False,
                                                    block_ineligible=False)
        ptavs = tmpl.attribute_line_ids.product_template_value_ids
        self.assertTrue(any(p.price_extra > 0 for p in ptavs))
        self.Pricing.rollback_logs(logs)
        tmpl.invalidate_recordset()
        ptavs.invalidate_recordset()
        self.assertTrue(all(abs(p.price_extra) < 1e-6 for p in ptavs))
        self.assertLessEqual(tmpl.list_price, 1.01)

    def test_no_prohibited_keys(self):
        tmpl = self._make_multi([(100.0, "available"), (300.0, "limited")])
        self.Pricing.activate_multi_template(self.conn, tmpl, dry_run=False,
                                             block_ineligible=False)
        tmpl.product_variant_ids._compute_petspot_shop_state()
        payload = tmpl._get_petspot_shop_payload()
        for k in PROHIBITED:
            self.assertNotIn(k, payload)
            for vp in payload["variants"]:
                self.assertNotIn(k, vp)

    def test_bulk_offer_map_bounded(self):
        tmpls = self.env["product.template"]
        for _ in range(4):
            tmpls |= self._make_multi([(100.0, "available"), (200.0, "available")])
            self.Pricing.activate_multi_template(self.conn, tmpls[-1:], dry_run=False,
                                                 block_ineligible=False)
        tmpls.product_variant_ids._compute_petspot_shop_state()
        vids = tmpls.product_variant_ids.ids
        offer_map = self.env["product.template"]._petspot_bulk_offer_map(vids)
        # one entry per variant that has an offer
        self.assertTrue(all(pid in offer_map for pid in vids))
        # serialize using shared map -> works and no leaks
        for t in tmpls:
            p = t._get_petspot_shop_payload(offer_map=offer_map)
            self.assertTrue(p["has_sellable"])

    def test_multi_pilot_variant_budget_guard(self):
        t = self._make_multi([(100.0, "available"), (200.0, "available"),
                              (300.0, "available")])
        with self.assertRaises(UserError):
            self.Pricing.activate_multi_pilot(self.conn, templates=t,
                                              max_templates=30, max_variants=2)

    def test_placeholder_hidden(self):
        tmpl = self._make_single(cost=100.0, avail="available", price=1.0)
        # not activated yet -> placeholder must not be sellable / no price
        payload = tmpl._get_petspot_shop_payload()
        vp = payload["variants"][0]
        self.assertFalse(vp["add_to_cart_allowed"])
        self.assertEqual(vp["selling_price"], 0.0)
        self.assertFalse(tmpl.petspot_shop_has_sellable)
