# -*- coding: utf-8 -*-

from odoo.tests import tagged

from .common import VetutionSupplierCommon, SAMPLE_DRUG


@tagged("post_install", "-at_install", "vetution_supplier")
class TestAvailability(VetutionSupplierCommon):
    def _norm(self, **kwargs):
        defaults = dict(
            show=True,
            show_price=True,
            out_of_stock=False,
            qty=5,
            effective_cost=100,
            is_expired=False,
            expiry_is_exact=False,
            days_to_expiry=False,
            minimum_expiry_days=90,
            near_expiry_days=180,
            low_stock_threshold=3,
        )
        defaults.update(kwargs)
        return self.Offer.normalize_availability(**defaults)

    def test_available(self):
        state, near, flags, ok = self._norm()
        self.assertEqual(state, "available")
        self.assertTrue(ok)

    def test_limited(self):
        state, near, flags, ok = self._norm(qty=2)
        self.assertEqual(state, "limited")

    def test_oos_authoritative(self):
        state, near, flags, ok = self._norm(out_of_stock=True, qty=5)
        self.assertEqual(state, "out_of_stock")
        self.assertIn("conflict_qty_pos", flags)
        self.assertFalse(ok)

    def test_qty_zero_not_oos(self):
        state, near, flags, ok = self._norm(qty=0)
        self.assertEqual(state, "unknown")
        self.assertIn("qty_zero_not_oos", flags)

    def test_price_hidden(self):
        state, near, flags, ok = self._norm(show=False)
        self.assertEqual(state, "price_hidden")

    def test_expired(self):
        state, near, flags, ok = self._norm(is_expired=True, expiry_is_exact=True)
        self.assertEqual(state, "expired")
        self.assertFalse(ok)


@tagged("post_install", "-at_install", "vetution_supplier")
class TestExpiry(VetutionSupplierCommon):
    def test_expired_blocks_procurement_on_upsert(self):
        drug = {
            "id": 999,
            "slug": "expired-test",
            "name": "Expired",
            "show_price": True,
            "prices": [
                {
                    "pack": {
                        "vetution": {
                            "drug_size_id": self.variant.vetution_size_id,
                            "price": 100,
                            "user_price": 0,
                            "show": 1,
                            "qty": "5",
                            "out_of_stock": 0,
                            "expire_date": "2020-01-01",
                        },
                        "vendors": [],
                    }
                }
            ],
        }
        metrics = {}
        self.Sync.process_drug(self.connection, drug, metrics, dry_run=False)
        offer = self.Offer.search(
            [
                ("connection_id", "=", self.connection.id),
                ("vetution_size_id", "=", self.variant.vetution_size_id),
                ("offer_type", "=", "vetution"),
            ],
            limit=1,
        )
        self.assertTrue(offer)
        self.assertTrue(offer.is_expired)
        self.assertEqual(offer.availability_state, "expired")
        self.assertFalse(offer.active_for_procurement)
