# -*- coding: utf-8 -*-
"""My Work / managed activity orchestration tests."""

import time

from odoo import Command, fields
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.petspot_fulfillment_vetution.models.ops_activity import (
    ACTION_MAPPING_REQUIRED,
    ACTION_DELIVERY_PRICE_REVIEW,
)


@tagged("post_install", "-at_install", "petspot_fulfillment_vetution", "petspot_ops")
class TestOpsActivities(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        stamp = int(time.time() * 1000)
        ff_user = cls.env.ref("petspot_fulfillment.group_fulfillment_user").id
        ff_mgr = cls.env.ref("petspot_fulfillment.group_fulfillment_manager").id
        base_user = cls.env.ref("base.group_user").id
        cls.product_user = cls.env["res.users"].create(
            {
                "name": "Ops Product Owner",
                "login": "ops_product_owner_%s" % stamp,
                "group_ids": [Command.set([ff_user, base_user])],
            }
        )
        cls.manager = cls.env["res.users"].create(
            {
                "name": "Ops Manager",
                "login": "ops_manager_%s" % stamp,
                "group_ids": [Command.set([ff_mgr, base_user])],
            }
        )
        cls.company.write(
            {
                "petspot_ops_owner_product_id": cls.product_user.id,
                "petspot_ops_owner_manager_id": cls.manager.id,
                "petspot_ops_owner_shipping_id": cls.manager.id,
                "petspot_ops_owner_purchasing_id": cls.manager.id,
            }
        )
        cls.partner = cls.env["res.partner"].create({"name": "Ops Cust", "phone": "+201000009900"})
        cls.unmapped = cls.env["product.product"].create(
            {"name": "Ops Unmapped", "default_code": "OPS-UNMAP", "type": "consu"}
        )

    def _inquiry(self, product, fulfillment="store_pickup"):
        return self.env["petspot.availability.inquiry"].create(
            {
                "phone": self.partner.phone,
                "partner_id": self.partner.id,
                "product_id": product.id,
                "default_code": product.default_code,
                "requested_qty": 1.0,
                "requested_fulfillment": fulfillment,
                "channel": "manual",
                "conversation_id": "ops-%s-%s" % (product.id, fields.Datetime.now()),
                "message_id": "ops-msg-%s" % fields.Datetime.now(),
            }
        )

    def test_mapping_creates_managed_activity_once(self):
        inq = self._inquiry(self.unmapped)
        self.env["petspot.vetution.shadow.assessment"].assess_inquiry(inq)
        inq._petspot_ops_sync()
        self.assertEqual(inq.ops_action_code, ACTION_MAPPING_REQUIRED)
        self.assertEqual(inq.ops_owner_id, self.product_user)
        acts = self.env["mail.activity"].search(
            [
                ("res_model", "=", "petspot.availability.inquiry"),
                ("res_id", "=", inq.id),
                ("petspot_managed", "=", True),
            ]
        )
        self.assertEqual(len(acts), 1)
        # idempotent
        inq._petspot_ops_sync()
        acts2 = self.env["mail.activity"].search(
            [
                ("res_model", "=", "petspot.availability.inquiry"),
                ("res_id", "=", inq.id),
                ("petspot_managed", "=", True),
                ("active", "=", True),
            ]
        )
        self.assertEqual(len(acts2), 1)
        self.assertEqual(acts2.petspot_action_code, ACTION_MAPPING_REQUIRED)

    def test_manual_activity_untouched(self):
        inq = self._inquiry(self.unmapped)
        manual = inq.activity_schedule(
            "mail.mail_activity_data_todo",
            summary="Manual note",
            user_id=self.env.uid,
        )
        self.env["petspot.vetution.shadow.assessment"].assess_inquiry(inq)
        inq._petspot_ops_sync()
        manual.invalidate_recordset()
        self.assertTrue(manual.exists())
        self.assertFalse(manual.petspot_managed)

    def test_mark_done_and_reassess_access(self):
        inq = self._inquiry(self.unmapped)
        self.env["petspot.vetution.shadow.assessment"].assess_inquiry(inq)
        inq._petspot_ops_sync()
        # wrong user
        other = self.env["res.users"].create(
            {
                "name": "Other FF",
                "login": "ops_other_%s" % int(time.time() * 1000),
                "group_ids": [
                    Command.set(
                        [
                            self.env.ref("petspot_fulfillment.group_fulfillment_user").id,
                            self.env.ref("base.group_user").id,
                        ]
                    )
                ],
            }
        )
        with self.assertRaises(AccessError):
            inq.with_user(other).action_ops_mark_done_and_reassess()

    def test_no_activity_when_cancelled(self):
        inq = self._inquiry(self.unmapped)
        self.env["petspot.vetution.shadow.assessment"].assess_inquiry(inq)
        inq._petspot_ops_sync()
        self.assertTrue(inq.ops_action_code)
        inq.state = "cancelled"
        inq._petspot_ops_sync()
        self.assertFalse(inq.ops_action_code)

    def test_delivery_price_review_code(self):
        """Delivery gate code maps to DELIVERY_PRICE_REVIEW_REQUIRED activity."""
        from unittest.mock import MagicMock, patch
        from odoo.addons.petspot_fulfillment_vetution.services.landed_cost_engine import (
            LandedCostEngine,
        )

        policy = self.env["petspot.vetution.landed.cost.policy"].search([], limit=1)
        if not policy:
            self.skipTest("no policy")
        fake = MagicMock()
        fake.base_fee = 196.0
        fake.size_surcharge = 0.0
        fake.pickup_surcharge = 0.0
        fake.discount = 0.0
        fake.cod_fee = 0.0
        fake.pricing_source = "contract"
        fake.notes = []
        fake.to_dict.return_value = {"base_fee": 196.0}
        with patch(
            "odoo.addons.petspot_shipblu_base.services.cost_engine.CostEngine.compute",
            return_value=fake,
        ):
            res = LandedCostEngine(self.env, policy).compute(
                supplier_cost=13.0,
                context={
                    "requested_fulfillment": "shipblu_delivery",
                    "destination_governorate": "North Coast",
                    "package_size_code": "small",
                    "payment_method": "paymob",
                },
            )
        self.assertEqual(res.delivery_decision_code, "DELIVERY_PRICE_REVIEW_REQUIRED")
        # Wire a fake assessment-like inquiry panel determination via sync path:
        # create inquiry and assessment stub fields by assessing a mapped product
        # when delivery review is set on assessment — covered by determine_action_code
        Ops = self.env["petspot.vetution.ops.activity"]
        # Minimal: force assessment-like record by assessing then patching codes
        product = self.env["product.product"].search(
            [("default_code", "=", "SHP-472-1065")], limit=1
        )
        if not product:
            self.skipTest("SHP-472-1065 missing")
        inq = self._inquiry(product, "shipblu_delivery")
        self.env["petspot.vetution.shadow.assessment"].assess_inquiry(inq)
        a = inq.vetution_assessment_id
        if a:
            # Clear higher-priority incomplete-cost signals so delivery gate wins.
            a.write(
                {
                    "delivery_decision_code": "DELIVERY_PRICE_REVIEW_REQUIRED",
                    "delivery_review_required": True,
                    "landed_cost_incomplete": False,
                    "product_decision_code": "OK",
                    "decision_code": "DELIVERY_PRICE_REVIEW_REQUIRED",
                    "state": "blocked",
                    "blockers": False,
                }
            )
            code = Ops.determine_action_code(inq)
            self.assertEqual(code, ACTION_DELIVERY_PRICE_REVIEW)

    def test_cron_repair_idempotent(self):
        inq = self._inquiry(self.unmapped)
        self.env["petspot.vetution.shadow.assessment"].assess_inquiry(inq)
        # clear panel without activity to force repair
        inq.with_context(petspot_ops_skip_sync=True).write(
            {"ops_action_code": False, "ops_activity_id": False}
        )
        self.env["petspot.availability.inquiry"].cron_petspot_ops_repair_activities()
        inq.invalidate_recordset()
        self.assertEqual(inq.ops_action_code, ACTION_MAPPING_REQUIRED)
        # second run does not duplicate
        self.env["petspot.availability.inquiry"].cron_petspot_ops_repair_activities()
        acts = self.env["mail.activity"].search(
            [
                ("res_model", "=", "petspot.availability.inquiry"),
                ("res_id", "=", inq.id),
                ("petspot_managed", "=", True),
                ("active", "=", True),
            ]
        )
        self.assertEqual(len(acts), 1)
