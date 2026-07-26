# -*- coding: utf-8 -*-

from odoo.tests import tagged

from .common import VetutionSupplierCommon, SAMPLE_DRUG


@tagged("post_install", "-at_install", "vetution_supplier")
class TestReconciliation(VetutionSupplierCommon):
    def test_reconcile_marks_not_seen_when_apply_stale(self):
        self.Sync.process_drug(self.connection, SAMPLE_DRUG, {}, dry_run=False)
        offer = self.Offer.search(
            [
                ("connection_id", "=", self.connection.id),
                ("vetution_size_id", "=", 900585),
                ("offer_type", "=", "vetution"),
            ],
            limit=1,
        )
        self.assertTrue(offer)
        # Pretend offer was last synced in the past
        offer.write({"last_commercial_sync_at": "2020-01-01 00:00:00", "is_stale": False})
        since = fields_datetime_now = self.env["vetution.sync.log"].create(
            {
                "name": "fake full",
                "connection_id": self.connection.id,
                "sync_type": "full_commercial",
                "state": "done",
                "started_at": "2026-07-26 00:00:00",
            }
        ).started_at
        report, log = self.Sync.reconcile_commercial(
            self.connection, since_dt=since, apply_stale=True
        )
        offer.invalidate_recordset()
        self.assertTrue(offer.is_stale)
        self.assertTrue(offer.needs_review)
        self.assertIn("not_seen_in_full_sync", offer.review_reason or "")
        self.assertFalse(offer.active_for_procurement)
        self.assertEqual(log.state, "done")
        self.assertGreaterEqual(report["primary_not_seen"], 1)

    def test_supplierinfo_kept_for_oos_with_cost(self):
        drug = {
            "id": 900419,
            "slug": "test-bravecto-phase1",
            "name": "TEST BRAVECTO",
            "show_price": True,
            "prices": [
                {
                    "1 Tablet | 20-40 Kg": {
                        "vetution": {
                            "drug_size_id": 900585,
                            "price": 1959,
                            "user_price": 0,
                            "show": 1,
                            "qty": "0",
                            "out_of_stock": 1,
                            "expire_date": "2027-12-31",
                        },
                        "vendors": [],
                    }
                }
            ],
        }
        self.Sync.process_drug(self.connection, drug, {}, dry_run=False)
        offer = self.Offer.search(
            [
                ("vetution_size_id", "=", 900585),
                ("offer_type", "=", "vetution"),
            ],
            limit=1,
        )
        self.assertEqual(offer.availability_state, "out_of_stock")
        self.assertFalse(offer.active_for_procurement)
        si = self.env["product.supplierinfo"].search(
            [
                ("vetution_origin", "=", "vetution_supplier"),
                ("vetution_offer_id", "=", offer.id),
            ]
        )
        self.assertEqual(len(si), 1)
        self.assertAlmostEqual(si.price, 1959)

    def test_supplierinfo_removed_when_expired(self):
        drug = {
            "id": 900419,
            "slug": "test-bravecto-phase1",
            "name": "TEST BRAVECTO",
            "show_price": True,
            "prices": [
                {
                    "1 Tablet | 20-40 Kg": {
                        "vetution": {
                            "drug_size_id": 900585,
                            "price": 1959,
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
        self.Sync.process_drug(self.connection, drug, {}, dry_run=False)
        offer = self.Offer.search(
            [("vetution_size_id", "=", 900585), ("offer_type", "=", "vetution")],
            limit=1,
        )
        self.assertEqual(offer.availability_state, "expired")
        si = self.env["product.supplierinfo"].search(
            [
                ("vetution_origin", "=", "vetution_supplier"),
                ("vetution_offer_id", "=", offer.id),
            ]
        )
        self.assertFalse(si)
