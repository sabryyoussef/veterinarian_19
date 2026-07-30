# -*- coding: utf-8 -*-
"""Trusted payment registration ledger (Phase 15B synthetic workflow).

Only trusted payment signals are ever accepted: Shopify's own paid status,
a verified Paymob callback, a staff-approved cash-on-pickup, or an explicit
COD policy acceptance. WhatsApp screenshots/claims are never a source here.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from odoo import api, fields, models
from odoo.exceptions import ValidationError

PAYMOB_SECRET_ICP = "petspot_fulfillment_vetution.paymob_hmac_secret"


class PetspotVetutionPaymentTrust(models.Model):
    _name = "petspot.vetution.payment.trust"
    _description = "Vetution Payment Trust Record"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char(required=True, default="PAY")
    case_id = fields.Many2one("petspot.fulfillment.case", index=True)
    inquiry_id = fields.Many2one("petspot.availability.inquiry", index=True)
    source = fields.Selection(
        [
            ("shopify_paid", "Shopify Paid"),
            ("paymob_callback", "Paymob Callback"),
            ("cash_pickup", "Cash on Pickup"),
            ("cod_policy", "COD Policy"),
        ],
        required=True,
        index=True,
    )
    amount = fields.Float(required=True)
    currency = fields.Char(default="EGP", required=True)
    reference = fields.Char(required=True, index=True)
    payload_hash = fields.Char(index=True)
    state = fields.Selection(
        [
            ("accepted", "Accepted"),
            ("rejected", "Rejected"),
            ("duplicate", "Duplicate"),
            ("exception", "Exception"),
        ],
        default="accepted",
        required=True,
        index=True,
        tracking=True,
    )
    reject_reason = fields.Char()
    approved_by = fields.Many2one("res.users")
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )

    @api.constrains("source", "reference", "state")
    def _check_no_duplicate_accepted(self):
        for rec in self:
            if rec.state != "accepted":
                continue
            dup = self.search(
                [
                    ("source", "=", rec.source),
                    ("reference", "=", rec.reference),
                    ("state", "=", "accepted"),
                    ("id", "!=", rec.id),
                ],
                limit=1,
            )
            if dup:
                raise ValidationError(
                    "Duplicate accepted payment for source=%s reference=%s "
                    "(existing id=%s)." % (rec.source, rec.reference, dup.id)
                )

    @staticmethod
    def _hash(payload):
        return hashlib.sha256(
            json.dumps(payload or {}, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    @api.model
    def _expected_amount_currency(self, case):
        so = case.sale_order_id if case else False
        if not so:
            return None, None
        return float(so.amount_total or 0.0), (so.currency_id.name if so.currency_id else "EGP")

    @api.model
    def _register_payment(self, *, case, inquiry, source, amount, currency, reference, payload_hash=False, approved_by=False):
        reference = reference or f"unknown-{source}"
        existing = self.search(
            [("source", "=", source), ("reference", "=", reference), ("state", "=", "accepted")],
            limit=1,
        )
        company = case.company_id if case else (inquiry.company_id if inquiry else self.env.company)
        if existing:
            return self.create(
                {
                    "name": f"PAY/{source}/{reference}/dup",
                    "case_id": case.id if case else False,
                    "inquiry_id": inquiry.id if inquiry else False,
                    "source": source,
                    "amount": amount,
                    "currency": currency or "EGP",
                    "reference": reference,
                    "payload_hash": payload_hash or False,
                    "state": "duplicate",
                    "reject_reason": f"duplicate_of_id_{existing.id}",
                    "company_id": company.id,
                }
            )

        exp_amount, exp_currency = self._expected_amount_currency(case)
        state = "accepted"
        reason = False
        if exp_amount is not None and abs(exp_amount - float(amount or 0.0)) > 0.01:
            state = "rejected"
            reason = f"amount_mismatch expected={exp_amount} got={amount}"
        elif exp_currency and currency and exp_currency != currency:
            state = "rejected"
            reason = f"currency_mismatch expected={exp_currency} got={currency}"

        rec = self.create(
            {
                "name": f"PAY/{source}/{reference}",
                "case_id": case.id if case else False,
                "inquiry_id": inquiry.id if inquiry else False,
                "source": source,
                "amount": amount,
                "currency": currency or "EGP",
                "reference": reference,
                "payload_hash": payload_hash or False,
                "state": state,
                "reject_reason": reason,
                "approved_by": approved_by.id if approved_by else False,
                "company_id": company.id,
            }
        )
        if state == "accepted" and case:
            new_status = "manual_paid" if source in ("cash_pickup", "cod_policy") else "paid"
            case.write({"payment_status": new_status, "payment_reference": reference})
            if case.state in ("new", "payment_pending", "availability_check"):
                case.action_transition("paid", source="payment_trust")
        return rec

    # ------------------------------------------------------------------ sources
    @api.model
    def register_shopify_paid(self, case, amount, currency, order_ref):
        return self._register_payment(
            case=case,
            inquiry=case.inquiry_id if case else False,
            source="shopify_paid",
            amount=amount,
            currency=currency,
            reference=str(order_ref),
        )

    @api.model
    def register_paymob_callback(self, payload, signature=False):
        """Verify HMAC using ICP secret when configured. Without a secret,
        only payloads explicitly marked synthetic_mock_signed=True are
        accepted — this must NEVER be relied on outside the synthetic TEST
        workflow.
        """
        payload = dict(payload or {})
        ICP = self.env["ir.config_parameter"].sudo()
        secret = ICP.get_param(PAYMOB_SECRET_ICP, "") or ""
        reference = str(payload.get("order_id") or payload.get("reference") or payload.get("id") or "")
        if payload.get("amount") is not None:
            amount = float(payload.get("amount"))
        else:
            amount = float(payload.get("amount_cents", 0) or 0) / 100.0
        currency = payload.get("currency") or "EGP"
        case = self.env["petspot.fulfillment.case"]
        case_id = payload.get("case_id")
        if case_id:
            case = case.browse(int(case_id)).exists()
        payload_hash = self._hash(payload)

        if secret:
            expected = hmac.new(
                secret.encode("utf-8"), payload_hash.encode("utf-8"), hashlib.sha512
            ).hexdigest()
            verified = bool(signature) and hmac.compare_digest(expected, str(signature))
        else:
            verified = bool(payload.get("synthetic_mock_signed"))

        if not verified:
            return self.create(
                {
                    "name": f"PAY/paymob_callback/{reference or 'unverified'}",
                    "case_id": case.id if case else False,
                    "source": "paymob_callback",
                    "amount": amount,
                    "currency": currency,
                    "reference": reference or f"unverified-{payload_hash[:12]}",
                    "payload_hash": payload_hash,
                    "state": "rejected",
                    "reject_reason": "hmac_verification_failed",
                    "company_id": (case.company_id.id if case else self.env.company.id),
                }
            )
        return self._register_payment(
            case=case,
            inquiry=False,
            source="paymob_callback",
            amount=amount,
            currency=currency,
            reference=reference,
            payload_hash=payload_hash,
        )

    @api.model
    def register_cash_pickup_approval(self, case, user):
        case.ensure_one()
        amount, currency = self._expected_amount_currency(case)
        return self._register_payment(
            case=case,
            inquiry=case.inquiry_id,
            source="cash_pickup",
            amount=amount or 0.0,
            currency=currency or "EGP",
            reference=f"cash-pickup:{case.id}",
            approved_by=user,
        )

    @api.model
    def register_cod_policy(self, case):
        case.ensure_one()
        amount, currency = self._expected_amount_currency(case)
        return self._register_payment(
            case=case,
            inquiry=case.inquiry_id,
            source="cod_policy",
            amount=amount or 0.0,
            currency=currency or "EGP",
            reference=f"cod-policy:{case.id}",
        )
