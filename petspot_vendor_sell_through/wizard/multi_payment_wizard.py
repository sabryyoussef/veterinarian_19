# -*- coding: utf-8 -*-
import json
from uuid import uuid4

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare, float_is_zero

from odoo.addons.petspot_vendor_sell_through.services.multi_payment import (
    bill_payment_cap,
    create_grouped_payment,
    sort_bills_for_allocation,
    validate_bill_selection,
)


class PetspotVendorSellThroughMultiPaymentWizard(models.TransientModel):
    _name = "petspot.vendor.sell.through.multi.payment.wizard"
    _description = "Register Combined Sell-Through Payment"

    partner_id = fields.Many2one("res.partner", required=True, readonly=True)
    company_id = fields.Many2one("res.company", required=True, readonly=True)
    currency_id = fields.Many2one("res.currency", required=True, readonly=True)
    payment_date = fields.Date(required=True, default=fields.Date.context_today)
    journal_id = fields.Many2one(
        "account.journal",
        required=True,
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
    )
    payment_method_line_id = fields.Many2one(
        "account.payment.method.line",
        string="Payment Method",
        domain="[('id', 'in', available_payment_method_line_ids)]",
    )
    available_payment_method_line_ids = fields.Many2many(
        "account.payment.method.line",
        compute="_compute_available_payment_methods",
    )
    memo = fields.Char(string="Memo/reference")
    line_ids = fields.One2many(
        "petspot.vendor.sell.through.multi.payment.wizard.line",
        "wizard_id",
        string="Selected bill lines",
    )
    combined_amount = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_combined_amount",
        store=True,
        readonly=False,
    )
    warning_html = fields.Html(compute="_compute_warnings")
    snapshot_json = fields.Text(readonly=True)
    idempotency_key = fields.Char(readonly=True)
    confirm_post = fields.Boolean(
        string="Post payment now (TEST automation only)",
        default=False,
        help="Manual UAT must leave unchecked. Automated tests may enable inside rollback transactions.",
    )

    @api.depends("journal_id")
    def _compute_available_payment_methods(self):
        for wiz in self:
            methods = self.env["account.payment.method.line"]
            if wiz.journal_id:
                methods = wiz.journal_id._get_available_payment_method_lines("outbound")
            wiz.available_payment_method_line_ids = methods

    @api.depends("line_ids.allocation_amount")
    def _compute_combined_amount(self):
        for wiz in self:
            wiz.combined_amount = sum(wiz.line_ids.mapped("allocation_amount"))

    @api.depends("line_ids", "line_ids.allocation_amount", "line_ids.payment_cap", "line_ids.residual")
    def _compute_warnings(self):
        for wiz in self:
            msgs = []
            for line in wiz.line_ids:
                if float_compare(line.allocation_amount, line.payment_cap, precision_rounding=wiz.currency_id.rounding) > 0:
                    msgs.append("Allocation on %s exceeds sell-through cap." % line.move_id.name)
                if float_compare(line.allocation_amount, line.residual, precision_rounding=wiz.currency_id.rounding) > 0:
                    msgs.append("Allocation on %s exceeds residual." % line.move_id.name)
                if line.blocking_warning:
                    msgs.append("%s: %s" % (line.move_id.name, line.blocking_warning))
            wiz.warning_html = "<br/>".join(msgs) if msgs else False

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self.env.context.get("active_ids") or []
        bills = self.env["account.move"].browse(active_ids).exists()
        if not bills:
            return res
        partners, companies, currencies = validate_bill_selection(bills)
        bills = sort_bills_for_allocation(bills)
        journal = self.env["account.journal"].search(
            [
                ("type", "in", ("bank", "cash")),
                ("company_id", "=", companies.id),
            ],
            limit=1,
        )
        lines = []
        snapshot = []
        for bill in bills:
            cap = bill_payment_cap(bill)
            already = bill.amount_total - bill.amount_residual
            snapshot.append(
                {
                    "id": bill.id,
                    "name": bill.name,
                    "residual": bill.amount_residual,
                    "eligible": bill.vst_eligible_amount,
                    "already_paid": already,
                    "cap": cap,
                    "write_date": str(bill.write_date),
                    "vst_last_recalculation": str(bill.vst_last_recalculation),
                }
            )
            lines.append(
                (
                    0,
                    0,
                    {
                        "move_id": bill.id,
                        "bill_date": bill.invoice_date,
                        "due_date": bill.invoice_date_due,
                        "bill_total": bill.amount_total,
                        "residual": bill.amount_residual,
                        "eligible_amount": bill.vst_eligible_amount,
                        "already_paid": already,
                        "payment_cap": cap,
                        "allocation_amount": cap,
                        "confidence": bill.vst_allocation_confidence,
                        "blocking_warning": bill.vst_blocking_warning,
                    },
                )
            )
        res.update(
            {
                "partner_id": partners.id,
                "company_id": companies.id,
                "currency_id": currencies.id,
                "journal_id": journal.id if journal else False,
                "line_ids": lines,
                "snapshot_json": json.dumps(snapshot),
                "idempotency_key": "VST-MULTI-%s" % uuid4().hex,
                "memo": "VST combined sell-through %s" % fields.Date.context_today(self),
            }
        )
        return res

    def action_refresh_caps(self):
        """Re-read caps after drift; does not post payment."""
        self.ensure_one()
        for line in self.line_ids:
            bill = line.move_id
            cap = bill_payment_cap(bill)
            line.write(
                {
                    "residual": bill.amount_residual,
                    "eligible_amount": bill.vst_eligible_amount,
                    "already_paid": bill.amount_total - bill.amount_residual,
                    "payment_cap": cap,
                    "allocation_amount": min(line.allocation_amount, cap, bill.amount_residual),
                    "confidence": bill.vst_allocation_confidence,
                    "blocking_warning": bill.vst_blocking_warning,
                }
            )
        snap = []
        for line in self.line_ids:
            bill = line.move_id
            snap.append(
                {
                    "id": bill.id,
                    "name": bill.name,
                    "residual": bill.amount_residual,
                    "eligible": bill.vst_eligible_amount,
                    "already_paid": bill.amount_total - bill.amount_residual,
                    "cap": bill_payment_cap(bill),
                    "write_date": str(bill.write_date),
                    "vst_last_recalculation": str(bill.vst_last_recalculation),
                }
            )
        self.snapshot_json = json.dumps(snap)
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def _check_access_payment(self):
        if not self.env.user.has_group("petspot_vendor_sell_through.group_vst_payment_manager"):
            raise AccessError("Only Accounting payment managers may use combined sell-through payment.")

    def _validate_lines(self):
        self.ensure_one()
        bills = self.line_ids.mapped("move_id")
        validate_bill_selection(bills)
        currency = self.currency_id
        total = 0.0
        for line in self.line_ids:
            if float_compare(line.allocation_amount, 0.0, precision_rounding=currency.rounding) < 0:
                raise UserError("Allocation amounts must be ≥ 0.")
            if float_compare(line.allocation_amount, line.residual, precision_rounding=currency.rounding) > 0:
                raise UserError("Allocation on %s exceeds residual." % line.move_id.name)
            if float_compare(line.allocation_amount, line.payment_cap, precision_rounding=currency.rounding) > 0:
                raise UserError("Allocation on %s exceeds sell-through eligibility." % line.move_id.name)
            total += line.allocation_amount
        if float_compare(total, self.combined_amount, precision_rounding=currency.rounding) != 0:
            raise UserError("Combined payment must equal the sum of per-bill allocations.")
        if float_is_zero(total, precision_rounding=currency.rounding):
            raise UserError("Combined payment amount must be positive.")
        if not self.journal_id:
            raise UserError("Select a payment journal.")

    def _detect_drift(self):
        """Compare live caps/residuals to wizard snapshot; return True if drifted."""
        self.ensure_one()
        snap = {row["id"]: row for row in json.loads(self.snapshot_json or "[]")}
        for line in self.line_ids:
            bill = line.move_id
            live_cap = bill_payment_cap(bill)
            row = snap.get(bill.id)
            if not row:
                return True
            if float_compare(bill.amount_residual, row["residual"], precision_rounding=self.currency_id.rounding) != 0:
                return True
            if float_compare(live_cap, row["cap"], precision_rounding=self.currency_id.rounding) != 0:
                return True
            if float_compare(line.allocation_amount, live_cap, precision_rounding=self.currency_id.rounding) > 0:
                return True
            if str(bill.write_date) != row.get("write_date"):
                # bill accounting write can change residual; treat as drift if residual/cap already caught
                pass
        return False

    def action_confirm(self):
        """Review-only by default; posts only when confirm_post is enabled (tests)."""
        self.ensure_one()
        self._check_access_payment()
        self._validate_lines()
        if self._detect_drift():
            self.env["petspot.vendor.sell.through.multi.payment.log"].sudo().create(
                {
                    "name": "DRIFT %s" % self.idempotency_key,
                    "partner_id": self.partner_id.id,
                    "company_id": self.company_id.id,
                    "currency_id": self.currency_id.id,
                    "bill_ids": [(6, 0, self.line_ids.mapped("move_id").ids)],
                    "eligibility_snapshot": self.snapshot_json,
                    "allocation_snapshot": json.dumps(
                        [{"bill": l.move_id.name, "amount": l.allocation_amount} for l in self.line_ids]
                    ),
                    "payment_amount": self.combined_amount,
                    "drift_rejected": True,
                    "idempotency_key": "%s-drift-%s" % (self.idempotency_key, uuid4().hex[:8]),
                    "reconciliation_result": "rejected_drift",
                }
            )
            raise UserError(
                "Sell-through eligibility or bill residual changed since the wizard opened. "
                "Click Refresh caps and review again."
            )

        if not self.confirm_post:
            # Open standard payment register prefilled for review (does not auto-post)
            ctx = {
                "active_model": "account.move",
                "active_ids": self.line_ids.mapped("move_id").ids,
                "active_id": self.line_ids[:1].move_id.id,
                "default_amount": self.combined_amount,
                "default_group_payment": True,
                "default_journal_id": self.journal_id.id,
                "default_payment_date": self.payment_date,
                "default_communication": self.memo,
            }
            return {
                "type": "ir.actions.act_window",
                "name": "Register Payment (review)",
                "res_model": "account.payment.register",
                "view_mode": "form",
                "target": "new",
                "context": ctx,
            }

        # Idempotency guard
        Log = self.env["petspot.vendor.sell.through.multi.payment.log"].sudo()
        if Log.search_count([("idempotency_key", "=", self.idempotency_key)]):
            raise UserError("This combined payment was already confirmed (idempotency guard).")

        # Lock payable lines
        bills = self.line_ids.mapped("move_id")
        payables = bills.line_ids.filtered(lambda l: l.account_type == "liability_payable")
        if payables:
            payables.lock_for_update()

        # Re-validate caps after lock
        for line in self.line_ids:
            live_cap = bill_payment_cap(line.move_id)
            if float_compare(line.allocation_amount, live_cap, precision_rounding=self.currency_id.rounding) > 0:
                raise UserError("Drift on %s after lock. Refresh and retry." % line.move_id.name)

        allocations = [
            (line.move_id, line.allocation_amount)
            for line in self.line_ids
            if not float_is_zero(line.allocation_amount, precision_rounding=self.currency_id.rounding)
        ]
        payment = create_grouped_payment(
            self.env,
            self.partner_id,
            self.company_id,
            self.currency_id,
            self.journal_id,
            self.payment_date,
            self.combined_amount,
            self.memo or self.idempotency_key,
            bills,
            allocations,
        )
        if self.payment_method_line_id and "payment_method_line_id" in payment._fields:
            payment.payment_method_line_id = self.payment_method_line_id

        Log.create(
            {
                "name": self.idempotency_key,
                "partner_id": self.partner_id.id,
                "company_id": self.company_id.id,
                "currency_id": self.currency_id.id,
                "bill_ids": [(6, 0, bills.ids)],
                "eligibility_snapshot": self.snapshot_json,
                "allocation_snapshot": json.dumps(
                    [{"bill_id": b.id, "bill": b.name, "amount": a} for b, a in allocations]
                ),
                "payment_amount": self.combined_amount,
                "payment_id": payment.id,
                "reconciliation_result": "posted:%s" % payment.name,
                "drift_rejected": False,
                "idempotency_key": self.idempotency_key,
            }
        )
        return {
            "type": "ir.actions.act_window",
            "name": "Payment",
            "res_model": "account.payment",
            "res_id": payment.id,
            "view_mode": "form",
            "target": "current",
        }


class PetspotVendorSellThroughMultiPaymentWizardLine(models.TransientModel):
    _name = "petspot.vendor.sell.through.multi.payment.wizard.line"
    _description = "Combined Sell-Through Payment Line"
    _order = "due_date asc, bill_date asc, move_id asc"

    wizard_id = fields.Many2one("petspot.vendor.sell.through.multi.payment.wizard", required=True, ondelete="cascade")
    move_id = fields.Many2one("account.move", string="Vendor Bill", required=True, readonly=True)
    bill_date = fields.Date(readonly=True)
    due_date = fields.Date(readonly=True)
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    bill_total = fields.Monetary(currency_field="currency_id", readonly=True)
    residual = fields.Monetary(currency_field="currency_id", readonly=True)
    eligible_amount = fields.Monetary(currency_field="currency_id", readonly=True)
    already_paid = fields.Monetary(currency_field="currency_id", readonly=True)
    payment_cap = fields.Monetary(currency_field="currency_id", readonly=True)
    allocation_amount = fields.Monetary(currency_field="currency_id")
    residual_after = fields.Monetary(currency_field="currency_id", compute="_compute_residual_after")
    confidence = fields.Char(readonly=True)
    blocking_warning = fields.Char(readonly=True)

    @api.depends("residual", "allocation_amount")
    def _compute_residual_after(self):
        for line in self:
            line.residual_after = (line.residual or 0.0) - (line.allocation_amount or 0.0)
