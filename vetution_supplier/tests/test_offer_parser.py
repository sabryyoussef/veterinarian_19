# -*- coding: utf-8 -*-

from datetime import date, timedelta

from odoo.tests import tagged

from .common import VetutionSupplierCommon


@tagged("post_install", "-at_install", "vetution_supplier")
class TestOfferParser(VetutionSupplierCommon):
    def test_effective_cost_priority(self):
        Offer = self.Offer
        self.assertEqual(Offer.compute_effective_cost(100, 80, True, True), 80)
        self.assertEqual(Offer.compute_effective_cost(100, 0, True, True), 100)
        self.assertEqual(Offer.compute_effective_cost(100, 0, False, True), 0)
        self.assertEqual(Offer.compute_effective_cost(0, 0, True, True), 0)

    def test_strike_price_only_when_promo(self):
        Offer = self.Offer
        self.assertEqual(Offer.compute_strike_price(1959, 2020, 1), 2020)
        self.assertEqual(Offer.compute_strike_price(260, 203, 0), 0)
        self.assertEqual(Offer.compute_strike_price(100, 50, 1), 0)

    def test_qty_parsing(self):
        Offer = self.Offer
        q, raw, flags = Offer.parse_qty("19")
        self.assertEqual(q, 19.0)
        q, raw, flags = Offer.parse_qty("-9")
        self.assertEqual(q, -9.0)
        self.assertIn("qty_negative", flags)
        q, raw, flags = Offer.parse_qty("0.25")
        self.assertEqual(q, 0.25)
        self.assertIn("fractional_qty", flags)

    def test_expiry_markers(self):
        Offer = self.Offer
        today = date(2026, 7, 26)
        for marker in (None, "0000-00-00", "0001-01-01"):
            r = Offer.parse_expiry(marker, today=today)
            self.assertFalse(r["expiry_is_exact"])
            self.assertIn("expiry_unknown", r["flags"])

        past = Offer.parse_expiry("2026-05-01", today=today)
        self.assertTrue(past["is_expired"])
        future = Offer.parse_expiry("2027-12-31", today=today)
        self.assertFalse(future["is_expired"])
        near = Offer.parse_expiry(
            (today + timedelta(days=30)).isoformat(), today=today
        )
        self.assertEqual(near["days_to_expiry"], 30)
