# -*- coding: utf-8 -*-
"""Auto/manual quotation ledger (Phase 15B synthetic workflow orchestration).

Every automatic quotation must pass ALL of: policy lock (synthetic OR
allow_auto_quotation+ICP auto_quote_enabled), freshness <=2h, automation
allowlist, delivery gate, and exact/confirmed mapping. Exactly one OPEN
(draft/sent) ledger row per inquiry at a time — creating a new one supersedes
the previous open row.
"""

from __future__ import annotations

from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PetspotVetutionQuotationLedger(models.Model):
    _name = "petspot.vetution.quotation.ledger"
    _description = "Vetution Quotation Ledger"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char(required=True, default="QUOTE")
    inquiry_id = fields.Many2one(
        "petspot.availability.inquiry", required=True, ondelete="cascade", index=True
    )
    case_id = fields.Many2one("petspot.fulfillment.case", index=True)
    sale_order_id = fields.Many2one("sale.order", index=True)
    assessment_id = fields.Many2one(
        "petspot.vetution.shadow.assessment", ondelete="restrict", index=True
    )
    policy_id = fields.Many2one("petspot.vetution.landed.cost.policy", required=True)
    version = fields.Integer(required=True, default=1)
    product_price = fields.Float(required=True)
    delivery_charge = fields.Float(default=0.0)
    order_total = fields.Float(compute="_compute_order_total", store=True)
    source = fields.Selection(
        [("auto", "Automatic"), ("manual", "Manual")], default="auto", required=True
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("sent", "Sent"),
            ("accepted", "Accepted"),
            ("expired", "Expired"),
            ("superseded", "Superseded"),
        ],
        default="draft",
        required=True,
        tracking=True,
        index=True,
    )
    expires_at = fields.Datetime()
    idempotency_key = fields.Char(required=True, index=True)
    accepted_price_lock = fields.Boolean(
        default=False,
        help="True once the customer accepted — price must not silently change afterwards.",
    )
    note = fields.Text()
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )

    _sql_constraints = [
        (
            "petspot_quote_ledger_idem_uniq",
            "unique(idempotency_key)",
            "A quotation with this idempotency key already exists.",
        ),
    ]

    @api.depends("product_price", "delivery_charge")
    def _compute_order_total(self):
        for rec in self:
            rec.order_total = round(
                float(rec.product_price or 0.0) + float(rec.delivery_charge or 0.0), 2
            )

    @api.model
    def _next_version(self, inquiry):
        last = self.search(
            [("inquiry_id", "=", inquiry.id)], order="version desc", limit=1
        )
        return (last.version or 0) + 1

    def action_mark_expired(self):
        for rec in self.filtered(lambda r: r.state in ("draft", "sent")):
            rec.write({"state": "expired"})
        return True

    @api.model
    def expire_stale(self):
        """Cron-safe: expire any open quotation past its expires_at."""
        now = fields.Datetime.now()
        stale = self.search(
            [("state", "in", ("draft", "sent")), ("expires_at", "<", now)]
        )
        stale.action_mark_expired()
        return len(stale)

    def action_accept(self):
        self.ensure_one()
        if self.state not in ("draft", "sent"):
            raise UserError(_("Only an open (draft/sent) quotation can be accepted."))
        if self.expires_at and self.expires_at < fields.Datetime.now():
            self.write({"state": "expired"})
            self.flush_recordset()
            raise UserError(_("Quotation has expired — request a fresh assessment."))
        self.write({"state": "accepted", "accepted_price_lock": True})
        self.message_post(body=_("Quotation accepted — price locked."))
        return True

    # ------------------------------------------------------------------ auto
    @api.model
    def create_auto_quotation(self, inquiry, assessment, policy):
        """Idempotent auto-quotation creation with full gate enforcement."""
        inquiry.ensure_one()
        assessment.ensure_one()
        policy.ensure_one()

        ICP = self.env["ir.config_parameter"].sudo()
        auto_quote_enabled = (
            ICP.get_param("petspot_fulfillment_vetution.auto_quote_enabled", "False")
            == "True"
        )
        if policy.is_synthetic_test:
            if not policy._synthetic_test_allowed_here():
                raise UserError(
                    _("Synthetic TEST policy is not allowed on this database.")
                )
        elif not (policy.allow_auto_quotation and auto_quote_enabled):
            raise UserError(
                _(
                    "Auto-quotation is disabled: policy.allow_auto_quotation and "
                    "ICP auto_quote_enabled must both be true (non-synthetic "
                    "policies), or the policy must be the synthetic TEST fixture."
                )
            )

        # Serialize per-inquiry to avoid racing duplicate quotations.
        self.env.cr.execute(
            "SELECT id FROM petspot_availability_inquiry WHERE id=%s FOR UPDATE",
            (inquiry.id,),
        )

        if (assessment.data_age_hours or 0.0) > 2.0:
            raise UserError(_("Commercial data is stale (>2h) — auto-quote blocked."))
        if not assessment.on_automation_allowlist:
            raise UserError(
                _("Product is not on the automation allowlist — auto-quote blocked.")
            )
        if not assessment.delivery_gate_passed:
            raise UserError(
                _(
                    "Delivery gate failed (decision=%s) — auto-quote blocked; "
                    "manual price review required."
                )
                % (assessment.delivery_decision_code or "?")
            )
        if assessment.resolution_confidence not in ("exact", "configured", "barcode"):
            raise UserError(
                _("Mapping is not exact/confirmed — auto-quote blocked.")
            )
        if assessment.landed_cost_incomplete:
            raise UserError(_("Landed cost incomplete — auto-quote blocked."))
        if not assessment.suggested_price:
            raise UserError(_("No suggested price on assessment — auto-quote blocked."))

        accepted = self.search(
            [("inquiry_id", "=", inquiry.id), ("state", "=", "accepted")],
            order="id desc",
            limit=1,
        )
        if accepted and accepted.accepted_price_lock:
            if abs(accepted.product_price - assessment.suggested_price) < 1e-6:
                return accepted  # idempotent — price unchanged since acceptance
            raise UserError(
                _(
                    "Post-accept price change detected (accepted %.2f -> new %.2f) — "
                    "an accepted quotation is locked; auto-quote blocked, manual "
                    "review required."
                )
                % (accepted.product_price, assessment.suggested_price)
            )

        open_quote = self.search(
            [("inquiry_id", "=", inquiry.id), ("state", "in", ("draft", "sent"))],
            limit=1,
        )
        if open_quote:
            if (
                open_quote.assessment_id == assessment
                and abs(open_quote.product_price - assessment.suggested_price) < 1e-6
            ):
                return open_quote  # idempotent — nothing changed
            if open_quote.accepted_price_lock:
                raise UserError(
                    _("An accepted quotation exists — cannot supersede a locked price.")
                )
            open_quote.write({"state": "superseded"})

        version = self._next_version(inquiry)
        idem = f"autoquote:{inquiry.id}:{assessment.id}:{version}"
        existing = self.search([("idempotency_key", "=", idem)], limit=1)
        if existing:
            return existing

        so = self._create_or_reuse_sale_order(inquiry, assessment, policy)

        expires_at = fields.Datetime.now() + timedelta(
            hours=policy.quotation_validity_hours or 2.0
        )
        ledger = self.create(
            {
                "name": f"QUOTE/{inquiry.name}/v{version}",
                "inquiry_id": inquiry.id,
                "case_id": inquiry.case_id.id if inquiry.case_id else False,
                "sale_order_id": so.id if so else False,
                "assessment_id": assessment.id,
                "policy_id": policy.id,
                "version": version,
                "product_price": assessment.suggested_price,
                "delivery_charge": assessment.customer_delivery_charge,
                "source": "auto",
                "state": "sent",
                "expires_at": expires_at,
                "idempotency_key": idem,
                "company_id": inquiry.company_id.id,
            }
        )
        inquiry.message_post(
            body=_("Auto quotation v%s created — expires %s (synthetic/auto path).")
            % (version, expires_at)
        )
        return ledger

    def _create_or_reuse_sale_order(self, inquiry, assessment, policy):
        if inquiry.sale_order_id:
            return inquiry.sale_order_id
        if not inquiry.product_id:
            raise UserError(_("Inquiry has no product — cannot create quotation."))
        partner = inquiry.partner_id
        if not partner:
            partner = self.env["res.partner"].create(
                {
                    "name": inquiry.customer_name or inquiry.phone,
                    "phone": inquiry.phone,
                    "type": "contact",
                }
            )
            inquiry.partner_id = partner.id

        order_lines = [
            (
                0,
                0,
                {
                    "product_id": inquiry.product_id.id,
                    "product_uom_qty": inquiry.requested_qty or 1.0,
                    "price_unit": assessment.suggested_price,
                },
            )
        ]
        # Delivery: use a dedicated shipping product line if one exists on this
        # DB; otherwise keep delivery_charge on the ledger only (order note),
        # never fold it into the product price.
        delivery_product = self.env["product.product"].sudo().search(
            [("default_code", "=", "SHIPBLU-DELIVERY")], limit=1
        )
        if delivery_product and assessment.customer_delivery_charge:
            order_lines.append(
                (
                    0,
                    0,
                    {
                        "product_id": delivery_product.id,
                        "product_uom_qty": 1.0,
                        "price_unit": assessment.customer_delivery_charge,
                    },
                )
            )
        so = self.env["sale.order"].create(
            {
                "partner_id": partner.id,
                "origin": f"petspot-vetution-autoquote:{inquiry.id}",
                "client_order_ref": inquiry.name,
                "order_line": order_lines,
            }
        )
        inquiry.write({"sale_order_id": so.id, "state": "quoted"})
        case = self.env["petspot.fulfillment.case"].get_or_create_for_sale_order(
            so, classification_source="inquiry"
        )
        case.write(
            {
                "inquiry_id": inquiry.id,
                "delivery_method": (
                    inquiry.requested_fulfillment
                    if inquiry.requested_fulfillment != "undecided"
                    else "undecided"
                ),
            }
        )
        inquiry.case_id = case.id
        return so
