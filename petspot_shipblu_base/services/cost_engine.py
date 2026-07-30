# -*- coding: utf-8 -*-
"""Reusable ShipBlu estimated cost breakdown (no accounting posts)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class CostBreakdown:
    base_fee: float = 0.0
    size_surcharge: float = 0.0
    cod_fee: float = 0.0
    try_and_buy_fee: float = 0.0
    inspection_fee: float = 0.0
    return_fee: float = 0.0
    pickup_surcharge: float = 0.0
    discount: float = 0.0
    tax: float = 0.0
    total: float = 0.0
    currency: str = "EGP"
    status: str = "estimated"  # estimated | confirmed
    pricing_source: str = "manual"  # manual | contract | api | imported
    pricing_rule_id: int | None = None
    discount_tier_label: str = ""
    monthly_shipment_count: int = 0
    notes: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


class CostEngine:
    """Compute explainable shipping cost from backend configuration."""

    def __init__(self, backend):
        self.backend = backend
        self.env = backend.env

    def monthly_shipment_count(self, year=None, month=None):
        """Count created/imported shipments in company month (Cairo calendar month via UTC dates is approximate)."""
        from datetime import date

        from odoo import fields as odoo_fields

        today = odoo_fields.Date.context_today(self.backend)
        year = year or today.year
        month = month or today.month
        start = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1)
        else:
            end = date(year, month + 1, 1)
        if "shipblu.shipment" not in self.env:
            return 0
        Shipment = self.env["shipblu.shipment"].sudo()
        return Shipment.search_count(
            [
                ("company_id", "=", self.backend.company_id.id),
                ("create_date", ">=", odoo_fields.Datetime.to_datetime(f"{start} 00:00:00")),
                ("create_date", "<", odoo_fields.Datetime.to_datetime(f"{end} 00:00:00")),
                ("state", "not in", ("draft", "cancelled", "error")),
            ]
        )

    def active_discount_tier(self, shipment_count=None):
        count = shipment_count if shipment_count is not None else self.monthly_shipment_count()
        Tier = self.env["shipblu.volume.discount"]
        tiers = Tier.search(
            [
                ("backend_id", "=", self.backend.id),
                ("active", "=", True),
                ("min_shipments", "<=", count),
                ("max_shipments", ">=", count),
            ],
            order="min_shipments desc, discount_percent desc, id",
        )
        if len(tiers) > 1:
            # Ambiguous overlapping configuration — fail closed for estimation callers
            # that check .exists() carefully; return empty and note via count.
            return Tier.browse(), count
        return tiers[:1], count

    def resolve_package_size(self, package_size_id=None, size_code=None):
        Size = self.env["shipblu.package.size"]
        domain = [("backend_id", "=", self.backend.id), ("active", "=", True)]
        if package_size_id:
            rec = Size.search(domain + [("shipblu_size_id", "=", int(package_size_id))], limit=1)
            if rec:
                return rec
        if size_code:
            rec = Size.search(domain + [("code", "=", size_code)], limit=1)
            if rec:
                return rec
        return Size.browse()

    def find_pricing_rule(self, origin_gov=None, dest_gov=None, weight_kg=None):
        Rule = self.env["shipblu.pricing.rule"]
        domain = [
            ("backend_id", "=", self.backend.id),
            ("active", "=", True),
        ]
        if origin_gov:
            domain.append(("origin_governorate", "=ilike", origin_gov))
        if dest_gov:
            domain.append(("destination_governorate", "=ilike", dest_gov))
        rules = Rule.search(domain, order="sequence, id")
        weight = float(weight_kg or 0.0)
        for rule in rules:
            if rule.min_weight and weight < rule.min_weight:
                continue
            if rule.max_weight and weight > rule.max_weight:
                continue
            if rule.date_from or rule.date_to:
                from odoo import fields as odoo_fields

                today = odoo_fields.Date.context_today(self.backend)
                if rule.date_from and today < rule.date_from:
                    continue
                if rule.date_to and today > rule.date_to:
                    continue
            return rule
        return Rule.browse()

    def compute(
        self,
        *,
        origin_governorate="Giza",
        destination_governorate=None,
        package_size_id=None,
        package_size_code=None,
        cod_amount=0.0,
        weight_kg=0.0,
        try_and_buy=False,
        inspection=False,
        include_return_fee=False,
        customer_refused_return_pay=False,
        pickup_shipment_count=None,
        api_base_price=None,
        tax_rate=0.0,
        force_confirmed=False,
    ):
        notes = []
        bd = CostBreakdown(currency=self.backend.company_id.currency_id.name or "EGP")

        # Base price: API authoritative if provided
        if api_base_price is not None:
            bd.base_fee = float(api_base_price)
            bd.pricing_source = "api"
            notes.append("Base price from ShipBlu API quote (authoritative).")
        else:
            rule = self.find_pricing_rule(origin_governorate, destination_governorate, weight_kg)
            if rule:
                bd.base_fee = float(rule.base_price)
                bd.pricing_rule_id = rule.id
                bd.pricing_source = rule.source or "manual"
                notes.append(f"Pricing rule: {rule.display_name}")
            else:
                notes.append("No pricing rule matched; base fee = 0.")

        size = self.resolve_package_size(package_size_id, package_size_code)
        if size:
            pct = float(size.surcharge_percent or 0.0)
            bd.size_surcharge = round(bd.base_fee * pct / 100.0, 2)
            if pct:
                notes.append(f"Package size {size.code}: +{pct}%")
        elif package_size_id or package_size_code:
            notes.append("Package size not mapped locally; no size surcharge applied.")

        cod = float(cod_amount or 0.0)
        if cod > 0 and self.backend.cod_commission_rate:
            bd.cod_fee = round(cod * float(self.backend.cod_commission_rate) / 100.0, 2)
            notes.append(f"COD commission {self.backend.cod_commission_rate}%")

        if try_and_buy:
            bd.try_and_buy_fee = float(self.backend.try_and_buy_fee or 0.0)
            notes.append("Try & Buy fee")
        if inspection:
            bd.inspection_fee = float(self.backend.inspection_fee or 0.0)
            notes.append("Inspection fee")
        if include_return_fee:
            bd.return_fee = float(self.backend.return_service_fee or 0.0)
            notes.append("Return service fee")
        if customer_refused_return_pay:
            # 90% of shipping fees (base + size) estimate
            shipping = bd.base_fee + bd.size_surcharge
            pct = float(self.backend.return_refusal_charge_percent or 0.0)
            refusal = round(shipping * pct / 100.0, 2)
            bd.return_fee = round(bd.return_fee + refusal, 2)
            notes.append(f"Return refusal estimate {pct}% of shipping")

        min_pick = int(self.backend.min_shipments_per_pickup or 5)
        if pickup_shipment_count is not None and int(pickup_shipment_count) < min_pick:
            bd.pickup_surcharge = float(self.backend.low_volume_pickup_surcharge or 0.0)
            notes.append(f"Low-volume pickup surcharge (count {pickup_shipment_count} < {min_pick})")

        subtotal_before_discount = (
            bd.base_fee
            + bd.size_surcharge
            + bd.cod_fee
            + bd.try_and_buy_fee
            + bd.inspection_fee
            + bd.return_fee
            + bd.pickup_surcharge
        )

        tier, month_count = self.active_discount_tier()
        bd.monthly_shipment_count = month_count
        if tier and not force_confirmed:
            # Estimated only — never auto-confirm
            disc_pct = float(tier.discount_percent or 0.0)
            bd.discount = round(bd.base_fee * disc_pct / 100.0, 2)
            bd.discount_tier_label = f"{tier.min_shipments}-{tier.max_shipments}: {disc_pct}%"
            bd.status = "estimated"
            notes.append(f"Estimated volume discount {disc_pct}% on base (not confirmed)")
        elif tier and force_confirmed:
            disc_pct = float(tier.discount_percent or 0.0)
            bd.discount = round(bd.base_fee * disc_pct / 100.0, 2)
            bd.discount_tier_label = f"{tier.min_shipments}-{tier.max_shipments}: {disc_pct}%"
            bd.status = "confirmed"
        else:
            bd.status = "estimated" if not force_confirmed else "confirmed"
            if month_count and not tier:
                notes.append(f"Monthly count {month_count} falls in a discount gap (no tier).")

        taxable = max(subtotal_before_discount - bd.discount, 0.0)
        if tax_rate:
            bd.tax = round(taxable * float(tax_rate) / 100.0, 2)
        bd.total = round(taxable + bd.tax, 2)
        bd.notes = notes
        return bd
