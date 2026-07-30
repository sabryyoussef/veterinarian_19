# -*- coding: utf-8 -*-
"""Operator My Work — blocker → managed Odoo Activity orchestration.

Maps real Shadow Assessment decision/blocker codes to one idempotent
mail.activity on petspot.availability.inquiry. Never invokes live
Chatwoot / Shopify / ShipBlu / RFQ-send transports.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

# Stable action codes stored on mail.activity.petspot_action_code
ACTION_MAPPING_REQUIRED = "MAPPING_REQUIRED"
ACTION_SUPPLIER_DATA_STALE = "SUPPLIER_DATA_STALE"
ACTION_OOS = "OOS_REVIEW"
ACTION_INCOMPLETE_COST = "INCOMPLETE_COST_PROFILE"
ACTION_NEGATIVE_MARGIN = "NEGATIVE_MARGIN"
ACTION_PRICE_REVIEW = "PRICE_REVIEW_REQUIRED"
ACTION_DELIVERY_PRICE_REVIEW = "DELIVERY_PRICE_REVIEW_REQUIRED"
ACTION_QUOTATION_READY = "QUOTATION_READY"
ACTION_WAITING_ACCEPTANCE = "WAITING_CUSTOMER_ACCEPTANCE"
ACTION_QUOTATION_EXPIRED = "QUOTATION_EXPIRED"
ACTION_PAYMENT_PENDING = "PAYMENT_PENDING"
ACTION_PAYMENT_REJECTED = "PAYMENT_REJECTED"
ACTION_SUPPLIER_PRICE_CHANGED = "SUPPLIER_PRICE_CHANGED"
ACTION_READY_FOR_RFQ = "READY_FOR_RFQ"
ACTION_WAITING_GIZA_RECEIPT = "WAITING_GIZA_RECEIPT"
ACTION_PACKAGE_SIZE_REQUIRED = "PACKAGE_SIZE_REQUIRED"
ACTION_READY_FOR_SHIPMENT = "READY_FOR_SHIPMENT"
ACTION_SHIPMENT_FAILED = "SHIPMENT_FAILED"
ACTION_READY_FOR_PICKUP = "READY_FOR_PICKUP_HANDOVER"
ACTION_CONFIG_OWNER_MISSING = "OPS_OWNER_CONFIG_REQUIRED"
ACTION_SHADOW_OK_NO_WORK = False  # no activity

# Owner category keys → res.company field names
OWNER_FIELD = {
    "product": "petspot_ops_owner_product_id",
    "purchasing": "petspot_ops_owner_purchasing_id",
    "finance": "petspot_ops_owner_finance_id",
    "sales": "petspot_ops_owner_sales_id",
    "shipping": "petspot_ops_owner_shipping_id",
    "warehouse": "petspot_ops_owner_warehouse_id",
    "store": "petspot_ops_owner_store_id",
    "manager": "petspot_ops_owner_manager_id",
}

ACTION_DEFS = {
    ACTION_MAPPING_REQUIRED: {
        "summary": "Confirm Vetution product mapping",
        "blocker": "MAPPING_REQUIRED",
        "explanation": "Exact Shopify ↔ Odoo ↔ Vetution size identity is missing.",
        "owner": "product",
        "activity_type_xml": "petspot_fulfillment_vetution.mail_activity_type_mapping",
        "nav": "mapping_review",
        "category": "product_mapping",
        "deadline_days": 0,
    },
    ACTION_SUPPLIER_DATA_STALE: {
        "summary": "Refresh supplier availability and price",
        "blocker": "SUPPLIER_DATA_STALE",
        "explanation": "Supplier commercial data is stale or refresh failed.",
        "owner": "purchasing",
        "activity_type_xml": "petspot_fulfillment_vetution.mail_activity_type_purchasing",
        "nav": "data_health",
        "category": "purchasing",
        "deadline_days": 0,
    },
    ACTION_OOS: {
        "summary": "Review unavailable supplier offer",
        "blocker": "OOS",
        "explanation": "Supplier offer is out of stock or unavailable.",
        "owner": "purchasing",
        "activity_type_xml": "petspot_fulfillment_vetution.mail_activity_type_purchasing",
        "nav": "supplier_snapshot",
        "category": "purchasing",
        "deadline_days": 1,
    },
    ACTION_INCOMPLETE_COST: {
        "summary": "Complete missing landed-cost inputs",
        "blocker": "INCOMPLETE_COST_PROFILE",
        "explanation": "Landed-cost components are incomplete — do not invent zeros.",
        "owner": "purchasing",
        "activity_type_xml": "petspot_fulfillment_vetution.mail_activity_type_finance",
        "nav": "landed_cost_policy",
        "category": "finance",
        "deadline_days": 1,
    },
    ACTION_NEGATIVE_MARGIN: {
        "summary": "Review unprofitable product price",
        "blocker": "NEGATIVE_MARGIN",
        "explanation": "Suggested price fails margin / profit gates.",
        "owner": "manager",
        "activity_type_xml": "petspot_fulfillment_vetution.mail_activity_type_manager",
        "nav": "shadow_assessment",
        "category": "manager",
        "deadline_days": 0,
    },
    ACTION_PRICE_REVIEW: {
        "summary": "Review proposed selling price",
        "blocker": "PRICE_REVIEW_REQUIRED",
        "explanation": "Price change exceeds the permitted ± band or requires review.",
        "owner": "manager",
        "activity_type_xml": "petspot_fulfillment_vetution.mail_activity_type_manager",
        "nav": "shadow_assessment",
        "category": "manager",
        "deadline_days": 0,
    },
    ACTION_DELIVERY_PRICE_REVIEW: {
        "summary": "Review delivery charge or fulfillment method",
        "blocker": "DELIVERY_PRICE_REVIEW_REQUIRED",
        "explanation": "Carrier cost exceeds customer delivery charge / subsidy gate.",
        "owner": "shipping",
        "activity_type_xml": "petspot_fulfillment_vetution.mail_activity_type_shipping",
        "nav": "shadow_assessment",
        "category": "shipping",
        "deadline_days": 0,
    },
    ACTION_QUOTATION_READY: {
        "summary": "Review and send quotation",
        "blocker": "QUOTATION_READY",
        "explanation": "Assessment is ready for quotation (TEST synthetic / gated).",
        "owner": "sales",
        "activity_type_xml": "petspot_fulfillment_vetution.mail_activity_type_sales",
        "nav": "quotation_ledger",
        "category": "customer_followup",
        "deadline_days": 0,
    },
    ACTION_WAITING_ACCEPTANCE: {
        "summary": "Follow up quotation acceptance",
        "blocker": "WAITING_CUSTOMER_ACCEPTANCE",
        "explanation": "Quotation was sent — waiting for customer acceptance.",
        "owner": "sales",
        "activity_type_xml": "petspot_fulfillment_vetution.mail_activity_type_sales",
        "nav": "quotation_ledger",
        "category": "customer_followup",
        "deadline_days": 1,
    },
    ACTION_QUOTATION_EXPIRED: {
        "summary": "Reprice expired quotation",
        "blocker": "QUOTATION_EXPIRED",
        "explanation": "Open quotation expired — reassess and reissue.",
        "owner": "sales",
        "activity_type_xml": "petspot_fulfillment_vetution.mail_activity_type_sales",
        "nav": "quotation_ledger",
        "category": "customer_followup",
        "deadline_days": 0,
    },
    ACTION_PAYMENT_PENDING: {
        "summary": "Follow up customer payment",
        "blocker": "PAYMENT_PENDING",
        "explanation": "Quotation accepted — payment not yet trusted.",
        "owner": "sales",
        "activity_type_xml": "petspot_fulfillment_vetution.mail_activity_type_sales",
        "nav": "payment_trust",
        "category": "finance",
        "deadline_days": 1,
    },
    ACTION_PAYMENT_REJECTED: {
        "summary": "Review rejected payment event",
        "blocker": "PAYMENT_REJECTED",
        "explanation": "A payment trust/event was rejected.",
        "owner": "finance",
        "activity_type_xml": "petspot_fulfillment_vetution.mail_activity_type_finance",
        "nav": "payment_events",
        "category": "finance",
        "deadline_days": 0,
    },
    ACTION_SUPPLIER_PRICE_CHANGED: {
        "summary": "Review supplier price change after quote",
        "blocker": "SUPPLIER_PRICE_CHANGED",
        "explanation": "Supplier cost moved after quotation acceptance — RFQ blocked.",
        "owner": "purchasing",
        "activity_type_xml": "petspot_fulfillment_vetution.mail_activity_type_purchasing",
        "nav": "supplier_task",
        "category": "purchasing",
        "deadline_days": 0,
    },
    ACTION_READY_FOR_RFQ: {
        "summary": "Create draft supplier RFQ",
        "blocker": "READY_FOR_RFQ",
        "explanation": "Paid/COD — create draft RFQ only (never send live on Production).",
        "owner": "purchasing",
        "activity_type_xml": "petspot_fulfillment_vetution.mail_activity_type_purchasing",
        "nav": "supplier_task",
        "category": "purchasing",
        "deadline_days": 0,
    },
    ACTION_WAITING_GIZA_RECEIPT: {
        "summary": "Register Giza / Haram receipt",
        "blocker": "WAITING_GIZA_RECEIPT",
        "explanation": "Confirm goods into Giza/Haram stock location.",
        "owner": "warehouse",
        "activity_type_xml": "petspot_fulfillment_vetution.mail_activity_type_warehouse",
        "nav": "giza_receipt",
        "category": "giza_receipt",
        "deadline_days": 1,
    },
    ACTION_PACKAGE_SIZE_REQUIRED: {
        "summary": "Confirm ShipBlu package size",
        "blocker": "PACKAGE_SIZE_REQUIRED",
        "explanation": "Official ShipBlu package-size IDs are unverified.",
        "owner": "shipping",
        "activity_type_xml": "petspot_fulfillment_vetution.mail_activity_type_shipping",
        "nav": "shipblu_backend",
        "category": "shipping",
        "deadline_days": 2,
    },
    ACTION_READY_FOR_SHIPMENT: {
        "summary": "Prepare delivery shipment (mock on TEST)",
        "blocker": "READY_FOR_SHIPMENT",
        "explanation": "Ready for ShipBlu shipment — Production stays track-only / mock.",
        "owner": "shipping",
        "activity_type_xml": "petspot_fulfillment_vetution.mail_activity_type_shipping",
        "nav": "mock_awb",
        "category": "shipping",
        "deadline_days": 0,
    },
    ACTION_SHIPMENT_FAILED: {
        "summary": "Review shipment failure",
        "blocker": "SHIPMENT_FAILED",
        "explanation": "Shipment creation or sync failed.",
        "owner": "shipping",
        "activity_type_xml": "petspot_fulfillment_vetution.mail_activity_type_shipping",
        "nav": "mock_awb",
        "category": "shipping",
        "deadline_days": 0,
    },
    ACTION_READY_FOR_PICKUP: {
        "summary": "Complete store pickup handover",
        "blocker": "READY_FOR_PICKUP_HANDOVER",
        "explanation": "Goods ready — complete store pickup handover.",
        "owner": "store",
        "activity_type_xml": "petspot_fulfillment_vetution.mail_activity_type_store",
        "nav": "fulfillment_case",
        "category": "store_pickup",
        "deadline_days": 0,
    },
    ACTION_CONFIG_OWNER_MISSING: {
        "summary": "Configure PetSpot Ops activity owners",
        "blocker": "OPS_OWNER_CONFIG_REQUIRED",
        "explanation": "No valid owner configured for this action category.",
        "owner": "manager",
        "activity_type_xml": "petspot_fulfillment_vetution.mail_activity_type_manager",
        "nav": "settings",
        "category": "manager",
        "deadline_days": 0,
    },
}


class PetspotVetutionOpsActivity(models.AbstractModel):
    """Stateless helpers bound as env['petspot.vetution.ops.activity']."""

    _name = "petspot.vetution.ops.activity"
    _description = "PetSpot Vetution Ops Activity Orchestrator"

    # ------------------------------------------------------------------ determine
    @api.model
    def determine_action_code(self, inquiry):
        """Return the single highest-priority action code, or False if none."""
        inquiry.ensure_one()
        if inquiry.state in ("fulfilled", "cancelled"):
            return False
        case = inquiry.case_id
        if case and case.state in ("completed", "cancelled"):
            return False

        assessment = inquiry.vetution_assessment_id
        blockers = (assessment.blockers or "") if assessment else ""
        blocker_set = {b for b in blockers.split("|") if b}
        state = assessment.state if assessment else False
        product_code = assessment.product_decision_code if assessment else False
        delivery_code = assessment.delivery_decision_code if assessment else False
        decision = assessment.decision_code if assessment else False

        # Lifecycle signals from related records (safe reads only)
        Ledger = self.env["petspot.vetution.quotation.ledger"]
        open_quote = Ledger.search(
            [("inquiry_id", "=", inquiry.id), ("state", "in", ("draft", "sent", "expired"))],
            order="id desc",
            limit=1,
        )
        accepted = Ledger.search(
            [("inquiry_id", "=", inquiry.id), ("state", "=", "accepted")],
            order="id desc",
            limit=1,
        )
        Trust = self.env["petspot.vetution.payment.trust"]
        pay_domain = [("state", "=", "rejected")]
        if case:
            pay_domain = [
                "|",
                ("inquiry_id", "=", inquiry.id),
                ("case_id", "=", case.id),
                ("state", "=", "rejected"),
            ]
        else:
            pay_domain = [("inquiry_id", "=", inquiry.id), ("state", "=", "rejected")]
        rejected_pay = Trust.search(pay_domain, order="id desc", limit=1)

        # Priority ladder (blocker / assessment first)
        if (
            "mapping_review_required" in blocker_set
            or (assessment and assessment.mapping_review_id and assessment.mapping_review_id.state == "pending")
            or (inquiry.review_required and not inquiry.vetution_size_id_resolved)
            or state == "review"
            and assessment
            and assessment.recommended_next_action == "open_mapping_review"
        ):
            return ACTION_MAPPING_REQUIRED

        if state in ("unavailable",) or "out_of_stock" in blocker_set or "offer_expired" in blocker_set:
            return ACTION_OOS

        if state in ("stale", "sync_failed") or "stale_data" in blocker_set or "stale_data_shadow" in blocker_set:
            return ACTION_SUPPLIER_DATA_STALE

        if (
            (assessment and assessment.landed_cost_incomplete)
            or product_code == "INSUFFICIENT_PRODUCT_COST_DATA"
            or delivery_code in ("DELIVERY_COST_INCOMPLETE", "INSUFFICIENT_DELIVERY_COST_DATA")
            or decision == "INSUFFICIENT_COST_DATA"
            or "landed_cost_incomplete" in blocker_set
        ):
            return ACTION_INCOMPLETE_COST

        if delivery_code == "DELIVERY_PRICE_REVIEW_REQUIRED" or (
            assessment and assessment.delivery_review_required
        ):
            return ACTION_DELIVERY_PRICE_REVIEW

        if any(
            b in blocker_set
            for b in ("negative_margin", "below_min_gross_margin", "below_min_profit")
        ):
            return ACTION_NEGATIVE_MARGIN

        if (
            (assessment and assessment.price_review_required)
            or "excessive_price_increase" in blocker_set
            or "excessive_price_decrease" in blocker_set
        ):
            return ACTION_PRICE_REVIEW

        if rejected_pay:
            return ACTION_PAYMENT_REJECTED

        if open_quote and open_quote.state == "expired":
            return ACTION_QUOTATION_EXPIRED
        if open_quote and open_quote.state == "sent":
            return ACTION_WAITING_ACCEPTANCE

        if case and case.state == "exception":
            return ACTION_SUPPLIER_PRICE_CHANGED

        if accepted and (
            not case
            or case.payment_status not in ("paid", "manual_paid")
        ):
            if not case or case.state not in ("completed", "cancelled"):
                return ACTION_PAYMENT_PENDING

        if accepted and case and case.payment_status in ("paid", "manual_paid"):
            if not case.purchase_order_ids:
                return ACTION_READY_FOR_RFQ
            if case.state in ("awaiting_receipt", "purchase_confirmed"):
                return ACTION_WAITING_GIZA_RECEIPT
            if case.delivery_method == "store_pickup" and case.state in (
                "store_pickup_ready",
                "ready_for_delivery",
            ):
                return ACTION_READY_FOR_PICKUP
            if case.delivery_method == "shipblu_delivery" and case.state in (
                "ready_for_delivery",
                "shipping_created",
            ):
                ICP = self.env["ir.config_parameter"].sudo()
                verified = (
                    ICP.get_param(
                        "petspot_fulfillment_vetution.shipblu_package_size_verified",
                        "False",
                    )
                    == "True"
                )
                if not verified:
                    return ACTION_PACKAGE_SIZE_REQUIRED
                return ACTION_READY_FOR_SHIPMENT

        # Eligible shadow OK → quotation ready (operator reviews; Production stays gated)
        if (
            assessment
            and assessment.state == "ok"
            and assessment.eligible_future_automation
            and not open_quote
            and not accepted
        ):
            return ACTION_QUOTATION_READY

        if assessment and assessment.state == "blocked" and assessment.recommended_next_action:
            # Fallback for blocked assessments without more specific match
            if assessment.recommended_next_action == "complete_landed_cost_inputs":
                return ACTION_INCOMPLETE_COST
            if assessment.recommended_next_action == "price_review_required":
                return ACTION_PRICE_REVIEW
            if assessment.recommended_next_action in ("manual_review", "policy_review"):
                return ACTION_PRICE_REVIEW

        return False

    @api.model
    def resolve_owner(self, inquiry, owner_category):
        """Fallback: configured → inquiry user → manager → config blocker."""
        company = inquiry.company_id or self.env.company
        field_name = OWNER_FIELD.get(owner_category)
        user = False
        if field_name and field_name in company._fields:
            user = company[field_name]
        if user and user.active:
            return user, False
        # inquiry has no dedicated responsible — use create_uid as soft owner
        if inquiry.create_uid and inquiry.create_uid.active and not inquiry.create_uid.share:
            return inquiry.create_uid, False
        mgr_field = OWNER_FIELD["manager"]
        if mgr_field in company._fields and company[mgr_field] and company[mgr_field].active:
            return company[mgr_field], False
        # No silent Administrator — signal config blocker
        return False, ACTION_CONFIG_OWNER_MISSING

    @api.model
    def sync_inquiry(self, inquiry):
        """Idempotent: ensure exactly one open managed activity for current action."""
        inquiry.ensure_one()
        if self.env.context.get("petspot_ops_skip_sync"):
            return False

        action_code = self.determine_action_code(inquiry)
        Activity = self.env["mail.activity"].sudo()
        open_managed = Activity.search(
            [
                ("res_model", "=", "petspot.availability.inquiry"),
                ("res_id", "=", inquiry.id),
                ("petspot_managed", "=", True),
            ]
        )

        if not action_code:
            self._resolve_managed(open_managed, note=_("No further operator action required."))
            self._update_inquiry_ops_panel(inquiry, False, False, False, False)
            return False

        conf_blocker = False
        definition = ACTION_DEFS.get(action_code)
        if not definition:
            return False

        user, conf_blocker = self.resolve_owner(inquiry, definition["owner"])
        if conf_blocker:
            action_code = conf_blocker
            definition = ACTION_DEFS[action_code]
            user, _cfg = self.resolve_owner(inquiry, "manager")
            if not user:
                # Last resort: current env user if internal; still visible config issue
                user = self.env.user if not self.env.user.share else self.env.ref("base.user_admin")

        # Resolve obsolete managed activities with different codes
        obsolete = open_managed.filtered(lambda a: a.petspot_action_code != action_code)
        self._resolve_managed(
            obsolete,
            note=_("Blocker changed — previous managed activity auto-resolved (%s → %s).")
            % (",".join(obsolete.mapped("petspot_action_code")), action_code),
        )

        existing = Activity.search(
            [
                ("res_model", "=", "petspot.availability.inquiry"),
                ("res_id", "=", inquiry.id),
                ("petspot_managed", "=", True),
                ("petspot_action_code", "=", action_code),
            ],
            limit=1,
        )
        deadline = fields.Date.context_today(self) + timedelta(
            days=int(definition.get("deadline_days") or 0)
        )
        xmlid = definition["activity_type_xml"]
        if not self.env.ref(xmlid, raise_if_not_found=False):
            xmlid = "mail.mail_activity_data_todo"

        if existing:
            vals = {}
            if user and existing.user_id != user:
                vals["user_id"] = user.id
            if existing.summary != definition["summary"]:
                vals["summary"] = definition["summary"]
            if vals:
                existing.with_context(petspot_ops_skip_sync=True).write(vals)
            activity = existing
        else:
            activity = inquiry.with_context(petspot_ops_skip_sync=True).activity_schedule(
                xmlid,
                summary=definition["summary"],
                note=definition["explanation"],
                user_id=user.id if user else self.env.uid,
                date_deadline=deadline,
            )
            if activity:
                activity.with_context(petspot_ops_skip_sync=True).write(
                    {
                        "petspot_managed": True,
                        "petspot_action_code": action_code,
                    }
                )

        self._update_inquiry_ops_panel(inquiry, action_code, definition, user, activity)
        return activity

    def _resolve_managed(self, activities, note=""):
        for act in activities:
            try:
                act.with_context(petspot_ops_skip_sync=True).action_feedback(
                    feedback=note or _("Auto-resolved by PetSpot Ops orchestrator.")
                )
            except Exception:  # noqa: BLE001
                # Fallback: unlink only managed leftovers if feedback fails
                _logger.exception("Failed to feedback managed activity %s", act.id)
                act.with_context(petspot_ops_skip_sync=True).unlink()

    def _update_inquiry_ops_panel(self, inquiry, action_code, definition, user, activity):
        assessment = inquiry.vetution_assessment_id
        ICP = self.env["ir.config_parameter"].sudo()
        dbname = self.env.cr.dbname
        is_test = dbname.endswith("_test") or "test" in dbname
        shadow = (
            ICP.get_param("petspot_fulfillment_vetution.auto_quote_enabled", "False") != "True"
            and ICP.get_param("petspot_fulfillment.automation_enabled", "False") != "True"
        )
        vals = {
            "ops_action_code": action_code or False,
            "ops_blocker_code": (definition or {}).get("blocker") or False,
            "ops_blocker_label": (definition or {}).get("explanation") or False,
            "ops_next_action_label": (definition or {}).get("summary") or False,
            "ops_owner_id": user.id if user else False,
            "ops_activity_id": activity.id if activity else False,
            "ops_due_date": activity.date_deadline if activity else False,
            "ops_category": (definition or {}).get("category") or False,
            "ops_stage": self._ops_stage(inquiry, assessment, action_code),
            "ops_environment": "test_synthetic" if is_test else (
                "production_shadow" if shadow else "production"
            ),
            "ops_priority": "1" if action_code in (
                ACTION_MAPPING_REQUIRED,
                ACTION_DELIVERY_PRICE_REVIEW,
                ACTION_NEGATIVE_MARGIN,
                ACTION_PAYMENT_REJECTED,
            ) else "0",
        }
        inquiry.with_context(petspot_ops_skip_sync=True).write(vals)

    def _ops_stage(self, inquiry, assessment, action_code):
        if not assessment:
            return "intake"
        if action_code == ACTION_MAPPING_REQUIRED:
            return "mapping"
        if action_code in (ACTION_SUPPLIER_DATA_STALE, ACTION_OOS, ACTION_INCOMPLETE_COST):
            return "sourcing"
        if action_code in (
            ACTION_PRICE_REVIEW,
            ACTION_NEGATIVE_MARGIN,
            ACTION_DELIVERY_PRICE_REVIEW,
            ACTION_QUOTATION_READY,
        ):
            return "commercial_review"
        if action_code in (ACTION_WAITING_ACCEPTANCE, ACTION_QUOTATION_EXPIRED):
            return "quotation"
        if action_code in (ACTION_PAYMENT_PENDING, ACTION_PAYMENT_REJECTED):
            return "payment"
        if action_code in (ACTION_READY_FOR_RFQ, ACTION_SUPPLIER_PRICE_CHANGED):
            return "supplier_order"
        if action_code == ACTION_WAITING_GIZA_RECEIPT:
            return "warehouse"
        if action_code in (
            ACTION_PACKAGE_SIZE_REQUIRED,
            ACTION_READY_FOR_SHIPMENT,
            ACTION_SHIPMENT_FAILED,
            ACTION_READY_FOR_PICKUP,
        ):
            return "fulfillment"
        if assessment.state == "ok" and not action_code:
            return "clear"
        return "blocked"
