# -*- coding: utf-8 -*-
"""Automated tests for ShipBlu Duplicate AWB Guard."""

from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from odoo.addons.delivery_shipblu.services.duplicate_guard import DuplicateGuard, GuardHit
from odoo.addons.delivery_shipblu.services.shipment_service import ShipmentService
from odoo.addons.petspot_shipblu_base.services.shipblu_client import ShipBluApiError


class TestShipBluDuplicateGuard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Reuse main company — creating a new company trips project billing_type NOT NULL on this DB.
        cls.company = cls.env.company
        existing = cls.env["shipblu.backend"].search([("company_id", "=", cls.company.id)], limit=1)
        if existing:
            existing.write(
                {
                    "api_key": "test-not-real",
                    "shipping_owner_mode": "odoo_owned",
                    "shipment_creation_enabled": True,
                    "default_package_size": 1,
                    "default_zone_id": 83,
                }
            )
            cls.backend = existing
        else:
            cls.backend = cls.env["shipblu.backend"].create(
                {
                    "name": "ShipBlu Dup Backend",
                    "company_id": cls.company.id,
                    "api_key": "test-not-real",
                    "shipping_owner_mode": "odoo_owned",
                    "shipment_creation_enabled": True,
                    "default_package_size": 1,
                    "default_zone_id": 83,
                }
            )
        cls.partner = cls.env["res.partner"].create(
            {
                "name": "Dup Customer",
                "phone": "01012345678",
                "street": "451 Haram Street",
                "city": "Giza",
                "company_id": cls.company.id,
            }
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Dup Product", "type": "consu", "list_price": 100, "company_id": False}
        )
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1
        )
        assert cls.warehouse, "company needs a warehouse"

    def _sale_and_picking(self, shopify_order_id="991001"):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "company_id": self.company.id,
                "warehouse_id": self.warehouse.id,
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.product.id,
                            "product_uom_qty": 1,
                            "price_unit": 100,
                        },
                    )
                ],
            }
        )
        if "shopify_order_id" in order._fields:
            order.shopify_order_id = shopify_order_id
        order.action_confirm()
        picking = order.picking_ids[:1]
        self.assertTrue(picking)
        return order, picking

    def test_01_canonical_key_stable(self):
        order, picking = self._sale_and_picking("555")
        guard = DuplicateGuard(self.env)
        k1 = guard.canonical_shipment_key(picking)
        k2 = guard.canonical_shipment_key(picking)
        self.assertEqual(k1, k2)
        self.assertIn(":pick:%s" % picking.id, k1)
        self.assertIn("shopify-555", k1)
        # Same key used as merchant reference
        self.assertEqual(ShipmentService(self.env).business_reference_for_picking(picking), k1)

    def test_02_local_awb_blocks(self):
        _order, picking = self._sale_and_picking()
        picking.carrier_tracking_ref = "AWB-LOCAL-1"
        guard = DuplicateGuard(self.env)
        hit = guard.check_local_picking(picking)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.source, "local_awb")

    def test_03_imported_delivery_reconciles(self):
        order, picking = self._sale_and_picking("777")
        key = DuplicateGuard(self.env).canonical_shipment_key(picking)
        shipment = self.env["shipblu.shipment"].create(
            {
                "backend_id": self.backend.id,
                "company_id": self.company.id,
                "business_reference": key,
                "canonical_shipment_key": key,
                "shipblu_order_id": "90001",
                "tracking_number": "AWB-IMP-1",
                "sale_order_id": order.id,
                "creation_source": "shopify",
                "shipment_owner": "legacy_shopify",
                "state": "created",
            }
        )
        guard = DuplicateGuard(self.env)
        hit = guard.check_local_shipments(picking, key)
        self.assertEqual(hit.source, "imported_delivery")
        reconciled = guard.reconcile(picking, self.backend, hit, key)
        self.assertEqual(reconciled.id, shipment.id)
        self.assertEqual(picking.shipblu_order_id, "90001")
        self.assertEqual(picking.shipblu_duplicate_guard_status, "reconciled")

    def test_04_second_create_reconciles_not_posts(self):
        _order, picking = self._sale_and_picking("888")
        create_calls = []

        def fake_create(payload):
            create_calls.append(payload)
            return {"id": 42, "tracking_number": "AWB-ONCE", "status": "CREATED"}

        mock_client = MagicMock()
        mock_client.create_delivery_order.side_effect = fake_create
        mock_client.list_delivery_orders_filtered.return_value = {"results": []}
        mock_client.find_by_merchant_order_reference.return_value = None

        with patch.object(type(self.backend), "get_client", return_value=mock_client):
            with patch(
                "odoo.addons.delivery_shipblu.services.import_service.ImportService.import_delivery_orders",
                return_value={"message": "ok", "created": 0, "updated": 0, "matched": 0, "needs_matching": 0, "pages": 0},
            ):
                s1 = ShipmentService(self.env).create_from_picking(picking)
                self.assertEqual(s1.tracking_number, "AWB-ONCE")
                self.assertEqual(len(create_calls), 1)
                # Second click
                s2 = ShipmentService(self.env).create_from_picking(picking)
                self.assertEqual(len(create_calls), 1, "second create must not POST again")
                self.assertTrue(
                    s2.shipblu_order_id == "42" or picking.shipblu_order_id == "42",
                    "second call must keep linked ShipBlu order id",
                )
                picking.invalidate_recordset()
                self.assertEqual(picking.shipblu_order_id, "42")

    def test_05_shopify_fulfillment_detection(self):
        order, picking = self._sale_and_picking("999")
        # Sibling picking with ShipBlu tracking (simulate Shopify-imported)
        picking2 = picking.copy({"carrier_tracking_ref": "AWB-SHOP-1"})
        picking2.shipblu_shipment_owner = "legacy_shopify"
        # Ensure same SO
        picking2.sale_id = order
        guard = DuplicateGuard(self.env)
        hit = guard.check_shopify_fulfillment(picking)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.source, "shopify_fulfillment")

    def test_06_timeout_marks_verification_required_no_blind_retry(self):
        _order, picking = self._sale_and_picking("1001")
        mock_client = MagicMock()
        mock_client.list_delivery_orders_filtered.return_value = {"results": []}
        mock_client.find_by_merchant_order_reference.return_value = None
        mock_client.create_delivery_order.side_effect = ShipBluApiError(
            "timeout", status_code=504, transient=True
        )

        with patch.object(type(self.backend), "get_client", return_value=mock_client):
            with patch(
                "odoo.addons.delivery_shipblu.services.import_service.ImportService.import_delivery_orders",
                return_value={"message": "ok", "created": 0, "updated": 0, "matched": 0, "needs_matching": 0, "pages": 0},
            ):
                with self.assertRaises(UserError) as ctx:
                    ShipmentService(self.env).create_from_picking(picking)
                self.assertIn("verification_required", str(ctx.exception).lower())
                shipment = self.env["shipblu.shipment"].search(
                    [("picking_id", "=", picking.id)], limit=1
                )
                # In tests, UserError may roll back — assert message + no second POST when
                # we simulate a second attempt with verification state re-applied:
                if shipment and shipment.state == "verification_required":
                    with self.assertRaises(UserError):
                        ShipmentService(self.env).create_from_picking(picking)
                else:
                    shipment = self.env["shipblu.shipment"].create(
                        {
                            "backend_id": self.backend.id,
                            "company_id": self.company.id,
                            "picking_id": picking.id,
                            "business_reference": DuplicateGuard(self.env).canonical_shipment_key(picking)
                            + "-vr",
                            "canonical_shipment_key": DuplicateGuard(self.env).canonical_shipment_key(
                                picking
                            ),
                            "state": "verification_required",
                            "duplicate_guard_status": "verification_required",
                        }
                    )
                    picking.write(
                        {
                            "shipblu_canonical_key": shipment.canonical_shipment_key,
                            "shipblu_duplicate_guard_status": "verification_required",
                        }
                    )
                    with self.assertRaises(UserError):
                        ShipmentService(self.env).create_from_picking(picking)
                self.assertEqual(mock_client.create_delivery_order.call_count, 1)

    def test_07_timeout_then_remote_found_reconciles(self):
        _order, picking = self._sale_and_picking("1002")
        key = DuplicateGuard(self.env).canonical_shipment_key(picking)
        mock_client = MagicMock()
        mock_client.list_delivery_orders_filtered.return_value = {"results": []}
        mock_client.create_delivery_order.side_effect = ShipBluApiError(
            "timeout", status_code=0, transient=True
        )
        mock_client.find_by_merchant_order_reference.return_value = {
            "id": 77,
            "tracking_number": "AWB-RECOVERED",
            "status": "CREATED",
            "merchant_order_reference": key,
        }

        with patch.object(type(self.backend), "get_client", return_value=mock_client):
            with patch(
                "odoo.addons.delivery_shipblu.services.import_service.ImportService.import_delivery_orders",
                return_value={"message": "ok", "created": 0, "updated": 0, "matched": 0, "needs_matching": 0, "pages": 0},
            ):
                shipment = ShipmentService(self.env).create_from_picking(picking)
                self.assertEqual(shipment.tracking_number, "AWB-RECOVERED")
                self.assertEqual(shipment.shipblu_order_id, "77")

    def test_08_remote_precheck_failure_fail_closed(self):
        _order, picking = self._sale_and_picking("1003")
        mock_client = MagicMock()
        mock_client.list_delivery_orders_filtered.side_effect = ShipBluApiError(
            "down", status_code=500, transient=True
        )

        with patch.object(type(self.backend), "get_client", return_value=mock_client):
            with patch(
                "odoo.addons.delivery_shipblu.services.import_service.ImportService.import_delivery_orders",
                return_value={"message": "ok", "created": 0, "updated": 0, "matched": 0, "needs_matching": 0, "pages": 0},
            ):
                with self.assertRaises(UserError) as ctx:
                    ShipmentService(self.env).create_from_picking(picking)
                self.assertIn("fail-closed", str(ctx.exception).lower())
                mock_client.create_delivery_order.assert_not_called()

    def test_09_multi_picking_different_keys(self):
        order, picking1 = self._sale_and_picking("2000")
        # Force second outgoing picking
        picking2 = picking1.copy()
        picking2.sale_id = order
        g = DuplicateGuard(self.env)
        k1 = g.canonical_shipment_key(picking1)
        k2 = g.canonical_shipment_key(picking2)
        self.assertNotEqual(k1, k2)
        self.assertIn(f"pick:{picking1.id}", k1)
        self.assertIn(f"pick:{picking2.id}", k2)

    def test_10_retry_same_idempotency_key(self):
        _order, picking = self._sale_and_picking("3000")
        keys = []

        def fake_create(payload):
            keys.append(payload["merchant_order_reference"])
            return {"id": 11, "tracking_number": "AWB-IDEM", "status": "CREATED"}

        mock_client = MagicMock()
        mock_client.create_delivery_order.side_effect = fake_create
        mock_client.list_delivery_orders_filtered.return_value = {"results": []}
        mock_client.find_by_merchant_order_reference.return_value = None
        expected = DuplicateGuard(self.env).canonical_shipment_key(picking)

        with patch.object(type(self.backend), "get_client", return_value=mock_client):
            with patch(
                "odoo.addons.delivery_shipblu.services.import_service.ImportService.import_delivery_orders",
                return_value={"message": "ok", "created": 0, "updated": 0, "matched": 0, "needs_matching": 0, "pages": 0},
            ):
                ShipmentService(self.env).create_from_picking(picking)
        self.assertEqual(keys, [expected])

    def test_11_return_not_treated_as_outbound(self):
        """Return orders live on shipblu.return.order — must not block outbound create via SO link alone."""
        order, picking = self._sale_and_picking("4000")
        self.env["shipblu.return.order"].create(
            {
                "name": "RET-1",
                "backend_id": self.backend.id,
                "company_id": self.company.id,
                "shipblu_return_id": "R-1",
                "tracking_number": "AWB-RETURN",
            }
        )
        guard = DuplicateGuard(self.env)
        key = guard.canonical_shipment_key(picking)
        hit = guard.check_local_shipments(picking, key)
        self.assertIsNone(hit)

    def test_12_concurrent_second_sees_local_after_first(self):
        """Simulate two sequential create attempts under lock semantics."""
        _order, picking = self._sale_and_picking("5000")
        mock_client = MagicMock()
        mock_client.list_delivery_orders_filtered.return_value = {"results": []}
        mock_client.find_by_merchant_order_reference.return_value = None
        mock_client.create_delivery_order.return_value = {
            "id": 55,
            "tracking_number": "AWB-CONC",
            "status": "CREATED",
        }
        with patch.object(type(self.backend), "get_client", return_value=mock_client):
            with patch(
                "odoo.addons.delivery_shipblu.services.import_service.ImportService.import_delivery_orders",
                return_value={"message": "ok", "created": 0, "updated": 0, "matched": 0, "needs_matching": 0, "pages": 0},
            ):
                ShipmentService(self.env).create_from_picking(picking)
                ShipmentService(self.env).create_from_picking(picking)
        self.assertEqual(mock_client.create_delivery_order.call_count, 1)
