# -*- coding: utf-8 -*-
"""Operational business rules for ShipBlu (mocked — no live API)."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.delivery_shipblu.services import cutoff_service
from odoo.addons.delivery_shipblu.services.shipment_service import ShipmentService
from odoo.addons.petspot_shipblu_base.services.cost_engine import CostEngine


class ShipBluOpsCase(TransactionCase):
    def setUp(self):
        super().setUp()
        company = self.env.company
        Project = self.env["project.project"]
        if "billing_type" in Project._fields:
            for proj in Project.search([("company_id", "=", company.id)]):
                if not proj.billing_type:
                    proj.write({"billing_type": "not_billable"})
        existing = self.env["shipblu.backend"].search([("company_id", "=", company.id)], limit=1)
        vals = {
            "name": "ShipBlu Ops Test",
            "company_id": company.id,
            "api_key": "test-not-real",
            "shipping_owner_mode": "track_only",
            "shipment_creation_enabled": False,
            "default_package_size": 1,
            "default_zone_id": 83,
            "company_timezone": "Africa/Cairo",
            "pickup_cutoff_time": 13.0,
            "flyer_cutoff_time": 10.0,
            "min_shipments_per_pickup": 5,
            "low_volume_pickup_surcharge": 65.0,
            "max_shipment_weight_kg": 10.0,
            "cod_commission_rate": 0.5,
            "try_and_buy_fee": 40.0,
            "return_service_fee": 5.0,
            "return_refusal_charge_percent": 90.0,
            "inspection_fee": 5.0,
            "settlement_transfer_fee": 70.0,
            "enable_pricing_estimation": True,
            "enable_package_weight_blocking": True,
            "enable_coverage_blocking": False,
            "try_and_buy_shopify_only": True,
        }
        if existing:
            existing.write(vals)
            self.backend = existing
        else:
            self.backend = self.env["shipblu.backend"].create(vals)
        self.backend._ensure_reference_config()

    def _at_cairo(self, hour, minute=0, day=30, month=7, year=2026):
        return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("Africa/Cairo")).astimezone(
            ZoneInfo("UTC")
        ).replace(tzinfo=None)


class TestCutoffs(ShipBluOpsCase):
    def test_pickup_before_1pm_same_day(self):
        when = self._at_cairo(12, 59)
        info = cutoff_service.pickup_cutoff_info(self.backend, when)
        self.assertFalse(info["pickup_cutoff_passed"])
        self.assertTrue(info["same_day_pickup_possible"])

    def test_pickup_after_1pm_next_day(self):
        when = self._at_cairo(13, 0)
        info = cutoff_service.pickup_cutoff_info(self.backend, when)
        self.assertTrue(info["pickup_cutoff_passed"])
        self.assertFalse(info["same_day_pickup_possible"])

    def test_flyer_before_10am(self):
        when = self._at_cairo(9, 59)
        info = cutoff_service.flyer_cutoff_info(self.backend, when)
        self.assertFalse(info["flyer_cutoff_passed"])

    def test_flyer_after_10am(self):
        when = self._at_cairo(10, 0)
        info = cutoff_service.flyer_cutoff_info(self.backend, when)
        self.assertTrue(info["flyer_cutoff_passed"])


class TestWeightAndPackage(ShipBluOpsCase):
    def setUp(self):
        super().setUp()
        self.backend.write(
            {
                "shipping_owner_mode": "odoo_owned",
                "shipment_creation_enabled": True,
                "default_package_size": 1,
            }
        )

    def test_weight_exactly_10kg_ok(self):
        svc = ShipmentService(self.env)
        svc.assert_can_create(
            False,
            self.backend,
            overrides={"package_size": 1, "zone": 83, "weight_kg": 10.0},
        )

    def test_weight_above_10kg_blocked(self):
        svc = ShipmentService(self.env)
        with self.assertRaises(UserError):
            svc.assert_can_create(
                False,
                self.backend,
                overrides={"package_size": 1, "zone": 83, "weight_kg": 10.01},
            )

    def test_package_count_validation(self):
        with self.assertRaises(ValidationError):
            self.env["shipblu.shipment"].create(
                {
                    "name": "SB-TEST-PC",
                    "backend_id": self.backend.id,
                    "company_id": self.backend.company_id.id,
                    "business_reference": "uat-pkg-count-1",
                    "package_count": 0,
                }
            )


class TestCostEngine(ShipBluOpsCase):
    def test_small_medium_no_surcharge(self):
        engine = CostEngine(self.backend)
        for code in ("small", "medium"):
            bd = engine.compute(
                destination_governorate="Giza",
                package_size_code=code,
                cod_amount=0,
            )
            self.assertEqual(bd.size_surcharge, 0.0)
            self.assertEqual(bd.base_fee, 95.0)

    def test_large_10_percent(self):
        bd = CostEngine(self.backend).compute(
            destination_governorate="Giza",
            package_size_code="large",
        )
        self.assertEqual(bd.base_fee, 95.0)
        self.assertAlmostEqual(bd.size_surcharge, 9.5, places=2)

    def test_xlarge_15_percent(self):
        bd = CostEngine(self.backend).compute(
            destination_governorate="Giza",
            package_size_code="xlarge",
        )
        self.assertAlmostEqual(bd.size_surcharge, 14.25, places=2)

    def test_cod_commission_half_percent(self):
        bd = CostEngine(self.backend).compute(
            destination_governorate="Giza",
            package_size_code="small",
            cod_amount=1000.0,
        )
        self.assertAlmostEqual(bd.cod_fee, 5.0, places=2)

    def test_inspection_fee(self):
        bd = CostEngine(self.backend).compute(
            destination_governorate="Giza",
            package_size_code="small",
            inspection=True,
        )
        self.assertEqual(bd.inspection_fee, 5.0)

    def test_return_service_fee(self):
        bd = CostEngine(self.backend).compute(
            destination_governorate="Giza",
            package_size_code="small",
            include_return_fee=True,
        )
        self.assertEqual(bd.return_fee, 5.0)

    def test_refusal_charge_90_percent(self):
        bd = CostEngine(self.backend).compute(
            destination_governorate="Giza",
            package_size_code="small",
            customer_refused_return_pay=True,
        )
        # 90% of 95 base
        self.assertAlmostEqual(bd.return_fee, 85.5, places=2)

    def test_pickup_below_5(self):
        bd = CostEngine(self.backend).compute(
            destination_governorate="Giza",
            package_size_code="small",
            pickup_shipment_count=3,
        )
        self.assertEqual(bd.pickup_surcharge, 65.0)

    def test_volume_discount_tier_and_gap(self):
        engine = CostEngine(self.backend)
        with patch.object(CostEngine, "monthly_shipment_count", return_value=40):
            tier, count = engine.active_discount_tier(40)
            self.assertTrue(tier)
            self.assertEqual(tier.discount_percent, 4.0)
        with patch.object(CostEngine, "monthly_shipment_count", return_value=55):
            tier, count = engine.active_discount_tier(55)
            self.assertFalse(tier)
            self.assertEqual(count, 55)
        # count 200 must hit exactly one tier (160-200), not overlap 201-500
        with patch.object(CostEngine, "monthly_shipment_count", return_value=200):
            tier, count = engine.active_discount_tier(200)
            self.assertTrue(tier)
            self.assertEqual(tier.min_shipments, 160)
            self.assertEqual(tier.max_shipments, 200)

    def test_api_price_takes_precedence(self):
        bd = CostEngine(self.backend).compute(
            destination_governorate="Giza",
            package_size_code="small",
            api_base_price=120.0,
        )
        self.assertEqual(bd.base_fee, 120.0)
        self.assertEqual(bd.pricing_source, "api")


class TestTryAndBuy(ShipBluOpsCase):
    def test_try_and_buy_shopify_ok(self):
        ship = self.env["shipblu.shipment"].create(
            {
                "name": "SB-TAB-1",
                "backend_id": self.backend.id,
                "company_id": self.backend.company_id.id,
                "business_reference": "uat-tab-shopify",
                "creation_source": "shopify",
                "shopify_order_id": "999",
                "try_and_buy_requested": True,
            }
        )
        self.assertTrue(ship.try_and_buy_eligible)
        bd = CostEngine(self.backend).compute(
            destination_governorate="Giza",
            package_size_code="small",
            try_and_buy=True,
        )
        self.assertEqual(bd.try_and_buy_fee, 40.0)

    def test_try_and_buy_non_shopify_rejected(self):
        ship = self.env["shipblu.shipment"].create(
            {
                "name": "SB-TAB-2",
                "backend_id": self.backend.id,
                "company_id": self.backend.company_id.id,
                "business_reference": "uat-tab-odoo",
                "creation_source": "odoo",
                "try_and_buy_requested": True,
            }
        )
        self.assertFalse(ship.try_and_buy_eligible)


class TestCreateGateAndCoverage(ShipBluOpsCase):
    def test_missing_package_size_blocks(self):
        self.backend.write(
            {
                "shipping_owner_mode": "odoo_owned",
                "shipment_creation_enabled": True,
                "default_package_size": 0,
            }
        )
        svc = ShipmentService(self.env)
        with self.assertRaises(UserError):
            svc.assert_can_create(False, self.backend, overrides={"zone": 83})

    def test_uncovered_destination_blocks_when_enabled(self):
        self.backend.write(
            {
                "shipping_owner_mode": "odoo_owned",
                "shipment_creation_enabled": True,
                "enable_coverage_blocking": True,
                "default_package_size": 1,
            }
        )
        svc = ShipmentService(self.env)
        with self.assertRaises(UserError):
            svc.assert_can_create(
                False,
                self.backend,
                overrides={"package_size": 1, "zone": 999999, "weight_kg": 1.0},
            )

    def test_create_blocked_in_track_only(self):
        self.backend.write(
            {
                "shipping_owner_mode": "track_only",
                "shipment_creation_enabled": False,
            }
        )
        with self.assertRaises(UserError):
            self.backend.assert_write_allowed("create")

    def test_zero_cod_wallet_warning_not_hard_block_by_default(self):
        self.backend.write(
            {
                "shipping_owner_mode": "odoo_owned",
                "shipment_creation_enabled": True,
                "enable_wallet_validation": True,
                "enable_wallet_hard_block": False,
                "wallet_balance_source": "manual",
                "wallet_balance_manual": 0.0,
                "default_package_size": 1,
            }
        )
        svc = ShipmentService(self.env)
        svc.assert_can_create(
            False,
            self.backend,
            overrides={"package_size": 1, "zone": 83, "cash_amount": 0.0, "weight_kg": 1.0},
        )


class TestSettlementAndSla(ShipBluOpsCase):
    def test_settlement_transfer_fee_default(self):
        sett = self.env["shipblu.settlement"].create(
            {
                "backend_id": self.backend.id,
                "period_start": "2026-07-01",
                "period_end": "2026-07-07",
                "gross_cod": 1000.0,
            }
        )
        self.assertEqual(sett.transfer_fee, 70.0)
        self.assertTrue(sett.account_missing_warning)

    def test_sla_calculation(self):
        ship = self.env["shipblu.shipment"].create(
            {
                "name": "SB-SLA-1",
                "backend_id": self.backend.id,
                "company_id": self.backend.company_id.id,
                "business_reference": "uat-sla-1",
                "destination_region": "Giza",
            }
        )
        ship.action_compute_sla()
        self.assertTrue(ship.sla_rule_id)
        self.assertTrue(ship.eta_start)
        self.assertTrue(ship.eta_end)


class TestPickupBatch(ShipBluOpsCase):
    def test_below_minimum_requires_confirmation(self):
        self.backend.write(
            {
                "shipping_owner_mode": "odoo_owned",
                "shipment_creation_enabled": True,
            }
        )
        ship = self.env["shipblu.shipment"].create(
            {
                "name": "SB-PKB-1",
                "backend_id": self.backend.id,
                "company_id": self.backend.company_id.id,
                "business_reference": "uat-pkb-1",
                "shipblu_order_id": "remote-1",
                "package_size_shipblu_id": 1,
                "package_count": 1,
                "label_status": "downloaded",
                "coverage_status": "covered",
            }
        )
        batch = self.env["shipblu.pickup.batch"].create(
            {
                "backend_id": self.backend.id,
                "planned_pickup_date": "2026-07-31",
                "shipment_ids": [(6, 0, ship.ids)],
            }
        )
        self.assertTrue(batch.below_minimum)
        self.assertEqual(batch.estimated_low_volume_surcharge, 65.0)
        with self.assertRaises(UserError):
            batch.action_submit_pickup()
