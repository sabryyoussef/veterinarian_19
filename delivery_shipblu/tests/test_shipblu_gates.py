# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase

from odoo.addons.delivery_shipblu.services.status_mapping import (
    coerce_raw_status,
    normalize_shipblu_status,
)


class TestShipBluStatusMapping(TransactionCase):
    def test_normalize_common_statuses(self):
        self.assertEqual(normalize_shipblu_status("CREATED"), "created")
        self.assertEqual(normalize_shipblu_status("OUT_FOR_DELIVERY"), "out_for_delivery")
        self.assertEqual(normalize_shipblu_status("DELIVERED"), "delivered")
        self.assertEqual(normalize_shipblu_status("CANCELLED"), "cancelled")
        self.assertEqual(normalize_shipblu_status("RETURN_TO_ORIGIN"), "returned")

    def test_coerce_raw_status(self):
        self.assertEqual(coerce_raw_status("created"), "CREATED")
        self.assertFalse(coerce_raw_status("NOT_A_REAL_STATUS"))
        self.assertFalse(coerce_raw_status(False))


class TestShipBluOwnershipGates(TransactionCase):
    def _backend(self, **vals):
        company = self.env["res.company"].create({"name": "ShipBlu Gate Co"})
        defaults = {
            "name": "ShipBlu Test Backend",
            "company_id": company.id,
            "api_key": "test-not-real",
            "shipping_owner_mode": "track_only",
            "shipment_creation_enabled": False,
        }
        defaults.update(vals)
        return self.env["shipblu.backend"].create(defaults)

    def test_track_only_blocks_create(self):
        backend = self._backend(shipping_owner_mode="track_only", shipment_creation_enabled=False)
        self.assertFalse(backend.can_create_shipments())
        with self.assertRaises(Exception):
            backend.assert_write_allowed("create")

    def test_odoo_owned_requires_package_and_flag(self):
        backend = self._backend(
            shipping_owner_mode="odoo_owned",
            shipment_creation_enabled=True,
            default_package_size=0,
        )
        self.assertFalse(backend.can_create_shipments())
        backend.default_package_size = 1
        self.assertTrue(backend.can_create_shipments())
