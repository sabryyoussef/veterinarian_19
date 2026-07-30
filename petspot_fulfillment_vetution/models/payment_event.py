# -*- coding: utf-8 -*-
"""Trusted payment events — Shopify paid / signed Paymob / cash / COD. Never WhatsApp screenshots."""

from odoo import api, fields, models
from odoo.exceptions import UserError


class PetspotVetutionPaymentEvent(models.Model):
    _name = "petspot.vetution.payment.event"
    _description = "Trusted Payment Event"
    _order = "id desc"
    _inherit = ["mail.thread"]

    name = fields.Char(required=True, default="PAY")
    inquiry_id = fields.Many2one("petspot.availability.inquiry", index=True, ondelete="cascade")
    case_id = fields.Many2one("petspot.fulfillment.case", index=True, ondelete="set null")
    sale_order_id = fields.Many2one("sale.order", index=True)
    source = fields.Selection(
        [
            ("shopify_paid", "Shopify already-paid"),
            ("paymob_callback", "Signed Paymob callback"),
            ("cash_pickup", "Cash / store pickup approval"),
            ("cod_policy", "COD policy acceptance"),
            ("manual_trusted", "Manager Mark Paid"),
        ],
        required=True,
        index=True,
    )
    external_ref = fields.Char(required=True, index=True)
    amount = fields.Float(required=True)
    currency = fields.Char(default="EGP", required=True)
    signature_ok = fields.Boolean(default=False)
    state = fields.Selection(
        [
            ("accepted", "Accepted"),
            ("rejected", "Rejected"),
            ("duplicate", "Duplicate"),
            ("exception", "Manual exception"),
            ("refund_pending", "Refund pending"),
        ],
        required=True,
        default="accepted",
        tracking=True,
        index=True,
    )
    reject_reason = fields.Char()
    payload_json = fields.Text()
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    _sql_constraints = [
        (
            "petspot_vetution_pay_ext_uniq",
            "unique(source, external_ref, company_id)",
            "Duplicate payment callback / reference.",
        ),
    ]

    @api.model
    def ingest_trusted_payment(
        self,
        *,
        source,
        external_ref,
        amount,
        currency="EGP",
        inquiry=None,
        case=None,
        sale_order=None,
        signature_ok=False,
        expected_amount=None,
        payload=None,
    ):
        """Idempotent trusted payment ingest. Rejects wrong amount/currency/unsigned Paymob."""
        company = self.env.company
        existing = self.search(
            [
                ("source", "=", source),
                ("external_ref", "=", str(external_ref)),
                ("company_id", "=", company.id),
            ],
            limit=1,
        )
        if existing:
            existing.state = "duplicate"
            return existing

        reject = False
        reason = False
        if source == "paymob_callback" and not signature_ok:
            reject, reason = True, "unsigned_or_invalid_paymob_signature"
        if currency and str(currency).upper() != "EGP":
            reject, reason = True, "wrong_currency"
        if expected_amount is not None and abs(float(amount) - float(expected_amount)) > 0.05:
            reject, reason = True, "wrong_amount"
        if source in ("shopify_paid", "cash_pickup", "cod_policy", "manual_trusted"):
            # these do not require Paymob signature
            pass

        vals = {
            "name": f"PAY/{source}/{external_ref}",
            "source": source,
            "external_ref": str(external_ref),
            "amount": float(amount or 0.0),
            "currency": (currency or "EGP").upper(),
            "signature_ok": bool(signature_ok),
            "inquiry_id": inquiry.id if inquiry else False,
            "case_id": case.id if case else False,
            "sale_order_id": sale_order.id if sale_order else False,
            "payload_json": payload if isinstance(payload, str) else False,
            "state": "rejected" if reject else "accepted",
            "reject_reason": reason or False,
        }
        event = self.create(vals)
        if event.state == "accepted" and case:
            if case.payment_status not in ("paid", "manual_paid"):
                # Map to case paid via existing transition if available
                try:
                    if hasattr(case, "action_transition"):
                        case.write({"payment_status": "paid" if source != "manual_trusted" else "manual_paid"})
                        if case.state in ("new", "payment_pending", "quoted"):
                            case.action_transition("paid", source=f"payment_event:{source}", note=event.name)
                except Exception:  # noqa: BLE001
                    case.write({"payment_status": "paid"})
        return event
