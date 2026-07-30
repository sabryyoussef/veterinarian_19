# -*- coding: utf-8 -*-
"""Ownership / status gates for ShipBlu.

Why ``billing_type`` appeared in the failure
--------------------------------------------
These tests only need a ``shipblu.backend``. Creating a *new* ``res.company``
triggers ``hr_timesheet`` → ``_create_internal_project_task``, which inserts an
``Internal`` ``project.project`` without ``billing_type``.

On this database ``sale_timesheet`` installed a required column
``project_project.billing_type`` (legitimate values: ``not_billable``,
``manually``) with **no SQL DEFAULT**, so the Internal-project INSERT hits
``NOT NULL``. The fixture was incomplete because it created a company (and thus
an Internal project) without ensuring ``billing_type``.

Fix: reuse ``env.company`` so no Internal project is auto-created. When a
project is created explicitly in tests, pass ``billing_type='not_billable'``.
We do not relax Production constraints, skip, xfail, or swallow the error.
"""
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
    def _ensure_project_billing_type(self, project):
        """Populate a legitimate sale_timesheet billing_type when the field exists."""
        if "billing_type" in project._fields and not project.billing_type:
            project.write({"billing_type": "not_billable"})
        return project

    def _backend(self, **vals):
        # Reuse main company — avoids hr_timesheet Internal project create without billing_type.
        company = self.env.company
        Project = self.env["project.project"]
        if "billing_type" in Project._fields:
            for proj in Project.search([("company_id", "=", company.id)]):
                self._ensure_project_billing_type(proj)
        else:
            # Schema drift safety: column may exist as NOT NULL without ORM field in some load paths.
            self.env.cr.execute(
                """
                UPDATE project_project
                   SET billing_type = 'not_billable'
                 WHERE company_id = %s
                   AND (billing_type IS NULL OR billing_type = '')
                """,
                (company.id,),
            )

        existing = self.env["shipblu.backend"].search([("company_id", "=", company.id)], limit=1)
        defaults = {
            "name": "ShipBlu Test Backend",
            "company_id": company.id,
            "api_key": "test-not-real",
            "shipping_owner_mode": "track_only",
            "shipment_creation_enabled": False,
            "default_package_size": 0,
        }
        defaults.update(vals)
        if existing:
            existing.write(defaults)
            return existing
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
