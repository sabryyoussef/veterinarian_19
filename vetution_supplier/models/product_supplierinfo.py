# -*- coding: utf-8 -*-
"""Mirror primary Vetution offers onto product.supplierinfo."""

from odoo import fields, models

VETUTION_ORIGIN = "vetution_supplier"


class ProductSupplierinfo(models.Model):
    _inherit = "product.supplierinfo"

    vetution_origin = fields.Char(
        string="Vetution Origin",
        copy=False,
        index=True,
        help="Marker for rows owned by vetution_supplier. Never touch rows without this marker.",
    )
    vetution_offer_id = fields.Many2one(
        "vetution.supplier.offer",
        ondelete="set null",
        copy=False,
        index=True,
    )

    def _vetution_mirror_offer(self, offer):
        """Create/update/deactivate supplierinfo for a primary Vetution offer.

        Returns metrics dict: supplierinfo_created/updated/deactivated.
        """
        metrics = {
            "supplierinfo_created": 0,
            "supplierinfo_updated": 0,
            "supplierinfo_deactivated": 0,
        }
        if offer.offer_type != "vetution":
            return metrics

        connection = offer.connection_id
        partner = connection.supplier_partner_id
        if not partner:
            partner = self.env.ref(
                "vetution_supplier.res_partner_vetution", raise_if_not_found=False
            )
            if partner:
                connection.sudo().write({"supplier_partner_id": partner.id})

        existing = self.search(
            [
                ("vetution_origin", "=", VETUTION_ORIGIN),
                "|",
                ("vetution_offer_id", "=", offer.id),
                "&",
                ("product_id", "=", offer.product_id.id),
                ("partner_id", "=", partner.id if partner else 0),
            ]
        )

        valid = (
            bool(offer.product_id)
            and float(offer.effective_cost or 0) > 0
            and offer.active
            and offer.availability_state
            not in ("expired", "price_hidden", "authentication_error")
        )
        # Quarantined / expiry-blocked offers keep cost metadata off supplierinfo
        # until cleared (Phase 2 invariant B for blocked cases; OOS still allowed).
        reason = offer.review_reason or ""
        if "duplicate_size_id_in_payload" in reason:
            valid = False
        min_days = offer.connection_id.minimum_expiry_days or 90
        if (
            offer.expiry_is_exact
            and offer.days_to_expiry is not False
            and offer.days_to_expiry is not None
            and offer.days_to_expiry < min_days
        ):
            valid = False

        if not valid:
            # Deactivate only our rows
            to_deactivate = existing.filtered(lambda r: r.vetution_origin == VETUTION_ORIGIN)
            if to_deactivate:
                # product.supplierinfo has no active field in all versions — delete safely
                # Prefer writing a zero price + high min_qty sentinel, or unlink only our rows.
                to_deactivate.unlink()
                metrics["supplierinfo_deactivated"] = len(to_deactivate)
            return metrics

        if not partner:
            return metrics

        currency = self.env.ref("base.EGP", raise_if_not_found=False) or self.env.company.currency_id
        uom = offer.product_id.uom_id or offer.product_tmpl_id.uom_id
        vals = {
            "partner_id": partner.id,
            "product_id": offer.product_id.id,
            "product_tmpl_id": offer.product_tmpl_id.id,
            "product_uom_id": uom.id,
            "product_code": str(offer.vetution_size_id or ""),
            "product_name": f"{offer.drug_name or ''} / {offer.size_name or ''}".strip(" /"),
            "price": offer.effective_cost,
            "currency_id": currency.id,
            "min_qty": 1.0,
            "delay": connection.supplier_lead_time_days or 3,
            "vetution_origin": VETUTION_ORIGIN,
            "vetution_offer_id": offer.id,
        }

        ours = existing.filtered(lambda r: r.vetution_origin == VETUTION_ORIGIN)
        if ours:
            row = ours[0]
            same = (
                row.partner_id.id == vals["partner_id"]
                and (row.product_id.id if row.product_id else False) == vals["product_id"]
                and abs(float(row.price or 0) - float(vals["price"])) < 0.009
                and (row.product_code or "") == (vals["product_code"] or "")
                and row.vetution_offer_id.id == vals["vetution_offer_id"]
                and int(row.delay or 0) == int(vals["delay"] or 0)
            )
            if not same:
                row.write(vals)
                metrics["supplierinfo_updated"] = 1
            extras = ours[1:]
            if extras:
                extras.unlink()
                metrics["supplierinfo_deactivated"] = len(extras)
        else:
            self.create(vals)
            metrics["supplierinfo_created"] = 1
        return metrics
