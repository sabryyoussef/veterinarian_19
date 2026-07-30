# -*- coding: utf-8 -*-
"""True landed-cost engine for PetSpot Vetution fulfillment (shadow-safe).

Reuses petspot_shipblu_base.services.cost_engine.CostEngine for ShipBlu
estimates. Never invents unknown values. Never creates shipments/AWBs.
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
    formula: str = (
        "landed_cost = supplier_cost + supplier_shipping + shipblu_shipping "
        "+ cod_commission + payment_gateway_fee + packaging + tax "
        "+ return_risk + handling"
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
            "landed_cost_incomplete": self.landed_cost_incomplete,
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
        lines.append(f"--- Landed Cost: {total}")
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

        return self._finalize(components, shipblu_bd, notes)

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
            or "Vetution delivery charge / free-delivery threshold not verified",
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
                ship_comp = CostComponent(
                    "shipblu_shipping",
                    "ShipBlu Shipping",
                    round(shipping_total, 2),
                    "estimated",
                    source=f"CostEngine/{bd.pricing_source}",
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

    # ------------------------------------------------------------------ finalize
    def _finalize(self, components, shipblu_bd, notes):
        cmap = {c.key: c for c in components}
        missing = []
        estimates = []
        known_count = 0
        for key in MANDATORY_KEYS:
            c = cmap.get(key)
            if not c:
                missing.append(key)
                continue
            if c.status == "not_applicable":
                known_count += 1
                continue
            if c.is_known:
                known_count += 1
                if c.is_estimate or c.status == "estimated":
                    estimates.append(key)
            else:
                missing.append(key)

        completeness = round(100.0 * known_count / len(MANDATORY_KEYS), 2)
        incomplete = bool(missing) or any(
            cmap[k].status == "unknown" for k in MANDATORY_KEYS if k in cmap
        )

        # Confidence
        critical_missing = [k for k in missing if k in STATUS_CRITICAL_UNKNOWN]
        if critical_missing or completeness < 50:
            conf_pct, conf_label = 40.0, "Critical costs missing"
        elif len(estimates) >= 2:
            conf_pct, conf_label = 60.0, "Multiple estimates"
        elif len(estimates) == 1:
            conf_pct, conf_label = 80.0, "One estimate"
        elif completeness >= 100 and not estimates:
            conf_pct, conf_label = 100.0, "Verified"
        else:
            conf_pct, conf_label = 80.0, "One estimate" if estimates else "Partial verified"

        # Decision matrix (still shadow — callers enforce allow_auto_quotation=False)
        if completeness >= 100 and conf_pct >= 100 and not incomplete:
            decision = "READY_FOR_AUTO_QUOTE"
        elif completeness >= 90:
            decision = "READY_FOR_MANUAL_REVIEW"
        elif completeness >= 75:
            decision = "SHADOW_ONLY"
        elif completeness >= 50:
            decision = "BLOCK_PRICE_PUBLISH"
        else:
            decision = "INSUFFICIENT_COST_DATA"

        landed = None
        if not incomplete:
            landed = round(sum(float(c.amount or 0.0) for c in components if c.status != "not_applicable"), 2)
        else:
            # Partial sum of known only for worksheet display — marked incomplete
            landed = round(
                sum(float(c.amount or 0.0) for c in components if c.is_known and c.status != "not_applicable"),
                2,
            )

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
        )
