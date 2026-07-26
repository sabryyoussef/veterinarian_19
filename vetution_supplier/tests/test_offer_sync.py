# -*- coding: utf-8 -*-

from odoo.tests import tagged

from .common import VetutionSupplierCommon, SAMPLE_DRUG


@tagged("post_install", "-at_install", "vetution_supplier")
class TestOfferSync(VetutionSupplierCommon):
    def test_idempotent_upsert(self):
        metrics1 = {}
        self.Sync.process_drug(self.connection, SAMPLE_DRUG, metrics1, dry_run=False)
        metrics2 = {}
        self.Sync.process_drug(self.connection, SAMPLE_DRUG, metrics2, dry_run=False)
        offers = self.Offer.search(
            [
                ("connection_id", "=", self.connection.id),
                ("vetution_size_id", "=", 900585),
                ("offer_type", "=", "vetution"),
            ]
        )
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers.effective_cost, 1959)
        self.assertEqual(offers.strike_price, 2020)
        self.assertTrue(offers.active_for_procurement)
        vendors = self.Offer.search(
            [
                ("connection_id", "=", self.connection.id),
                ("vendor_drug_size_id", "=", 900075),
                ("offer_type", "=", "marketplace_vendor"),
            ]
        )
        self.assertEqual(len(vendors), 1)
        self.assertFalse(vendors.active_for_procurement)
        self.assertGreaterEqual(metrics2.get("offers_unchanged", 0), 1)

    def test_duplicate_size_id_quarantine(self):
        drug = {
            "id": 901101,
            "slug": "friskies-cat-156-gm-test",
            "name": "FRISKIES TEST",
            "show_price": True,
            "prices": [
                {
                    "Fillet | Turkey": {
                        "vetution": {
                            "drug_size_id": 901839,
                            "price": 64,
                            "user_price": 0,
                            "show": 1,
                            "qty": "-1",
                            "out_of_stock": 1,
                            "expire_date": "0000-00-00",
                        },
                        "vendors": [],
                    }
                },
                {
                    "Fillet | Turkey Dup": {
                        "vetution": {
                            "drug_size_id": 901839,
                            "price": 64,
                            "user_price": 0,
                            "show": 1,
                            "qty": "0",
                            "out_of_stock": 1,
                            "expire_date": "2024-09-30",
                        },
                        "vendors": [],
                    }
                },
            ],
        }
        # Map size to a product
        self.variant.vetution_size_id = 901839
        metrics = {}
        quarantine = []
        self.Sync.process_drug(
            self.connection, drug, metrics, dry_run=False, quarantine_bucket=quarantine
        )
        offers = self.Offer.search(
            [
                ("connection_id", "=", self.connection.id),
                ("vetution_size_id", "=", 901839),
                ("offer_type", "=", "vetution"),
            ]
        )
        self.assertEqual(len(offers), 1)
        self.assertTrue(offers.needs_review)
        self.assertIn("duplicate_size_id_in_payload", offers.review_reason or "")
        self.assertFalse(offers.active_for_procurement)
        self.assertGreaterEqual(metrics.get("duplicate_ids", 0), 1)
        self.assertGreaterEqual(len(quarantine), 2)

    def test_removed_upstream_not_deleted(self):
        metrics = {}
        self.Sync.process_drug(self.connection, SAMPLE_DRUG, metrics, dry_run=False)
        before = self.Offer.search_count(
            [("connection_id", "=", self.connection.id), ("offer_type", "=", "vetution")]
        )
        # Sync a different product — should not delete bravecto offer
        other = {
            "id": 1,
            "slug": "other",
            "name": "Other",
            "show_price": True,
            "prices": [
                {
                    "A": {
                        "vetution": {
                            "drug_size_id": 999002,
                            "price": 10,
                            "user_price": 0,
                            "show": 1,
                            "qty": "1",
                            "out_of_stock": 0,
                            "expire_date": "2028-01-01",
                        },
                        "vendors": [],
                    }
                }
            ],
        }
        self.Sync.process_drug(self.connection, other, {}, dry_run=False)
        still = self.Offer.search(
            [
                ("connection_id", "=", self.connection.id),
                ("vetution_size_id", "=", 900585),
            ],
            limit=1,
        )
        self.assertTrue(still)
        self.assertGreaterEqual(
            self.Offer.search_count(
                [("connection_id", "=", self.connection.id), ("offer_type", "=", "vetution")]
            ),
            before,
        )
