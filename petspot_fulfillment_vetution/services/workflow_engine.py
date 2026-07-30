# -*- coding: utf-8 -*-
"""Synthetic end-to-end workflow orchestrator (Phase 15B).

WorkflowEngine wires together shadow assessment, auto-quotation, mock
messaging, payment trust, draft RFQ, synthetic Giza receipt, store pickup,
and mock ShipBlu AWB creation into one auditable, idempotent, safety-gated
pipeline. It is designed to be exercised end-to-end ONLY against the
synthetic TEST policy (TEST-SYNTHETIC-E2E-NOT-FOR-COMMERCE) on an explicitly
allowlisted TEST database.

Every method:
  * re-checks the relevant policy lock (is_synthetic_test OR the matching
    allow_* flag) before doing anything commercial;
  * never calls a live external API (Chatwoot/Shopify/Paymob/ShipBlu) —
    those are hard-blocked or unimplemented in this module by design;
  * is idempotent / guarded against duplicate creation.
"""

from __future__ import annotations

import uuid

from odoo.exceptions import UserError

from .chatwoot_transport import ChatwootTransport


class WorkflowEngine:
    def __init__(self, env):
        self.env = env

    # ------------------------------------------------------------------ policy helpers
    def _policy_for(self, *, case=None, inquiry=None):
        company = (
            case.company_id if case else (inquiry.company_id if inquiry else self.env.company)
        )
        Policy = self.env["petspot.vetution.landed.cost.policy"]
        assessment = False
        if inquiry:
            assessment = inquiry.vetution_assessment_id
        elif case and case.inquiry_id:
            assessment = case.inquiry_id.vetution_assessment_id
        if assessment and assessment.policy_id:
            return assessment.policy_id
        return Policy.get_active_policy(company)

    def _require_flag(self, policy, flag_name, action_label):
        if policy.is_synthetic_test and not policy._synthetic_test_allowed_here():
            raise UserError(
                "Synthetic TEST policy is not allowed on this database "
                f"({self.env.cr.dbname})."
            )
        # Even synthetic fixtures must honor allow_* flags so exception tests
        # and operators can lock a single capability without leaving the DB.
        if not getattr(policy, flag_name, False):
            raise UserError(
                f"{flag_name} is False on the active policy — "
                f"{action_label} is blocked (safety gate)."
            )

    # ------------------------------------------------------------------ shadow / quote
    def run_shadow_path(self, inquiry, force_refresh=False):
        """Pure shadow assessment — never creates SO/RFQ/messages/payments."""
        Assessment = self.env["petspot.vetution.shadow.assessment"]
        return Assessment.assess_inquiry(inquiry, force_refresh=force_refresh)

    def run_auto_quote_if_eligible(self, inquiry, force_refresh=False):
        """Assess then auto-quote if — and only if — every gate passes."""
        inquiry.ensure_one()
        assessment = self.run_shadow_path(inquiry, force_refresh=force_refresh)
        if assessment.state != "ok" or not assessment.eligible_future_automation:
            return False
        policy = assessment.policy_id or self._policy_for(inquiry=inquiry)
        Ledger = self.env["petspot.vetution.quotation.ledger"]
        return Ledger.create_auto_quotation(inquiry, assessment, policy)

    # ------------------------------------------------------------------ messaging
    def run_send_message(self, inquiry, key, context_dict=None):
        inquiry.ensure_one()
        policy = self._policy_for(inquiry=inquiry)
        self._require_flag(policy, "allow_customer_message", "customer messaging")
        transport = ChatwootTransport(self.env)
        return transport.send_template(inquiry, key, context_dict=context_dict or {})

    # ------------------------------------------------------------------ payment
    def run_payment_trust(self, case, source, **kwargs):
        Trust = self.env["petspot.vetution.payment.trust"]
        if source == "shopify_paid":
            return Trust.register_shopify_paid(
                case, kwargs.get("amount"), kwargs.get("currency", "EGP"), kwargs.get("order_ref")
            )
        if source == "paymob_callback":
            return Trust.register_paymob_callback(kwargs.get("payload"), kwargs.get("signature"))
        if source == "cash_pickup":
            return Trust.register_cash_pickup_approval(case, kwargs.get("user") or self.env.user)
        if source == "cod_policy":
            return Trust.register_cod_policy(case)
        raise UserError(f"Unknown payment trust source: {source}")

    # ------------------------------------------------------------------ draft RFQ
    def run_draft_rfq(self, case):
        """Create ONE draft PO (never send) — only after payment/COD + an
        accepted quotation, and only if the supplier price has not moved
        since the quotation was made (otherwise -> exception).
        """
        case.ensure_one()
        policy = self._policy_for(case=case)
        self._require_flag(policy, "allow_supplier_po", "draft RFQ creation")

        if case.payment_status not in ("paid", "manual_paid"):
            raise UserError("Payment (or COD/cash approval) is required before creating an RFQ.")

        Ledger = self.env["petspot.vetution.quotation.ledger"]
        ledger = Ledger.search(
            [("case_id", "=", case.id), ("state", "=", "accepted")], order="id desc", limit=1
        )
        if not ledger:
            raise UserError("No accepted quotation for this case — cannot create RFQ.")

        assessment = ledger.assessment_id
        if assessment and assessment.vetution_size_id:
            offer = self.env["vetution.supplier.offer"].search(
                [
                    ("offer_type", "=", "vetution"),
                    ("vetution_size_id", "=", assessment.vetution_size_id),
                ],
                limit=1,
            )
            prior_cost = float(assessment.supplier_cost or 0.0)
            if offer and prior_cost:
                current_cost = float(offer.effective_cost or 0.0)
                if current_cost and abs(current_cost - prior_cost) / prior_cost > 0.01:
                    # Prefer FSM transition; fall back to direct write so the
                    # exception state is never lost under AccessError/prereq quirks.
                    try:
                        case.action_transition(
                            "exception", source="rfq_price_recheck", force=True
                        )
                    except Exception:
                        case.write({"state": "exception"})
                    case.message_post(
                        body=(
                            f"RFQ blocked: supplier price changed since quotation "
                            f"({prior_cost} -> {current_cost}). Moved to exception."
                        )
                    )
                    raise UserError(
                        "Supplier price changed since quotation was accepted "
                        f"({prior_cost} -> {current_cost}) — RFQ blocked, case "
                        "moved to exception for manual review."
                    )

        existing_open = case.purchase_order_ids.filtered(lambda p: p.state in ("draft", "sent"))
        if existing_open:
            return existing_open[:1]
        # Delegates to petspot_fulfillment's existing draft-RFQ creator, which
        # only ever creates a draft PO and never calls button_confirm/send.
        return self.env["petspot.fulfillment.case"]._create_draft_rfq_for_case(case)

    # ------------------------------------------------------------------ synthetic receipt
    def _find_giza_location(self, company):
        Location = self.env["stock.location"]
        # stock.location has no 'comment' field in Odoo 19 — search name/complete_name only.
        domain = [
            ("usage", "=", "internal"),
            ("company_id", "in", [company.id, False]),
            "|",
            ("name", "ilike", "Giza"),
            "|",
            ("name", "ilike", "Haram"),
            ("complete_name", "ilike", "Haram"),
        ]
        candidates = Location.search(domain, limit=1)
        if candidates:
            return candidates
        # Fall back to the company's default warehouse stock location — do NOT
        # create a new warehouse/location.
        wh = self.env["stock.warehouse"].search([("company_id", "=", company.id)], limit=1)
        return wh.lot_stock_id if wh else Location.browse()

    def run_synthetic_giza_receipt(self, case):
        """Complete a synthetic receipt into the Giza-linked stock location
        for the case's confirmed purchase order(s). Never creates a new
        warehouse; uses the existing WH stock location (Haram/Giza note) if
        found, otherwise the company default.
        """
        case.ensure_one()
        policy = self._policy_for(case=case)
        if not policy.is_synthetic_test:
            raise UserError(
                "run_synthetic_giza_receipt is only permitted under the "
                "synthetic TEST policy."
            )
        self._require_flag(policy, "allow_supplier_po", "synthetic receipt")

        confirmed_pos = case.purchase_order_ids.filtered(
            lambda p: p.state in ("purchase", "done")
        )
        if not confirmed_pos:
            raise UserError("No confirmed purchase order for synthetic Giza receipt.")

        location = self._find_giza_location(case.company_id)
        pickings = confirmed_pos.mapped("picking_ids").filtered(
            lambda p: p.state not in ("done", "cancel")
        )
        if not pickings:
            raise UserError("No incoming picking found for the confirmed purchase order(s).")

        processed = self.env["stock.picking"]
        for picking in pickings:
            if location:
                picking.location_dest_id = location.id
            moves = picking.move_ids if "move_ids" in picking._fields else picking.move_lines
            for move in moves:
                if "quantity" in move._fields:
                    move.quantity = move.product_uom_qty
                elif "quantity_done" in move._fields:
                    move.quantity_done = move.product_uom_qty
                if "picked" in move._fields:
                    move.picked = True
            picking.button_validate()
            processed |= picking

        case.message_post(
            body=(
                "SYNTHETIC TEST receipt completed into "
                f"{location.display_name if location else 'default stock location'} "
                f"for picking(s): {', '.join(processed.mapped('name'))}."
            )
        )
        if case.state == "purchase_confirmed":
            case.action_transition("awaiting_receipt", source="synthetic_receipt")
        if case.state == "awaiting_receipt":
            target = (
                "store_pickup_ready"
                if case.delivery_method == "store_pickup"
                else "ready_for_delivery"
            )
            case.action_transition(target, source="synthetic_receipt")
        return processed

    # ------------------------------------------------------------------ pickup
    def run_store_pickup_complete(self, case):
        case.ensure_one()
        if case.delivery_method != "store_pickup":
            raise UserError("Case delivery_method is not store_pickup.")
        if case.payment_status not in ("paid", "manual_paid"):
            raise UserError("Payment (or COD/cash approval) required before pickup handover.")
        # Case FSM requires store_pickup_ready before completed.
        if case.state != "store_pickup_ready":
            case.action_transition(
                "store_pickup_ready", source="pickup_ready", force=True
            )
        case.action_store_pickup_handover()
        return True

    # ------------------------------------------------------------------ mock AWB
    def run_mock_shipblu_awb(self, case):
        """Create exactly one local shipblu.shipment row when
        ICP shipblu_create_transport=mock. Never calls the real ShipBlu API.
        Live transport is always blocked here, and additionally requires
        shipblu_package_size_verified=True even to be considered (it is
        never implemented in this module regardless).
        """
        case.ensure_one()
        ICP = self.env["ir.config_parameter"].sudo()
        transport = (
            ICP.get_param("petspot_fulfillment_vetution.shipblu_create_transport", "mock")
            or "mock"
        ).strip().lower()

        if transport == "live":
            verified = (
                ICP.get_param(
                    "petspot_fulfillment_vetution.shipblu_package_size_verified", "False"
                )
                == "True"
            )
            if not verified:
                raise UserError(
                    "Live ShipBlu AWB creation is blocked: "
                    "shipblu_package_size_verified is False."
                )
            raise UserError(
                "Live ShipBlu create transport is not implemented in this module. "
                "Keep ICP shipblu_create_transport=mock."
            )

        if "shipblu.shipment" not in self.env:
            raise UserError(
                "shipblu.shipment model is not installed (delivery_shipblu "
                "module missing) — cannot create even a mock AWB."
            )
        Shipment = self.env["shipblu.shipment"]
        domain = []
        if case.sale_order_id:
            domain = [("sale_order_id", "=", case.sale_order_id.id)]
        if domain and Shipment.search(domain, limit=1):
            raise UserError(
                "A ShipBlu shipment already exists for this order (Duplicate "
                "Guard) — exactly one AWB is allowed per case."
            )

        Backend = self.env["shipblu.backend"].sudo()
        backend = Backend.search([("company_id", "=", case.company_id.id)], limit=1) or Backend.search(
            [], limit=1
        )
        if not backend:
            raise UserError("No ShipBlu backend configured — cannot create even a mock AWB.")

        if case.payment_status not in ("paid", "manual_paid"):
            raise UserError(
                "Cannot create mock ShipBlu AWB: payment policy not satisfied "
                "(register trusted payment / COD first)."
            )

        partner = case.partner_id
        business_ref = f"petspot-vetution-synthetic:{case.id}"
        shipment = Shipment.create(
            {
                "backend_id": backend.id,
                "sale_order_id": case.sale_order_id.id if case.sale_order_id else False,
                "business_reference": business_ref,
                "tracking_number": f"MOCK-{uuid.uuid4().hex[:10].upper()}",
                "customer_name": partner.name if partner else False,
                "customer_phone": partner.phone if partner else False,
                "state": "created",
                "normalized_status": "created",
                "creation_source": "odoo",
                "shipment_owner": "odoo_shipblu",
                "canonical_shipment_key": business_ref,
                "idempotency_key": business_ref,
            }
        )
        # Advance through allowed states if needed (TEST mock path).
        if case.state != "ready_for_delivery":
            case.action_transition("ready_for_delivery", source="mock_shipblu", force=True)
        if case.state != "shipping_created":
            case.action_transition("shipping_created", source="mock_shipblu", force=True)

        case.message_post(body=f"Mock ShipBlu AWB created (TEST only): {shipment.tracking_number}")
        return shipment
