# -*- coding: utf-8 -*-
"""Price publish queue — approval-gated, mock Shopify transport by default.

Nothing here ever writes to Shopify unless ICP
petspot_fulfillment_vetution.shopify_publish_transport=live, which is not
implemented in this module (flipping it raises). publish_mock() only flips
the queue row + (optionally) the Odoo sales price for audit purposes.
"""

from __future__ import annotations

from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

TRANSPORT_ICP = "petspot_fulfillment_vetution.shopify_publish_transport"
REENQUEUE_WINDOW_HOURS = 1.0


class PetspotVetutionPricePublishQueue(models.Model):
    _name = "petspot.vetution.price.publish.queue"
    _description = "Vetution Price Publish Queue"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char(required=True, default="PUB")
    product_id = fields.Many2one("product.product", required=True, index=True)
    shopify_variant_id = fields.Char(index=True)
    suggested_price = fields.Float(required=True)
    current_price = fields.Float()
    state = fields.Selection(
        [
            ("pending", "Pending approval"),
            ("approved", "Approved"),
            ("published", "Published"),
            ("failed", "Failed"),
            ("rolled_back", "Rolled back"),
            ("blocked", "Blocked"),
        ],
        default="pending",
        required=True,
        tracking=True,
        index=True,
    )
    audit = fields.Text(help="Append-only audit trail of state changes / reasons.")
    idempotency_key = fields.Char(required=True, index=True)
    approved_by = fields.Many2one("res.users")
    published_at = fields.Datetime()
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )

    _sql_constraints = [
        (
            "petspot_price_pub_idem_uniq",
            "unique(idempotency_key)",
            "A price-publish request with this idempotency key already exists.",
        ),
    ]

    def _append_audit(self, line):
        for rec in self:
            rec.audit = ((rec.audit or "") + f"\n[{fields.Datetime.now()}] {line}").strip()

    @api.model
    def enqueue(self, product, suggested_price, shopify_variant_id=False):
        product.ensure_one()
        current_price = float(product.lst_price or product.list_price or 0.0)
        suggested_price = float(suggested_price or 0.0)

        if getattr(product.product_tmpl_id, "vetution_sale_price_locked", False):
            rec = self._create_row(product, suggested_price, current_price, shopify_variant_id)
            rec.write({"state": "blocked"})
            rec._append_audit("Blocked: product.vetution_sale_price_locked is True.")
            return rec

        if abs(suggested_price - current_price) < 1e-6:
            rec = self._create_row(product, suggested_price, current_price, shopify_variant_id)
            rec.write({"state": "blocked"})
            rec._append_audit("Blocked: suggested price equals current price (no-op).")
            return rec

        # Loop prevention: don't re-enqueue same price within window
        cutoff = fields.Datetime.now() - timedelta(hours=REENQUEUE_WINDOW_HOURS)
        recent = self.search(
            [
                ("product_id", "=", product.id),
                ("suggested_price", "=", suggested_price),
                ("create_date", ">=", cutoff),
                ("state", "not in", ("failed", "rolled_back")),
            ],
            limit=1,
        )
        if recent:
            return recent

        return self._create_row(product, suggested_price, current_price, shopify_variant_id)

    def _create_row(self, product, suggested_price, current_price, shopify_variant_id):
        idem = f"pub:{product.id}:{suggested_price}:{fields.Datetime.now().timestamp()}"
        return self.create(
            {
                "name": f"PUB/{product.default_code or product.id}",
                "product_id": product.id,
                "shopify_variant_id": shopify_variant_id or False,
                "suggested_price": suggested_price,
                "current_price": current_price,
                "idempotency_key": idem,
                "audit": f"Enqueued: {current_price} -> {suggested_price}",
            }
        )

    def approve(self, user=None):
        user = user or self.env.user
        for rec in self:
            if rec.state != "pending":
                raise UserError(f"Cannot approve a request in state={rec.state}.")
            rec.write({"state": "approved", "approved_by": user.id})
            rec._append_audit(f"Approved by {user.display_name}.")
        return True

    def publish_mock(self):
        """Mock-only publish. Live transport is intentionally unimplemented."""
        ICP = self.env["ir.config_parameter"].sudo()
        mode = (ICP.get_param(TRANSPORT_ICP, "mock") or "mock").strip().lower()
        if mode == "live":
            raise UserError(
                "Live Shopify publish transport is not implemented in this "
                "module. Keep ICP petspot_fulfillment_vetution.shopify_publish_transport=mock."
            )
        for rec in self:
            if rec.state != "approved":
                raise UserError(f"Cannot publish a request in state={rec.state}.")
            if getattr(rec.product_id.product_tmpl_id, "vetution_sale_price_locked", False):
                rec.write({"state": "blocked"})
                rec._append_audit("Blocked at publish time: price now locked.")
                continue
            rec.write({"state": "published", "published_at": fields.Datetime.now()})
            rec._append_audit(
                f"Published (mock): {rec.current_price} -> {rec.suggested_price} "
                "(no live Shopify call was made)."
            )
        return True

    def rollback_mock(self, reason=False):
        for rec in self:
            if rec.state not in ("published", "failed"):
                raise UserError(f"Cannot roll back a request in state={rec.state}.")
            rec.write({"state": "rolled_back"})
            rec._append_audit(f"Rolled back (mock): {reason or 'no reason given'}.")
        return True

    def mark_failed(self, reason):
        for rec in self:
            rec.write({"state": "failed"})
            rec._append_audit(f"Failed: {reason}")
        return True
