# -*- coding: utf-8 -*-
"""True landed-cost engine for PetSpot Vetution fulfillment (shadow-safe).

Reuses petspot_shipblu_base.services.cost_engine.CostEngine for ShipBlu
estimates. Never invents unknown values. Never creates shipments/AWBs.

Phase 15A.4 — Giza ecommerce origin:
  Vetution → PetSpot Giza fulfillment → customer (ShipBlu) or Giza pickup.
  Customer delivery charge (e.g. EGP 118) is order-level revenue, not a
  product cost. Full ShipBlu cost is NOT added to product price when the
  customer is charged for delivery; only delivery shortfall (if any) enters
  product landed cost / order profitability.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

MANDATORY_KEYS = (
    "supplier_cost",
    "supplier_shipping",
    "shipblu_shipping",
    "cod_commission",
    "payment_gateway_fee",
    "packaging",
    "tax",
    "return_risk",
    "handling",
)

# Keys that belong in product price worksheet when delivery is separately charged.
PRODUCT_LANDED_KEYS = (
    "supplier_cost",
    "supplier_shipping",
    "payment_gateway_fee",
    "packaging",
    "tax",
    "return_risk",
    "handling",
)

DELIVERY_COST_KEYS = ("shipblu_shipping", "cod_commission")

# Recovered via customer delivery charge on shipblu_delivery (not product COGS).
DELIVERY_RECOVERED_KEYS = ("shipblu_shipping", "cod_commission")

STATUS_KNOWN = {"verified", "verified_zero", "configured", "estimated"}
STATUS_CRITICAL_UNKNOWN = {
    "supplier_cost",
    "supplier_shipping",
    "shipblu_shipping",
    "packaging",
    "payment_gateway_fee",
}


@dataclass
class CostComponent:
    key: str
    label: str
    amount: float | None
    status: str  # verified | verified_zero | configured | estimated | unknown | not_applicable
    source: str = ""
    is_estimate: bool = False
    expected: bool = True  # expected provision vs actual
    detail: dict = field(default_factory=dict)

    @property
    def is_known(self) -> bool:
        return self.status in STATUS_KNOWN or self.status == "not_applicable"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["is_known"] = self.is_known
        return d


@dataclass
class LandedCostResult:
    components: list
    landed_cost: float | None
    landed_cost_incomplete: bool
    completeness_percent: float
    pricing_confidence_percent: float
    pricing_confidence_label: str
    decision_code: str
    missing_keys: list
    estimate_keys: list
    shipblu_breakdown: dict | None = None
    notes: list = field(default_factory=list)
    product_landed_cost: float | None = None
    customer_delivery_charge: float | None = None
    estimated_carrier_cost: float | None = None
    delivery_specific_fees: float | None = None
    delivery_margin: float | None = None
    delivery_subsidy: float | None = None
    delivery_profit_or_subsidy: float | None = None  # alias of delivery_margin
    delivery_shortfall: float | None = None  # alias of delivery_subsidy (order PnL only)
    proposed_delivery_charge: float | None = None
    delivery_gate_passed: bool = True
    delivery_review_required: bool = False
    recommended_product_price: float | None = None
    order_total: float | None = None
    product_cost_completeness: float = 0.0
    delivery_cost_completeness: float = 0.0
    overall_completeness: float = 0.0
    product_decision_code: str = ""
    delivery_decision_code: str = ""
    scenario: str = ""
    evidence_source: str = ""
    formula: str = (
        "product_landed = supplier + supplier_shipping(Vetution→Giza) "
        "+ payment_fee + packaging + tax + return_risk + handling "
        "(NO outbound ShipBlu / NO customer delivery charge); "
        "delivery_margin = customer_delivery_charge - carrier - delivery_fees; "
        "order_total = recommended_product_price + customer_delivery_charge"
    )

    def component_map(self) -> dict:
        return {c.key: c for c in self.components}

    def amount_or_zero(self, key: str) -> float:
        c = self.component_map().get(key)
        if not c or c.amount is None or not c.is_known:
            return 0.0
        return float(c.amount)

    def to_dict(self) -> dict:
        return {
            "formula": self.formula,
            "landed_cost": self.landed_cost,
            "product_landed_cost": self.product_landed_cost,
            "landed_cost_incomplete": self.landed_cost_incomplete,
            "customer_delivery_charge": self.customer_delivery_charge,
            "estimated_carrier_cost": self.estimated_carrier_cost,
            "delivery_specific_fees": self.delivery_specific_fees,
            "delivery_margin": self.delivery_margin,
            "delivery_subsidy": self.delivery_subsidy,
            "delivery_profit_or_subsidy": self.delivery_profit_or_subsidy,
            "delivery_shortfall": self.delivery_shortfall,
            "proposed_delivery_charge": self.proposed_delivery_charge,
            "delivery_gate_passed": self.delivery_gate_passed,
            "delivery_review_required": self.delivery_review_required,
            "recommended_product_price": self.recommended_product_price,
            "order_total": self.order_total,
            "product_cost_completeness": self.product_cost_completeness,
            "delivery_cost_completeness": self.delivery_cost_completeness,
            "overall_completeness": self.overall_completeness,
            "product_decision_code": self.product_decision_code,
            "delivery_decision_code": self.delivery_decision_code,
            "scenario": self.scenario,
            "evidence_source": self.evidence_source,
            "completeness_percent": self.completeness_percent,
            "pricing_confidence_percent": self.pricing_confidence_percent,
            "pricing_confidence_label": self.pricing_confidence_label,
            "decision_code": self.decision_code,
            "missing_keys": self.missing_keys,
            "estimate_keys": self.estimate_keys,
            "components": [c.to_dict() for c in self.components],
            "shipblu_breakdown": self.shipblu_breakdown,
            "notes": self.notes,
        }

    def report_lines(self) -> list:
        lines = []
        for c in self.components:
            amt = "unknown" if c.amount is None or c.status == "unknown" else f"{c.amount:.2f}"
            mark = "✓" if c.is_known else "✗"
            lines.append(f"{mark} {c.label}: {amt} [{c.status}]")
        total = "incomplete" if self.landed_cost_incomplete else f"{self.landed_cost:.2f}"
        lines.append(f"--- PRODUCT landed (price worksheet): {self.product_landed_cost}")
        lines.append(f"--- Recommended product price: {self.recommended_product_price}")
        lines.append(f"--- DELIVERY charge (revenue): {self.customer_delivery_charge}")
        lines.append(f"--- Estimated carrier cost: {self.estimated_carrier_cost}")
        lines.append(f"--- Delivery-specific fees: {self.delivery_specific_fees}")
        lines.append(f"--- Delivery margin: {self.delivery_margin}")
        lines.append(f"--- Delivery subsidy: {self.delivery_subsidy}")
        lines.append(f"--- Proposed break-even delivery charge: {self.proposed_delivery_charge}")
        lines.append(f"--- Delivery gate passed: {self.delivery_gate_passed}")
        lines.append(f"--- Order total: {self.order_total}")
        lines.append(
            f"--- Completeness product/delivery/overall: "
            f"{self.product_cost_completeness}/{self.delivery_cost_completeness}/{self.overall_completeness}"
        )
        lines.append(f"--- Gross mandatory stack (audit): {total}")
        lines.append(f"Completeness: {self.completeness_percent:.0f}%")
        lines.append(
            f"Confidence: {self.pricing_confidence_percent:.0f}% ({self.pricing_confidence_label})"
        )
        lines.append(f"Decision: {self.decision_code}")
        return lines


class LandedCostEngine:
    """Compute explainable true landed cost from policy + context."""

    def __init__(self, env, policy):
        self.env = env
        self.policy = policy

    # ------------------------------------------------------------------ public
    def compute(self, *, supplier_cost: float, context: dict | None = None) -> LandedCostResult:
        ctx = dict(context or {})
        notes: list[str] = []
        components: list[CostComponent] = []

        # 1) Supplier purchase
        cost = float(supplier_cost or 0.0)
        if cost > 0:
            components.append(
                CostComponent(
                    "supplier_cost",
                    "Supplier Cost",
                    cost,
                    "verified",
                    source="vetution.supplier.offer.effective_cost",
                )
            )
        else:
            components.append(
                CostComponent(
                    "supplier_cost",
                    "Supplier Cost",
                    None,
                    "unknown",
                    source="missing or zero supplier commercial price",
                )
            )

        # 2) Supplier shipping
        components.append(self._supplier_shipping(cost, ctx, notes))

        # 3+4) ShipBlu shipping + COD commission (reuse CostEngine)
        shipblu_comp, cod_comp, shipblu_bd = self._shipblu_and_cod(cost, ctx, notes)
        components.append(shipblu_comp)
        components.append(cod_comp)

        # 5) Payment gateway fee (non-COD methods; COD fee is in cod_commission)
        components.append(self._payment_fee(cost, ctx, notes))

        # 6) Packaging
        components.append(self._packaging(ctx, notes))

        # 7) Tax
        components.append(self._tax(cost, components, notes))

        # 8) Return risk (expected provision)
        components.append(self._return_risk(cost, components, notes))

        # 9) Operational handling
        components.append(self._handling(notes))

        # 10–11) Customer delivery charge (order revenue) + shortfall into product landed
        delivery_comps, delivery_meta = self._delivery_charge_and_shortfall(
            ctx, components, notes
        )
        components.extend(delivery_comps)

        return self._finalize(components, shipblu_bd, notes, delivery_meta=delivery_meta)

    # ------------------------------------------------------------------ pieces
    def _supplier_shipping(self, supplier_cost, ctx, notes):
        mode = self.policy.supplier_shipping_mode or "unknown"
        if mode == "included":
            return CostComponent(
                "supplier_shipping",
                "Supplier Shipping",
                0.0,
                "verified_zero",
                source="Policy: supplier includes shipping",
            )
        if mode == "fixed":
            if self.policy.supplier_shipping_status == "unknown":
                return CostComponent(
                    "supplier_shipping",
                    "Supplier Shipping",
                    None,
                    "unknown",
                    source="Fixed mode but status unknown",
                )
            amt = float(self.policy.supplier_shipping_amount or 0.0)
            st = "verified_zero" if amt == 0 else "configured"
            return CostComponent(
                "supplier_shipping",
                "Supplier Shipping",
                amt,
                st,
                source=self.policy.supplier_shipping_source or "policy.supplier_shipping_amount",
            )
        if mode == "calculated":
            # Placeholder for future supplier calculator — unknown until implemented
            notes.append("Supplier shipping mode=calculated but no calculator configured.")
            return CostComponent(
                "supplier_shipping",
                "Supplier Shipping",
                None,
                "unknown",
                source="calculated mode without calculator",
            )
        # unknown — never assume zero
        return CostComponent(
            "supplier_shipping",
            "Supplier Shipping",
            None,
            "unknown",
            source=self.policy.supplier_shipping_source
            or "Vetution → Giza supplier shipping not verified (never assume zero)",
        )

    def _shipblu_and_cod(self, supplier_cost, ctx, notes):
        fulfillment = ctx.get("requested_fulfillment") or "undecided"
        if fulfillment == "store_pickup":
            return (
                CostComponent(
                    "shipblu_shipping",
                    "ShipBlu Shipping",
                    0.0,
                    "not_applicable",
                    source="Store pickup — no ShipBlu AWB",
                ),
                CostComponent(
                    "cod_commission",
                    "COD Commission",
                    0.0,
                    "not_applicable",
                    source="Store pickup",
                ),
                None,
            )

        if "shipblu.backend" not in self.env:
            notes.append("shipblu.backend model unavailable")
            return (
                CostComponent("shipblu_shipping", "ShipBlu Shipping", None, "unknown", source="module missing"),
                CostComponent("cod_commission", "COD Commission", None, "unknown", source="module missing"),
                None,
            )

        backend = self.env["shipblu.backend"].sudo().search(
            [("company_id", "=", self.policy.company_id.id)], limit=1
        )
        if not backend:
            backend = self.env["shipblu.backend"].sudo().search([], limit=1)
        if not backend:
            notes.append("No shipblu.backend configured")
            return (
                CostComponent("shipblu_shipping", "ShipBlu Shipping", None, "unknown", source="no backend"),
                CostComponent("cod_commission", "COD Commission", None, "unknown", source="no backend"),
                None,
            )

        dest = ctx.get("destination_governorate") or self.policy.default_destination_governorate
        package_code = ctx.get("package_size_code") or self.policy.default_package_size_code
        package_id = ctx.get("package_size_id")
        if not dest:
            notes.append("Destination governorate unknown — ShipBlu estimate blocked")
            return (
                CostComponent(
                    "shipblu_shipping",
                    "ShipBlu Shipping",
                    None,
                    "unknown",
                    source="destination_governorate missing",
                ),
                CostComponent(
                    "cod_commission",
                    "COD Commission",
                    None,
                    "unknown",
                    source="requires ShipBlu estimate context",
                ),
                None,
            )
        if not package_code and not package_id:
            notes.append("Package size unresolved — ShipBlu estimate blocked")
            return (
                CostComponent(
                    "shipblu_shipping",
                    "ShipBlu Shipping",
                    None,
                    "unknown",
                    source="package_size unknown",
                ),
                CostComponent(
                    "cod_commission",
                    "COD Commission",
                    None,
                    "unknown",
                    source="package_size unknown",
                ),
                None,
            )

        payment_method = ctx.get("payment_method") or self.policy.default_payment_method or "unknown"
        # COD amount for commission: use suggested sell preview base or supplier*markup proxy
        cod_amount = float(ctx.get("cod_amount") or 0.0)
        if payment_method == "cod" and cod_amount <= 0:
            # provisional COD base = supplier cost only for estimate; caller may pass better
            cod_amount = float(ctx.get("estimated_collect_amount") or supplier_cost or 0.0)

        try:
            from odoo.addons.petspot_shipblu_base.services.cost_engine import CostEngine

            engine = CostEngine(backend)
            bd = engine.compute(
                origin_governorate=self.policy.default_origin_governorate or "Giza",
                destination_governorate=dest,
                package_size_id=package_id,
                package_size_code=package_code,
                cod_amount=cod_amount if payment_method == "cod" else 0.0,
                weight_kg=float(ctx.get("weight_kg") or self.policy.default_weight_kg or 0.0),
                force_confirmed=False,
            )
            bd_dict = bd.to_dict()
            # Shipping portion excludes COD (tracked separately)
            shipping_total = float(bd.base_fee or 0.0) + float(bd.size_surcharge or 0.0)
            shipping_total += float(bd.pickup_surcharge or 0.0)
            shipping_total -= float(bd.discount or 0.0)
            shipping_total = max(shipping_total, 0.0)

            if shipping_total <= 0 and "No pricing rule matched" in " ".join(bd.notes or []):
                ship_comp = CostComponent(
                    "shipblu_shipping",
                    "ShipBlu Shipping",
                    None,
                    "unknown",
                    source="CostEngine: no pricing rule matched",
                    detail=bd_dict,
                )
            else:
                origin = self.policy.default_origin_governorate or "Giza"
                source = f"CostEngine/{bd.pricing_source}"
                if (
                    origin == "Giza"
                    and dest == "Giza"
                    and (package_code or "") == "small"
                    and abs(shipping_total - 95.0) < 1e-6
                ):
                    source = (
                        "APPROVED_PROVISIONAL_ESTIMATE: Giza→Giza/small/EGP95 "
                        f"(CostEngine/{bd.pricing_source}; not invoice/universal tariff)"
                    )
                    notes.append(source)
                ship_comp = CostComponent(
                    "shipblu_shipping",
                    "ShipBlu Shipping",
                    round(shipping_total, 2),
                    "estimated",
                    source=source,
                    is_estimate=True,
                    detail=bd_dict,
                )

            if payment_method in ("unknown", False, None, ""):
                # Cannot classify COD vs prepaid — leave COD unknown (do not invent N/A)
                cod_comp = CostComponent(
                    "cod_commission",
                    "COD Commission",
                    None,
                    "unknown",
                    source="payment_method unresolved — COD vs prepaid unknown",
                )
            elif payment_method == "cod":
                if backend.cod_commission_rate is False or backend.cod_commission_rate is None:
                    cod_comp = CostComponent(
                        "cod_commission",
                        "COD Commission",
                        None,
                        "unknown",
                        source="backend.cod_commission_rate missing",
                    )
                else:
                    cod_comp = CostComponent(
                        "cod_commission",
                        "COD Commission",
                        round(float(bd.cod_fee or 0.0), 2),
                        "estimated",
                        source=f"ShipBlu COD {backend.cod_commission_rate}%",
                        is_estimate=True,
                        detail={"cod_amount": cod_amount},
                    )
            else:
                cod_comp = CostComponent(
                    "cod_commission",
                    "COD Commission",
                    0.0,
                    "not_applicable",
                    source=f"payment_method={payment_method}",
                )
            return ship_comp, cod_comp, bd_dict
        except Exception as err:  # noqa: BLE001
            notes.append(f"ShipBlu CostEngine error: {err}")
            return (
                CostComponent(
                    "shipblu_shipping",
                    "ShipBlu Shipping",
                    None,
                    "unknown",
                    source=str(err)[:200],
                ),
                CostComponent(
                    "cod_commission",
                    "COD Commission",
                    None,
                    "unknown",
                    source="ShipBlu estimate failed",
                ),
                None,
            )

    def _payment_fee(self, supplier_cost, ctx, notes):
        method = ctx.get("payment_method") or self.policy.default_payment_method or "unknown"
        if method in ("unknown", False, None):
            return CostComponent(
                "payment_gateway_fee",
                "Payment Gateway Fee",
                None,
                "unknown",
                source="payment method unresolved",
            )
        if method == "cod":
            # COD commission already separate
            return CostComponent(
                "payment_gateway_fee",
                "Payment Gateway Fee",
                0.0,
                "not_applicable",
                source="COD uses cod_commission component",
            )
        # Look up fee from policy payment fee lines
        Fee = self.env["petspot.vetution.payment.fee"]
        fee = Fee.search(
            [
                ("policy_id", "=", self.policy.id),
                ("payment_method", "=", method),
                ("active", "=", True),
            ],
            limit=1,
        )
        if not fee:
            if self.policy.payment_fee_status == "verified_zero":
                return CostComponent(
                    "payment_gateway_fee",
                    "Payment Gateway Fee",
                    0.0,
                    "verified_zero",
                    source="policy.payment_fee_status=verified_zero",
                )
            return CostComponent(
                "payment_gateway_fee",
                "Payment Gateway Fee",
                None,
                "unknown",
                source=f"No fee row for method={method}",
            )
        if fee.status == "unknown":
            return CostComponent(
                "payment_gateway_fee",
                "Payment Gateway Fee",
                None,
                "unknown",
                source=fee.source_note or f"{method} fee unknown",
            )
        # Fee often % of selling price; for landed cost we apply % of supplier as provisional
        # unless collect_amount provided — mark as estimate when percent-based on provisional base.
        base = float(ctx.get("estimated_collect_amount") or supplier_cost or 0.0)
        amount = base * float(fee.percent or 0.0) / 100.0 + float(fee.fixed_amount or 0.0)
        is_est = bool(fee.percent) and not ctx.get("estimated_collect_amount")
        return CostComponent(
            "payment_gateway_fee",
            "Payment Gateway Fee",
            round(amount, 2),
            "estimated" if is_est else fee.status,
            source=fee.source_note or f"{method} fee schedule",
            is_estimate=is_est or fee.status == "estimated",
        )

    def _packaging(self, ctx, notes):
        pkg_type = ctx.get("packaging_type") or self.policy.default_packaging_type
        if not pkg_type:
            return CostComponent(
                "packaging",
                "Packaging",
                None,
                "unknown",
                source="packaging type unresolved",
            )
        Pkg = self.env["petspot.vetution.packaging.cost"]
        row = Pkg.search(
            [
                ("policy_id", "=", self.policy.id),
                ("packaging_type", "=", pkg_type),
                ("active", "=", True),
            ],
            limit=1,
        )
        if not row:
            if self.policy.packaging_handling_status == "verified_zero":
                return CostComponent(
                    "packaging",
                    "Packaging",
                    0.0,
                    "verified_zero",
                    source="legacy packaging_handling_status=verified_zero",
                )
            return CostComponent(
                "packaging",
                "Packaging",
                None,
                "unknown",
                source=f"No packaging cost for type={pkg_type}",
            )
        if row.status == "unknown":
            return CostComponent(
                "packaging",
                "Packaging",
                None,
                "unknown",
                source=row.source_note or pkg_type,
            )
        return CostComponent(
            "packaging",
            "Packaging",
            float(row.amount or 0.0),
            row.status,
            source=row.source_note or f"packaging:{pkg_type}",
        )

    def _tax(self, supplier_cost, components, notes):
        mode = self.policy.tax_mode or "unknown"
        if mode == "unknown":
            return CostComponent(
                "tax",
                "Tax",
                None,
                "unknown",
                source=self.policy.non_recoverable_tax_source or "tax mode unknown",
            )
        if mode == "exempt":
            return CostComponent(
                "tax",
                "Tax",
                0.0,
                "verified_zero",
                source="tax_mode=exempt",
            )
        if self.policy.non_recoverable_tax_status == "unknown" and mode in ("inclusive", "exclusive"):
            # Need rate
            if not self.policy.non_recoverable_tax_rate and self.policy.non_recoverable_tax_status != "verified_zero":
                return CostComponent(
                    "tax",
                    "Tax",
                    None,
                    "unknown",
                    source="tax mode set but rate/status unknown",
                )
        if self.policy.non_recoverable_tax_status == "verified_zero":
            return CostComponent("tax", "Tax", 0.0, "verified_zero", source="verified zero tax")
        rate = float(self.policy.non_recoverable_tax_rate or 0.0)
        # Apply on supplier cost for exclusive; inclusive treated as already in supplier (0 add)
        if mode == "inclusive":
            return CostComponent(
                "tax",
                "Tax",
                0.0,
                "configured",
                source="VAT inclusive in supplier price — no add-on",
            )
        amt = round(float(supplier_cost or 0.0) * rate / 100.0, 2)
        return CostComponent(
            "tax",
            "Tax",
            amt,
            "configured",
            source=f"exclusive {rate}% on supplier cost",
        )

    def _return_risk(self, supplier_cost, components, notes):
        status = self.policy.risk_return_allowance_status or "unknown"
        if status == "unknown":
            return CostComponent(
                "return_risk",
                "Return Risk Provision",
                None,
                "unknown",
                source=self.policy.risk_return_allowance_source or "not configured",
                expected=True,
            )
        if status == "verified_zero":
            return CostComponent(
                "return_risk",
                "Return Risk Provision",
                0.0,
                "verified_zero",
                source="verified zero provision",
                expected=True,
            )
        mode = self.policy.risk_mode or "percent"
        if mode == "fixed":
            amt = float(self.policy.risk_fixed_amount or 0.0)
        else:
            amt = round(
                float(supplier_cost or 0.0)
                * float(self.policy.risk_return_allowance_rate or 0.0)
                / 100.0,
                2,
            )
        return CostComponent(
            "return_risk",
            "Return Risk Provision",
            amt,
            "configured",
            source=self.policy.risk_return_allowance_source or f"risk_mode={mode}",
            expected=True,
            detail={"expected_vs_actual": "expected"},
        )

    def _handling(self, notes):
        status = self.policy.handling_status or "unknown"
        if status == "unknown":
            return CostComponent(
                "handling",
                "Operational Handling",
                None,
                "unknown",
                source=self.policy.handling_source or "warehouse/picking/packing not configured",
            )
        if status == "verified_zero":
            return CostComponent(
                "handling",
                "Operational Handling",
                0.0,
                "verified_zero",
                source="verified zero handling",
            )
        amt = float(self.policy.handling_amount or 0.0)
        return CostComponent(
            "handling",
            "Operational Handling",
            amt,
            "configured",
            source=self.policy.handling_source or "policy.handling_amount",
        )

    def _delivery_charge_and_shortfall(self, ctx, components, notes):
        """Order-level delivery revenue vs carrier cost — NEVER added to product landed.

        Product catalog price excludes ShipBlu and customer delivery charge.
        delivery_margin / delivery_subsidy are order-economics only.
        """
        fulfillment = ctx.get("requested_fulfillment") or "undecided"
        cmap = {c.key: c for c in components}
        extras = []
        scenario = fulfillment

        if fulfillment == "store_pickup":
            pickup_fee = float(
                ctx.get("customer_pickup_fee")
                if ctx.get("customer_pickup_fee") is not None
                else (getattr(self.policy, "customer_pickup_fee_amount", 0.0) or 0.0)
            )
            pickup_status = getattr(self.policy, "customer_pickup_fee_status", None) or "verified_zero"
            if pickup_fee <= 0 or pickup_status in ("verified_zero", "unknown"):
                charge = 0.0
                extras.append(
                    CostComponent(
                        "customer_delivery_charge",
                        "Customer Delivery Charge",
                        0.0,
                        "not_applicable",
                        source="Giza store pickup — delivery revenue zero unless approved pickup fee",
                    )
                )
            else:
                charge = pickup_fee
                extras.append(
                    CostComponent(
                        "customer_delivery_charge",
                        "Customer Delivery / Pickup Fee",
                        pickup_fee,
                        "configured",
                        source=self.policy.customer_pickup_fee_source or "approved pickup fee",
                    )
                )
            notes.append("Scenario A: Giza store pickup — ShipBlu/COD N/A; delivery revenue 0")
            return extras, {
                "scenario": "store_pickup",
                "customer_delivery_charge": charge,
                "estimated_carrier_cost": 0.0,
                "delivery_specific_fees": 0.0,
                "delivery_margin": 0.0,
                "delivery_subsidy": 0.0,
                "delivery_profit_or_subsidy": 0.0,
                "delivery_shortfall": 0.0,
                "evidence_source": "store_pickup",
            }

        # Resolve customer delivery revenue (rules → policy → context)
        Rule = self.env["petspot.vetution.delivery.revenue.rule"]
        charge, charge_status, charge_source, rule = Rule.resolve_charge(self.policy, ctx)
        if charge_status == "unknown" and charge is None:
            extras.append(
                CostComponent(
                    "customer_delivery_charge",
                    "Customer Delivery Charge",
                    None,
                    "unknown",
                    source=charge_source,
                )
            )
            notes.append("Customer delivery charge unknown — delivery economics incomplete")
            return extras, {
                "scenario": scenario,
                "customer_delivery_charge": None,
                "estimated_carrier_cost": None,
                "delivery_specific_fees": None,
                "delivery_margin": None,
                "delivery_subsidy": None,
                "delivery_profit_or_subsidy": None,
                "delivery_shortfall": None,
                "evidence_source": charge_source,
            }

        promo = (ctx.get("shipping_promotion") or "").lower()
        if promo in ("free", "free_shipping"):
            scenario = "free_shipping"
        elif promo in ("discounted", "discount") or (
            "customer_delivery_charge" in ctx
            and ctx.get("customer_delivery_charge") is not None
            and float(ctx.get("customer_delivery_charge")) < float(
                getattr(self.policy, "customer_delivery_charge_amount", 118.0) or 118.0
            )
            and float(ctx.get("customer_delivery_charge")) > 0
        ):
            scenario = "discounted_shipping"
        else:
            scenario = "shipblu_delivery"

        extras.append(
            CostComponent(
                "customer_delivery_charge",
                "Customer Delivery Charge",
                float(charge),
                "configured" if charge_status != "verified" else "verified",
                source=charge_source
                + (f" rule#{rule.id}" if rule else "")
                + " (order revenue — NOT product COGS)",
            )
        )

        ship = cmap.get("shipblu_shipping")
        cod = cmap.get("cod_commission")
        ship_known = bool(
            ship and ship.is_known and ship.amount is not None and ship.status != "not_applicable"
        )
        if cod and cod.status == "not_applicable":
            cod_known = True
            cod_amt = 0.0
        else:
            cod_known = bool(cod and cod.is_known and cod.amount is not None)
            cod_amt = float(cod.amount or 0.0) if cod_known else None
        ship_amt = float(ship.amount or 0.0) if ship_known else None

        if ship_amt is None or cod_amt is None:
            notes.append("Carrier/COD incomplete — delivery margin unresolved (product price unaffected)")
            return extras, {
                "scenario": scenario,
                "customer_delivery_charge": float(charge),
                "estimated_carrier_cost": ship_amt,
                "delivery_specific_fees": cod_amt,
                "delivery_margin": None,
                "delivery_subsidy": None,
                "delivery_profit_or_subsidy": None,
                "delivery_shortfall": None,
                "evidence_source": charge_source,
            }

        margin = round(float(charge) - ship_amt - cod_amt, 2)
        subsidy = round(max(0.0, ship_amt + cod_amt - float(charge)), 2)
        notes.append(
            f"delivery_margin = {charge} - carrier {ship_amt} - fees {cod_amt} = {margin}; "
            f"delivery_subsidy = {subsidy}"
        )
        if ship and ship.source:
            notes.append(f"carrier_source={ship.source}")
        return extras, {
            "scenario": scenario,
            "customer_delivery_charge": float(charge),
            "estimated_carrier_cost": ship_amt,
            "delivery_specific_fees": cod_amt,
            "delivery_margin": margin,
            "delivery_subsidy": subsidy,
            "delivery_profit_or_subsidy": margin,
            "delivery_shortfall": subsidy,
            "evidence_source": charge_source,
        }

    # ------------------------------------------------------------------ finalize
    def _finalize(self, components, shipblu_bd, notes, delivery_meta=None):
        delivery_meta = delivery_meta or {}
        cmap = {c.key: c for c in components}

        def _layer_stats(keys):
            missing = []
            estimates = []
            known = 0
            for key in keys:
                c = cmap.get(key)
                if not c:
                    missing.append(key)
                    continue
                if c.status == "not_applicable":
                    known += 1
                    continue
                if c.is_known:
                    known += 1
                    if c.is_estimate or c.status == "estimated":
                        estimates.append(key)
                else:
                    missing.append(key)
            completeness = round(100.0 * known / max(len(keys), 1), 2)
            return missing, estimates, completeness

        product_missing, product_est, product_comp = _layer_stats(PRODUCT_LANDED_KEYS)
        delivery_missing, delivery_est, delivery_comp = _layer_stats(DELIVERY_COST_KEYS)
        # Overall = mean of layers (equal weight product + delivery)
        overall = round((product_comp + delivery_comp) / 2.0, 2)

        # Legacy mandatory completeness (includes all MANDATORY_KEYS)
        missing, estimates, completeness = _layer_stats(MANDATORY_KEYS)
        incomplete = bool(missing)

        # Confidence uses product + delivery estimates (legacy field)
        all_estimates = list(product_est) + list(delivery_est)
        critical_missing = [k for k in product_missing if k in STATUS_CRITICAL_UNKNOWN]
        if critical_missing or product_comp < 50:
            conf_pct, conf_label = 40.0, "Critical product costs missing"
        elif len(all_estimates) >= 2:
            conf_pct, conf_label = 60.0, "Multiple estimates"
        elif len(all_estimates) == 1:
            conf_pct, conf_label = 80.0, "One estimate"
        elif product_comp >= 100 and delivery_comp >= 100 and not all_estimates:
            conf_pct, conf_label = 100.0, "Verified"
        else:
            conf_pct, conf_label = 80.0, "Partial verified"

        # Layer decisions
        if product_comp >= 100 and not product_missing:
            product_decision = "PRODUCT_PRICE_READY"
        else:
            product_decision = "INSUFFICIENT_PRODUCT_COST_DATA"

        if delivery_comp >= 100 and not delivery_missing:
            if delivery_meta.get("scenario") == "store_pickup":
                delivery_decision = "ORDER_ECONOMICS_READY"
            elif delivery_meta.get("delivery_margin") is not None:
                delivery_decision = "ORDER_ECONOMICS_READY"
            else:
                delivery_decision = "DELIVERY_COST_INCOMPLETE"
        else:
            delivery_decision = "INSUFFICIENT_DELIVERY_COST_DATA"

        # --- Delivery price-review gate (Phase 15B) ---
        # Never fold subsidy into product_landed; break-even proposed charge is
        # informational only (estimated_carrier_cost + delivery_specific_fees +
        # max_auto_delivery_subsidy).
        max_auto_subsidy = float(getattr(self.policy, "max_auto_delivery_subsidy", 0.0) or 0.0)
        carrier_cost = delivery_meta.get("estimated_carrier_cost")
        delivery_fees = delivery_meta.get("delivery_specific_fees")
        proposed_delivery_charge = None
        if carrier_cost is not None and delivery_fees is not None:
            proposed_delivery_charge = round(
                float(carrier_cost) + float(delivery_fees) + max_auto_subsidy, 2
            )
        delivery_subsidy = delivery_meta.get("delivery_subsidy")
        delivery_gate_passed = True
        if delivery_meta.get("scenario") != "store_pickup" and delivery_subsidy is not None:
            if float(delivery_subsidy) > max_auto_subsidy + 1e-9:
                delivery_gate_passed = False
                delivery_decision = "DELIVERY_PRICE_REVIEW_REQUIRED"
                notes.append(
                    f"Delivery gate FAILED: subsidy {delivery_subsidy} > "
                    f"max_auto_delivery_subsidy {max_auto_subsidy} — "
                    f"proposed break-even delivery charge = {proposed_delivery_charge}"
                )

        # Combined decision — preserve READY_FOR_AUTO_QUOTE when both layers complete
        # (Phase locks still prevent actual auto-quote.)
        if product_decision == "PRODUCT_PRICE_READY" and delivery_decision == "ORDER_ECONOMICS_READY":
            if conf_pct >= 100 and not incomplete:
                decision = "READY_FOR_AUTO_QUOTE"
            else:
                decision = "READY_FOR_MANUAL_REVIEW"
            notes.append(
                "Layers: PRODUCT_PRICE_READY + ORDER_ECONOMICS_READY "
                "(delivery revenue separate from product price)"
            )
        elif product_decision == "PRODUCT_PRICE_READY":
            decision = "PRODUCT_PRICE_READY"
            notes.append("Product recommendation READY; delivery economics incomplete/partial")
        elif completeness >= 90:
            decision = "READY_FOR_MANUAL_REVIEW"
        elif completeness >= 75:
            decision = "SHADOW_ONLY"
        elif completeness >= 50:
            decision = "BLOCK_PRICE_PUBLISH"
        else:
            decision = "INSUFFICIENT_COST_DATA"

        def _sum_keys(keys, *, require_complete):
            total = 0.0
            for key in keys:
                c = cmap.get(key)
                if not c or c.status == "not_applicable":
                    continue
                if not c.is_known or c.amount is None:
                    if require_complete:
                        return None
                    continue
                total += float(c.amount)
            return round(total, 2)

        # Product landed NEVER includes ShipBlu, COD, or delivery shortfall
        product_landed = _sum_keys(list(PRODUCT_LANDED_KEYS), require_complete=False)
        landed = product_landed  # pricing base
        gross = _sum_keys(list(MANDATORY_KEYS), require_complete=False)
        notes.append(
            f"Gross mandatory audit stack (incl. ShipBlu/COD; excl. delivery revenue): {gross}"
        )
        notes.append(
            "Product landed excludes outbound carrier cost and customer delivery charge"
        )

        # Suggested product price from product landed only
        sale = self.policy.compute_suggested_sale_price(product_landed or 0.0)
        recommended = float(sale.get("suggested_price") or 0.0) or None
        charge = delivery_meta.get("customer_delivery_charge")
        order_total = None
        if recommended is not None and charge is not None:
            order_total = round(float(recommended) + float(charge), 2)

        return LandedCostResult(
            components=components,
            landed_cost=landed,
            landed_cost_incomplete=incomplete,
            completeness_percent=completeness,
            pricing_confidence_percent=conf_pct,
            pricing_confidence_label=conf_label,
            decision_code=decision,
            missing_keys=missing,
            estimate_keys=estimates,
            shipblu_breakdown=shipblu_bd,
            notes=notes,
            product_landed_cost=product_landed,
            customer_delivery_charge=delivery_meta.get("customer_delivery_charge"),
            estimated_carrier_cost=delivery_meta.get("estimated_carrier_cost"),
            delivery_specific_fees=delivery_meta.get("delivery_specific_fees"),
            delivery_margin=delivery_meta.get("delivery_margin"),
            delivery_subsidy=delivery_meta.get("delivery_subsidy"),
            delivery_profit_or_subsidy=delivery_meta.get("delivery_profit_or_subsidy"),
            delivery_shortfall=delivery_meta.get("delivery_shortfall"),
            proposed_delivery_charge=proposed_delivery_charge,
            delivery_gate_passed=delivery_gate_passed,
            delivery_review_required=not delivery_gate_passed,
            recommended_product_price=recommended,
            order_total=order_total,
            product_cost_completeness=product_comp,
            delivery_cost_completeness=delivery_comp,
            overall_completeness=overall,
            product_decision_code=product_decision,
            delivery_decision_code=delivery_decision,
            scenario=delivery_meta.get("scenario") or "",
            evidence_source=delivery_meta.get("evidence_source") or "",
        )
