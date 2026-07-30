# -*- coding: utf-8 -*-
from odoo.tests import tagged, TransactionCase
from odoo.exceptions import UserError


@tagged("post_install", "-at_install", "petspot_fulfillment")
class TestPetspotFulfillment(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "FF Test Customer", "phone": "01000000001"})
        cls.vendor = cls.env["res.partner"].create({"name": "FF Test Vendor", "supplier_rank": 1})
        cls.product_store = cls.env["product.product"].create({
            "name": "FF Store Product",
            "type": "consu",
            "list_price": 100.0,
            "standard_price": 40.0,
            "default_code": "FF-STORE-1",
        })
        cls.product_b2b = cls.env["product.product"].create({
            "name": "FF B2B Product",
            "type": "consu",
            "list_price": 200.0,
            "standard_price": 80.0,
            "default_code": "FF-B2B-1",
            "seller_ids": [(0, 0, {"partner_id": cls.vendor.id, "price": 75.0})],
        })
        cls.Case = cls.env["petspot.fulfillment.case"]
        cls.Inquiry = cls.env["petspot.availability.inquiry"]

    def _sale(self, product, shopify_order_id=None, financial="pending"):
        vals = {
            "partner_id": self.partner.id,
            "order_line": [(0, 0, {
                "product_id": product.id,
                "product_uom_qty": 1.0,
                "price_unit": product.list_price,
            })],
        }
        if shopify_order_id and "shopify_order_id" in self.env["sale.order"]._fields:
            vals["shopify_order_id"] = shopify_order_id
            total = product.list_price
            if "shopify_order_total" in self.env["sale.order"]._fields:
                vals["shopify_order_total"] = total
            if financial in ("paid", "partially_paid") and "shopify_amount_paid" in self.env["sale.order"]._fields:
                vals["shopify_amount_paid"] = total if financial == "paid" else total * 0.5
            elif "shopify_amount_paid" in self.env["sale.order"]._fields:
                vals["shopify_amount_paid"] = 0.0
        return self.env["sale.order"].create(vals)

    def test_01_sale_imports_one_case(self):
        so = self._sale(self.product_b2b, shopify_order_id="900001")
        case1 = self.Case.get_or_create_for_sale_order(so)
        case2 = self.Case.get_or_create_for_sale_order(so)
        self.assertEqual(case1, case2)
        self.assertTrue(case1.idempotency_key)

    def test_02_webhook_replay_no_duplicate_case(self):
        so = self._sale(self.product_b2b, shopify_order_id="900002")
        c1 = self.Case.get_or_create_for_sale_order(so)
        # Simulate replay via same shopify ids
        c2 = self.Case.search([
            ("shopify_order_id", "=", "900002"),
        ])
        self.assertEqual(len(c2), 1)
        self.assertEqual(c2, c1)

    def test_03_supplier_rfq_once(self):
        so = self._sale(self.product_b2b, shopify_order_id="900003", financial="paid")
        case = self.Case.get_or_create_for_sale_order(so)
        case._auto_classify(force=True)
        case.payment_status = "paid"
        case.state = "paid"
        self.Case._create_draft_rfq_for_case(case)
        self.assertEqual(len(case.purchase_order_ids), 1)
        po_id = case.purchase_order_ids.id
        self.Case._create_draft_rfq_for_case(case)
        self.assertEqual(case.purchase_order_ids.id, po_id)

    def test_04_missing_vendor_blocks(self):
        orphan = self.env["product.product"].create({
            "name": "FF No Vendor",
            "type": "consu",
            "list_price": 50.0,
            "default_code": "FF-ORPHAN",
        })
        so = self._sale(orphan, shopify_order_id="900004")
        case = self.Case.get_or_create_for_sale_order(so)
        for line in case.line_ids:
            line.source = "supplier_b2b"
            line.vendor_id = False
        with self.assertRaises(UserError):
            self.Case._create_draft_rfq_for_case(case)

    def test_05_supplier_reject_exception_if_paid(self):
        so = self._sale(self.product_b2b, shopify_order_id="900005", financial="paid")
        case = self.Case.get_or_create_for_sale_order(so)
        case.payment_status = "paid"
        case.state = "supplier_rfq"
        wiz = self.env["petspot.supplier.confirm.wizard"].create({
            "case_id": case.id,
            "available": False,
            "notes": "Out of stock at supplier",
        })
        wiz.action_confirm()
        self.assertEqual(case.state, "exception")
        self.assertEqual(case.payment_status, "refund_review")

    def test_06_price_change_requires_approval(self):
        so = self._sale(self.product_b2b, shopify_order_id="900006", financial="paid")
        case = self.Case.get_or_create_for_sale_order(so)
        case.state = "supplier_rfq"
        wiz = self.env["petspot.supplier.confirm.wizard"].create({
            "case_id": case.id,
            "available": True,
            "supplier_cost": 90.0,
            "price_changed": True,
        })
        wiz.action_confirm()
        self.assertEqual(case.state, "customer_approval_required")
        self.assertTrue(case.customer_approval_required)

    def test_07_unpaid_cannot_ship(self):
        so = self._sale(self.product_b2b, shopify_order_id="900007", financial="pending")
        case = self.Case.get_or_create_for_sale_order(so)
        case.payment_status = "unpaid"
        case.state = "ready_for_delivery"
        case.delivery_method = "shipblu_delivery"
        with self.assertRaises(UserError):
            case.action_create_shipblu()

    def test_08_paid_shopify_status_retained(self):
        so = self._sale(self.product_b2b, shopify_order_id="900008", financial="paid")
        case = self.Case.get_or_create_for_sale_order(so)
        self.assertEqual(case.payment_status, "paid")
        self.assertIn((case.shopify_financial_status or "").lower(), ("paid", "partially_paid"))
        self.assertGreaterEqual(so.shopify_amount_paid, so.shopify_order_total)

    def test_09_inquiry_alone_creates_no_sale(self):
        inq = self.Inquiry.create({
            "phone": "01000000099",
            "product_id": self.product_store.id,
            "requested_qty": 2,
            "channel": "manual",
        })
        self.assertFalse(inq.sale_order_id)
        self.assertFalse(inq.case_id)
        self.assertEqual(inq.state, "draft")

    def test_10_inquiry_quotation_idempotent(self):
        inq = self.Inquiry.create({
            "phone": "01000000098",
            "product_id": self.product_store.id,
            "requested_qty": 1,
            "channel": "whatsapp",
            "message_id": "msg-unique-10",
        })
        inq.action_create_quotation()
        so = inq.sale_order_id
        self.assertTrue(so)
        inq.action_create_quotation()
        self.assertEqual(inq.sale_order_id, so)
        self.assertEqual(inq.case_id.path, "manual_whatsapp")

    def test_11_store_stock_no_unnecessary_po(self):
        so = self._sale(self.product_store, shopify_order_id="900011", financial="paid")
        case = self.Case.get_or_create_for_sale_order(so)
        for line in case.line_ids:
            line.source = "store_stock"
        case.path = "store_stock"
        case.payment_status = "paid"
        # Should error — no b2b lines
        with self.assertRaises(UserError):
            self.Case._create_draft_rfq_for_case(case)
        self.assertFalse(case.purchase_order_ids)

    def test_12_store_pickup_blocks_shipblu(self):
        so = self._sale(self.product_store, shopify_order_id="900012", financial="paid")
        case = self.Case.get_or_create_for_sale_order(so)
        case.write({
            "payment_status": "paid",
            "state": "ready_for_delivery",
            "delivery_method": "store_pickup",
        })
        with self.assertRaises(UserError):
            case.action_create_shipblu()

    def test_13_mixed_lines_sources(self):
        vals = {
            "partner_id": self.partner.id,
            "order_line": [
                (0, 0, {"product_id": self.product_store.id, "product_uom_qty": 1, "price_unit": 100}),
                (0, 0, {"product_id": self.product_b2b.id, "product_uom_qty": 1, "price_unit": 200}),
            ],
        }
        if "shopify_order_id" in self.env["sale.order"]._fields:
            vals["shopify_order_id"] = "900013"
        so = self.env["sale.order"].create(vals)
        case = self.Case.get_or_create_for_sale_order(so)
        case._auto_classify(force=True)
        sources = set(case.line_ids.mapped("source"))
        self.assertIn("supplier_b2b", sources)
        # store line has no vendor and no stock → unclassified → mixed path
        self.assertTrue({"unclassified", "store_stock"} & sources or case.path == "mixed")
        self.assertEqual(case.path, "mixed")

    def test_14_transition_audit_log(self):
        so = self._sale(self.product_store, shopify_order_id="900014")
        case = self.Case.get_or_create_for_sale_order(so)
        case.state = "new"
        case.action_transition("availability_check", source="test")
        self.assertEqual(len(case.transition_ids), 1)
        self.assertEqual(case.transition_ids.to_state, "availability_check")

    def test_15_purchase_confirm_requires_payment(self):
        so = self._sale(self.product_b2b, shopify_order_id="900015")
        case = self.Case.get_or_create_for_sale_order(so)
        case._auto_classify(force=True)
        case.state = "supplier_confirmed"
        case.payment_status = "unpaid"
        case.supplier_confirmed = True
        self.Case._create_draft_rfq_for_case(case)
        with self.assertRaises(UserError):
            case.action_confirm_purchase()

    def test_16_historical_cutover_skips_auto_case(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "petspot_fulfillment.cutover_timestamp",
            "2099-01-01 00:00:00",
        )
        so = self._sale(self.product_store, shopify_order_id="900016")
        # create hook should skip; explicit get still allowed for reconciliation
        self.assertFalse(self.Case.search([("sale_order_id", "=", so.id)]))
        self.assertFalse(self.Case._is_cutover_eligible(so))
        self.env["ir.config_parameter"].sudo().set_param(
            "petspot_fulfillment.cutover_timestamp", ""
        )

    def test_17_shipblu_blocked_before_ready(self):
        so = self._sale(self.product_b2b, shopify_order_id="900017", financial="paid")
        case = self.Case.get_or_create_for_sale_order(so)
        case.write({
            "payment_status": "paid",
            "state": "paid",
            "delivery_method": "shipblu_delivery",
            "supplier_confirmed": True,
        })
        with self.assertRaises(UserError):
            case.action_create_shipblu()

    def test_18_receipt_enables_ready(self):
        so = self._sale(self.product_b2b, shopify_order_id="900018", financial="paid")
        case = self.Case.get_or_create_for_sale_order(so)
        case.write({
            "payment_status": "paid",
            "state": "awaiting_receipt",
            "delivery_method": "shipblu_delivery",
            "supplier_confirmed": True,
        })
        case.action_mark_ready_for_delivery()
        self.assertEqual(case.state, "ready_for_delivery")

    def test_19_access_mark_paid_manager_only(self):
        so = self._sale(self.product_store, shopify_order_id="900019")
        case = self.Case.get_or_create_for_sale_order(so)
        user = self.env["res.users"].create({
            "name": "FF Limited",
            "login": "ff_limited_%s" % so.id,
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("petspot_fulfillment.group_fulfillment_user").id,
            ])],
        })
        wiz = self.env["petspot.mark.paid.wizard"].create({
            "case_id": case.id,
            "payment_reference": "X-1",
        })
        from odoo.exceptions import AccessError
        with self.assertRaises(AccessError):
            wiz.with_user(user).action_confirm()

    def test_20_availability_mode_untouched(self):
        """Catalog metafield / product data must not be written by this module."""
        tmpl = self.product_store.product_tmpl_id
        before = tmpl.write_date
        inq = self.Inquiry.create({
            "phone": "01000000120",
            "product_id": self.product_store.id,
            "channel": "manual",
        })
        inq.action_check_store()
        tmpl.invalidate_recordset()
        self.assertEqual(tmpl.write_date, before)
