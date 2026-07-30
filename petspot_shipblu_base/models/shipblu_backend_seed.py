# -*- coding: utf-8 -*-
"""Idempotent reference config seeds (pricing, volume, package sizes, SLA)."""

from odoo import models


class ShipBluBackendSeed(models.Model):
    _inherit = "shipblu.backend"

    def _ensure_reference_config(self):
        """Create editable reference records once per backend (no duplicates)."""
        for backend in self:
            backend._seed_pricing_rules()
            backend._seed_volume_discounts()
            backend._seed_package_sizes()
            backend._seed_sla_rules()

    def _seed_pricing_rules(self):
        self.ensure_one()
        Rule = self.env["shipblu.pricing.rule"].sudo()
        rows = [
            ("Giza", "Giza", 95.0),
            ("Giza", "Alexandria", 104.0),
            ("Giza", "Delta", 106.0),
            ("Giza", "Canal Cities", 106.0),
            ("Giza", "Assiut", 181.0),
            ("Giza", "North Coast", 196.0),
        ]
        for origin, dest, price in rows:
            exists = Rule.search(
                [
                    ("backend_id", "=", self.id),
                    ("origin_governorate", "=", origin),
                    ("destination_governorate", "=", dest),
                    ("source", "=", "contract"),
                ],
                limit=1,
            )
            if exists:
                continue
            Rule.create(
                {
                    "name": f"{origin} → {dest}",
                    "backend_id": self.id,
                    "origin_governorate": origin,
                    "destination_governorate": dest,
                    "base_price": price,
                    "tax_included": False,
                    "source": "contract",
                    "note": "Seeded reference (excl. tax & COD). API quotes override when available.",
                }
            )

    def _seed_volume_discounts(self):
        self.ensure_one()
        Tier = self.env["shipblu.volume.discount"].sudo()
        rows = [
            (30, 50, 4.0),
            (60, 100, 5.0),
            (101, 150, 7.0),
            (160, 200, 25.0),
            # 201–500 (not 200–500): count 200 belongs only to the 25% tier — no overlap.
            (201, 500, 30.0),
        ]
        for lo, hi, pct in rows:
            exists = Tier.search(
                [
                    ("backend_id", "=", self.id),
                    ("min_shipments", "=", lo),
                    ("max_shipments", "=", hi),
                ],
                limit=1,
            )
            if exists:
                continue
            Tier.create(
                {
                    "backend_id": self.id,
                    "min_shipments": lo,
                    "max_shipments": hi,
                    "discount_percent": pct,
                }
            )

    def _seed_package_sizes(self):
        self.ensure_one()
        Size = self.env["shipblu.package.size"].sudo()
        # IDs 1–4 accepted by official pricing API; labels aligned to Shopify app UI.
        # Operator must verify before enabling live create.
        rows = [
            ("Small", "small", 1, 0.0),
            ("Medium", "medium", 2, 0.0),
            ("Large", "large", 3, float(self.large_package_surcharge_percent or 10.0)),
            ("Extra Large", "xlarge", 4, float(self.xlarge_package_surcharge_percent or 15.0)),
        ]
        for name, code, sid, pct in rows:
            exists = Size.search(
                [("backend_id", "=", self.id), ("shipblu_size_id", "=", sid)],
                limit=1,
            )
            if exists:
                continue
            Size.create(
                {
                    "name": name,
                    "code": code,
                    "backend_id": self.id,
                    "shipblu_size_id": sid,
                    "surcharge_percent": pct,
                    "note": "Verify ID against Shopify ShipBlu UI before live create.",
                }
            )

    def _seed_sla_rules(self):
        self.ensure_one()
        Sla = self.env["shipblu.sla.rule"].sudo()
        rows = [
            ("Cairo", 1, 1),
            ("Giza", 1, 1),
            ("Alexandria", 1, 1),
            ("Delta", 1, 1),
            ("Canal Cities", 2, 3),
            ("Assiut", 2, 4),
        ]
        for region, dmin, dmax in rows:
            exists = Sla.search(
                [("backend_id", "=", self.id), ("region", "=", region)],
                limit=1,
            )
            if exists:
                continue
            Sla.create(
                {
                    "name": f"{region} SLA",
                    "backend_id": self.id,
                    "region": region,
                    "days_min": dmin,
                    "days_max": dmax,
                }
            )

    def action_seed_reference_config(self):
        self._ensure_reference_config()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "ShipBlu",
                "message": "Reference pricing / discounts / package sizes / SLA seeded (idempotent).",
                "type": "success",
                "sticky": False,
            },
        }
