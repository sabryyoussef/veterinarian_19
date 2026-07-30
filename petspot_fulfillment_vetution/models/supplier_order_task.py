# -*- coding: utf-8 -*-
"""RFQ/PO orchestration helpers — draft only; no unofficial Vetution purchase API."""

from odoo import api, fields, models
from odoo.exceptions import UserError


class PetspotVetutionSupplierOrderTask(models.Model):
    _name = "petspot.vetution.supplier.order.task"
    _description = "Manual Vetution Order Placement Task"
    _order = "id desc"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True, default="SUP-TASK")
    case_id = fields.Many2one("petspot.fulfillment.case", required=True, index=True, ondelete="cascade")
    purchase_order_id = fields.Many2one("purchase.order", copy=False)
    inquiry_id = fields.Many2one("petspot.availability.inquiry", index=True)
    vetution_size_id = fields.Integer(required=True)
    product_id = fields.Many2one("product.product", required=True)
    state = fields.Selection(
        [
            ("draft", "Draft RFQ ready"),
            ("awaiting_manual_placement", "Awaiting authorized manual placement"),
            ("placed_manual", "Placed manually"),
            ("price_exception", "Price-change exception"),
            ("partial", "Partial availability"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
        tracking=True,
        index=True,
    )
    recheck_ok = fields.Boolean(default=False)
    recheck_note = fields.Char()
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    _sql_constraints = [
        (
            "petspot_vetution_sup_task_case_uniq",
            "unique(case_id, company_id)",
            "One supplier order task per fulfillment case.",
        ),
    ]

    @api.model
    def ensure_for_case(self, case, *, quote_accepted=False, payment_ok=False):
        case.ensure_one()
        policy = self.env["petspot.vetution.landed.cost.policy"].get_active_policy()
        existing = self.search([("case_id", "=", case.id)], limit=1)
        if existing:
            return existing
        if not policy.allow_supplier_po and not policy.is_synthetic_test_fixture:
            raise UserError("Supplier PO automation locked (allow_supplier_po=False).")
        if not quote_accepted or not payment_ok:
            raise UserError("RFQ/PO only after quote acceptance and trusted payment/COD policy.")

        product = case.inquiry_id.product_id if case.inquiry_id else False
        if not product and case.sale_order_id:
            product = case.sale_order_id.order_line[:1].product_id
        if not product or not product.vetution_size_id:
            raise UserError("Exact Vetution size required for supplier task.")

        # Immediate availability/price recheck via offer
        offer = self.env["vetution.supplier.offer"].search(
            [("vetution_size_id", "=", product.vetution_size_id), ("offer_type", "=", "vetution")],
            limit=1,
        )
        recheck_ok = bool(offer and offer.effective_cost and offer.effective_cost > 0)
        note = "offer_ok" if recheck_ok else "offer_missing_or_zero"

        # Draft RFQ via case if available
        po = False
        if hasattr(case, "action_create_draft_rfq"):
            case.action_create_draft_rfq()
            po = case.purchase_order_ids[:1]

        task = self.create(
            {
                "name": f"SUP/{case.name or case.id}",
                "case_id": case.id,
                "inquiry_id": case.inquiry_id.id if case.inquiry_id else False,
                "purchase_order_id": po.id if po else False,
                "product_id": product.id,
                "vetution_size_id": product.vetution_size_id,
                "recheck_ok": recheck_ok,
                "recheck_note": note,
                "state": "awaiting_manual_placement" if recheck_ok else "price_exception",
            }
        )
        # Ops activity for authorized manual placement (no unofficial purchase API)
        task.activity_schedule(
            "mail.mail_activity_data_todo",
            summary="Place Vetution order manually (no unofficial API)",
            note="Official ordering API unavailable — authorized staff must place order manually.",
        )
        return task
