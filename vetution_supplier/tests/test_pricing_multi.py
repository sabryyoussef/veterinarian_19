# -*- coding: utf-8 -*-
"""Phase 4 multi-variant (Pack Size) pricing: price_extra, anchor, blocking, rollback."""

from unittest.mock import patch

from odoo.tests.common import tagged

from .common import VetutionSupplierCommon


@tagged("post_install", "-at_install", "vetution_supplier")
class TestVetutionMultiVariantPricing(VetutionSupplierCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.connection.write({
            "default_markup_percent": 20.0,
            "fixed_markup_amount": 0.0,
            "min_gross_margin_percent": 15.0,
            "min_gross_profit_amount": 50.0,
            "price_rounding": 5.0,
            "max_auto_price_change_percent": 5000.0,
            "minimum_expiry_days": 90,
        })
        cls.Pricing = cls.env["vetution.pricing"]
        cls.attr = cls.env["product.attribute"].search([("name", "=", "Pack Size")], limit=1)
        if not cls.attr:
            cls.attr = cls.env["product.attribute"].create({
                "name": "Pack Size", "create_variant": "always",
            })

    def _make_multi_template(self, name, sizes):
        """sizes: list of (value_name, size_id, cost, avail, show_price).

        Returns (template, {size_id: variant}).
        """
        val_recs = self.env["product.attribute.value"]
        for (vname, *_rest) in sizes:
            v = self.env["product.attribute.value"].search(
                [("name", "=", vname), ("attribute_id", "=", self.attr.id)], limit=1
            )
            if not v:
                v = self.env["product.attribute.value"].create(
                    {"name": vname, "attribute_id": self.attr.id}
                )
            val_recs |= v
        tmpl = self.env["product.template"].create({
            "name": name,
            "type": "consu",
            "list_price": 1.0,
            "vetution_id": 990000 + abs(hash(name)) % 9000,
            "vetution_slug": name.lower().replace(" ", "-"),
            "attribute_line_ids": [(0, 0, {
                "attribute_id": self.attr.id,
                "value_ids": [(6, 0, val_recs.ids)],
            })],
        })
        # Map each variant to a size_id and create an offer.
        variant_by_size = {}
        for (vname, size_id, cost, avail, show_price) in sizes:
            av = self.env["product.attribute.value"].search(
                [("name", "=", vname), ("attribute_id", "=", self.attr.id)], limit=1
            )
            variant = tmpl.product_variant_ids.filtered(
                lambda p: av in p.product_template_attribute_value_ids.product_attribute_value_id
            )[:1]
            variant.vetution_size_id = size_id
            self.env["vetution.supplier.offer"].create({
                "connection_id": self.connection.id,
                "offer_type": "vetution",
                "vetution_drug_id": tmpl.vetution_id,
                "drug_slug": tmpl.vetution_slug,
                "vetution_size_id": size_id,
                "size_name": vname,
                "product_id": variant.id,
                "supplier_price": cost,
                "effective_cost": cost,
                "availability_state": avail,
                "show": True,
                "show_price": show_price,
                "active_for_procurement": (avail in ("available", "limited") and show_price and cost > 0),
                "is_stale": False,
            })
            variant_by_size[size_id] = variant
        return tmpl, variant_by_size

    def test_all_eligible_price_extra_and_anchor(self):
        tmpl, vbs = self._make_multi_template(
            "P4 AllEligible",
            [("10 Tablets", 700001, 100.0, "available", True),
             ("30 Tablets", 700002, 300.0, "available", True)],
        )
        logs = self.Pricing.activate_multi_template(self.connection, tmpl, dry_run=False)
        # cost100 -> 150 (profit floor), cost300 -> markup360 vs margin352.9 vs profit350 -> 360
        anchor = vbs[700001]
        big = vbs[700002]
        self.assertEqual(tmpl.list_price, 150.0)
        self.assertEqual(anchor.lst_price, 150.0)
        self.assertEqual(big.lst_price, 360.0)
        # anchor extra 0, big extra 210
        anchor_ptav = self.Pricing._variant_ptav(tmpl, anchor)
        big_ptav = self.Pricing._variant_ptav(tmpl, big)
        self.assertEqual(anchor_ptav.price_extra, 0.0)
        self.assertEqual(big_ptav.price_extra, 210.0)
        self.assertGreaterEqual(big_ptav.price_extra, 0.0)
        self.assertTrue(tmpl.vetution_price_activated)
        self.assertTrue(big.vetution_variant_price_activated)

    def test_no_leakage_ineligible_archived(self):
        tmpl, vbs = self._make_multi_template(
            "P4 Mixed",
            [("10 Tablets", 700011, 100.0, "available", True),
             ("30 Tablets", 700012, 300.0, "out_of_stock", True),
             ("Hidden", 700013, 200.0, "available", False)],
        )
        logs = self.Pricing.activate_multi_template(self.connection, tmpl, dry_run=False)
        elig = vbs[700011]
        oos = vbs[700012]
        hidden = vbs[700013]
        # eligible one becomes anchor at 150
        self.assertEqual(tmpl.list_price, 150.0)
        self.assertEqual(elig.lst_price, 150.0)
        # ineligible variants archived → cannot be sold at a copied price
        self.assertFalse(oos.active)
        self.assertFalse(hidden.active)
        self.assertTrue(oos.vetution_variant_blocked_by_pricing)
        archived_logs = logs.filtered("variant_archived")
        self.assertEqual(len(archived_logs), 2)

    def test_dry_run_writes_nothing(self):
        tmpl, vbs = self._make_multi_template(
            "P4 Dry",
            [("10 Tablets", 700021, 100.0, "available", True),
             ("30 Tablets", 700022, 300.0, "out_of_stock", True)],
        )
        logs = self.Pricing.activate_multi_template(self.connection, tmpl, dry_run=True)
        self.assertEqual(tmpl.list_price, 1.0)
        self.assertFalse(tmpl.vetution_price_activated)
        self.assertTrue(vbs[700022].active)
        self.assertTrue(all(l.dry_run for l in logs))

    def test_rollback_restores_state(self):
        tmpl, vbs = self._make_multi_template(
            "P4 Rollback",
            [("10 Tablets", 700031, 100.0, "available", True),
             ("30 Tablets", 700032, 300.0, "available", True),
             ("OOS", 700033, 200.0, "out_of_stock", True)],
        )
        logs = self.Pricing.activate_multi_template(self.connection, tmpl, dry_run=False)
        self.assertEqual(tmpl.list_price, 150.0)
        self.assertFalse(vbs[700033].active)
        self.Pricing.rollback_logs(logs)
        self.assertEqual(tmpl.list_price, 1.0)
        self.assertFalse(tmpl.vetution_price_activated)
        self.assertTrue(vbs[700033].active)
        self.assertFalse(vbs[700033].vetution_variant_blocked_by_pricing)
        big_ptav = self.Pricing._variant_ptav(tmpl, vbs[700032])
        self.assertEqual(big_ptav.price_extra, 0.0)

    def test_pack_size_guard_rejects_multi_attribute(self):
        # A template whose variant attribute is not a single Pack Size must be skipped.
        color = self.env["product.attribute"].create({"name": "Color-P4", "create_variant": "always"})
        cval = self.env["product.attribute.value"].create({"name": "Red-P4", "attribute_id": color.id})
        tmpl = self.env["product.template"].create({
            "name": "P4 NonPack", "type": "consu", "list_price": 1.0,
            "vetution_id": 995555, "vetution_slug": "p4-nonpack",
            "attribute_line_ids": [(0, 0, {"attribute_id": color.id, "value_ids": [(6, 0, cval.ids)]})],
        })
        log = self.Pricing.activate_multi_template(self.connection, tmpl, dry_run=False)
        self.assertTrue(log.skipped)
        self.assertEqual(log.skip_reason, "not_single_pack_size_attribute")

    def test_pilot_variant_budget(self):
        with patch.object(type(self.Pricing), "_assert_fresh_and_auth", lambda *a, **k: True):
            tmpls, used = self.Pricing.select_multi_pilot_templates(
                self.connection, max_templates=30, max_variants=100
            )
            self.assertLessEqual(len(tmpls), 30)
            self.assertLessEqual(used, 100)
