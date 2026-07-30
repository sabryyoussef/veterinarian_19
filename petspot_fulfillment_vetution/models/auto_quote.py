# -*- coding: utf-8 -*-
"""TEST auto-quotation runs — Production allow_auto_quotation stays False."""

from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class PetspotVetutionAutoQuote(models.Model):
    _name = "petspot.vetution.auto.quote"
    _description = "Vetution Auto-Quote Run"
    _order = "id desc"
    _inherit = ["mail.thread"]

    name = fields.Char(required=True, default="AQ")
    inquiry_id = fields.Many2one(
        "petspot.availability.inquiry", required=True, index=True, ondelete="cascade"
    )
    assessment_id = fields.Many2one("petspot.vetution.shadow.assessment", ondelete="set null")
    policy_id = fields.Many2one("petspot.vetution.landed.cost.policy")
    sale_order_id = fields.Many2one("sale.order", copy=False)
    version = fields.Integer(default=1, required=True)
    idempotency_key = fields.Char(required=True, index=True)
    state = fields.Selection(
        [
            ("eligible", "Eligible"),
            ("blocked", "Blocked"),
            ("quoted", "Quoted"),
            ("expired", "Expired"),
            ("accepted", "Accepted"),
            ("superseded", "Superseded"),
        ],
        default="eligible",
        required=True,
        tracking=True,
        index=True,
    )
    block_reason = fields.Char()
    product_price = fields.Float()
    delivery_charge = fields.Float()
    order_total = fields.Float()
    valid_until = fields.Datetime()
    accepted_price_locked = fields.Boolean(
        default=False,
        help="When True, post-acceptance price changes require exception handling.",
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    _sql_constraints = [
        (
            "petspot_vetution_aq_idempotent",
            "unique(idempotency_key, company_id)",
            "Duplicate auto-quote idempotency key.",
        ),
    ]

    @api.model
    def _eligibility(self, inquiry, assessment, policy):
        reasons = []
        if not policy.allow_auto_quotation:
            reasons.append("allow_auto_quotation=False")
        if policy.is_synthetic_test_fixture is False and not policy.allow_auto_quotation:
            reasons.append("non_synthetic_policy_locked")
        if not assessment or assessment.state not in ("ok", "blocked"):
            # blocked assessments can still quote only if product ready and delivery review handled
            pass
        if not inquiry.product_id:
            reasons.append("missing_product")
        if not self.env["petspot.vetution.automation.allowlist"].is_product_allowed(
            inquiry.product_id
        ):
            reasons.append("not_on_allowlist")
        if assessment and not assessment.is_fresh:
            reasons.append("stale_supplier_data")
        age_limit = policy.stale_after_hours_auto_quote or 2.0
        if assessment and (assessment.data_age_hours or 0) > age_limit:
            reasons.append("commercial_data_older_than_auto_quote_window")
        if assessment and assessment.product_decision_code == "INSUFFICIENT_PRODUCT_COST_DATA":
            if not policy.is_synthetic_test_fixture:
                reasons.append("incomplete_product_cost")
        if assessment and assessment.delivery_decision_code == "DELIVERY_PRICE_REVIEW_REQUIRED":
            reasons.append("delivery_price_review_required")
        if assessment and assessment.delivery_review_required:
            reasons.append("delivery_price_review_required")
        # Existing open quote for same inquiry version?
        open_q = self.search(
            [
                ("inquiry_id", "=", inquiry.id),
                ("state", "in", ("eligible", "quoted", "accepted")),
            ],
            limit=1,
        )
        # checked by caller for supersede
        return reasons, open_q

    @api.model
    def run_for_inquiry(self, inquiry, assessment=None, force_policy=None):
        inquiry.ensure_one()
        policy = force_policy or self.env["petspot.vetution.landed.cost.policy"].get_active_policy()
        assessment = assessment or self.env["petspot.vetution.shadow.assessment"].search(
            [("inquiry_id", "=", inquiry.id)], order="id desc", limit=1
        )
        reasons, open_q = self._eligibility(inquiry, assessment, policy)
        key = f"AQ/{inquiry.id}/v{(open_q.version + 1) if open_q else 1}"
        existing = self.search([("idempotency_key", "=", key)], limit=1)
        if existing:
            return existing

        vals = {
            "name": key,
            "inquiry_id": inquiry.id,
            "assessment_id": assessment.id if assessment else False,
            "policy_id": policy.id,
            "idempotency_key": key,
            "version": (open_q.version + 1) if open_q else 1,
            "product_price": assessment.recommended_product_price if assessment else 0.0,
            "delivery_charge": assessment.customer_delivery_charge if assessment else 0.0,
            "order_total": assessment.order_total if assessment else 0.0,
            "valid_until": fields.Datetime.now()
            + timedelta(hours=float(policy.quotation_validity_hours or 2.0)),
        }
        if reasons:
            vals["state"] = "blocked"
            vals["block_reason"] = "|".join(reasons)
            return self.create(vals)

        # Create one quotation via inquiry helper if available
        if open_q and open_q.state in ("quoted", "accepted"):
            open_q.state = "superseded"

        quote = self.create(vals)
        if hasattr(inquiry, "action_create_quotation"):
            so = inquiry.action_create_quotation()
            # action may return action dict or order
            if isinstance(so, dict) and so.get("res_id"):
                quote.sale_order_id = so["res_id"]
            elif getattr(inquiry, "sale_order_id", False):
                quote.sale_order_id = inquiry.sale_order_id.id
        quote.state = "quoted"
        return quote

    def action_accept(self):
        for rec in self:
            if rec.state != "quoted":
                raise UserError("Only quoted runs can be accepted.")
            if rec.valid_until and fields.Datetime.now() > rec.valid_until:
                rec.state = "expired"
                raise UserError("Quotation expired.")
            rec.state = "accepted"
            rec.accepted_price_locked = True

    def action_expire_due(self):
        due = self.search(
            [
                ("state", "=", "quoted"),
                ("valid_until", "!=", False),
                ("valid_until", "<", fields.Datetime.now()),
            ]
        )
        due.write({"state": "expired"})
        return len(due)
