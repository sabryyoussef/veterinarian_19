# -*- coding: utf-8 -*-
"""Helpers for supplier multi-bill sell-through payment caps and reconciliation."""

from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero


def bill_payment_cap(bill):
    """Payable sell-through cap for one posted vendor bill."""
    residual = bill.amount_residual
    already = bill.amount_total - bill.amount_residual
    eligible = bill.vst_eligible_amount or 0.0
    remaining_elig = max(0.0, eligible - already)
    currency = bill.currency_id
    cap = min(residual, remaining_elig)
    return currency.round(max(0.0, cap)) if currency else max(0.0, cap)


def sort_bills_for_allocation(bills):
    """Oldest due date → oldest bill date → lowest id."""
    return bills.sorted(
        key=lambda b: (
            b.invoice_date_due or b.invoice_date or b.date,
            b.invoice_date or b.date,
            b.id,
        )
    )


def greedy_allocate(bills, total_amount):
    """Distribute total_amount across bills using caps in default order."""
    currency = bills[:1].currency_id if bills else None
    remaining = total_amount
    result = []
    for bill in sort_bills_for_allocation(bills):
        cap = bill_payment_cap(bill)
        if currency and float_is_zero(cap, precision_rounding=currency.rounding):
            take = 0.0
        else:
            take = min(cap, remaining)
            if currency:
                take = currency.round(take)
            remaining = (remaining - take) if not currency else currency.round(remaining - take)
        result.append((bill, take, cap))
    return result


def validate_bill_selection(bills):
    """Raise UserError if selection is not valid for combined payment."""
    if not bills:
        raise UserError("Select at least one Vendor Bill.")
    partners = bills.mapped("commercial_partner_id")
    if len(partners) != 1:
        raise UserError(
            "Mixed suppliers are not allowed. Conflicting partners: %s"
            % ", ".join(partners.mapped("display_name"))
        )
    companies = bills.mapped("company_id")
    if len(companies) != 1:
        raise UserError(
            "Mixed companies are not allowed. Conflicting companies: %s"
            % ", ".join(companies.mapped("name"))
        )
    currencies = bills.mapped("currency_id")
    if len(currencies) != 1:
        raise UserError(
            "Mixed currencies are not allowed. Conflicting currencies: %s"
            % ", ".join(currencies.mapped("name"))
        )
    bad_state = bills.filtered(lambda b: b.state != "posted" or b.move_type != "in_invoice")
    if bad_state:
        raise UserError(
            "Only posted Vendor Bills are allowed. Invalid: %s" % ", ".join(bad_state.mapped("name"))
        )
    paid = bills.filtered(lambda b: float_compare(b.amount_residual, 0.0, precision_rounding=b.currency_id.rounding) <= 0)
    if paid:
        raise UserError(
            "Fully paid bills cannot be included: %s" % ", ".join(paid.mapped("name"))
        )
    zero_elig = bills.filtered(lambda b: float_compare(bill_payment_cap(b), 0.0, precision_rounding=b.currency_id.rounding) <= 0)
    if zero_elig:
        raise UserError(
            "Bills with zero sell-through payment eligibility cannot be included: %s"
            % ", ".join(zero_elig.mapped("name"))
        )
    if len(bills.ids) != len(set(bills.ids)):
        raise UserError("A bill cannot appear twice in the selection.")
    return partners, companies, currencies


def create_grouped_payment(env, partner, company, currency, journal, payment_date, amount, memo, bills, allocations):
    """Create one supplier payment and reconcile exact amounts per bill.

    ``allocations`` is a list of (bill, amount) with amounts > 0.
    Uses account.payment + account.partial.reconcile (no raw SQL).
    """
    if float_compare(amount, sum(a for _b, a in allocations), precision_rounding=currency.rounding) != 0:
        raise UserError("Combined payment amount must equal the sum of per-bill allocations.")

    Payment = env["account.payment"]
    payment = Payment.create(
        {
            "payment_type": "outbound",
            "partner_type": "supplier",
            "partner_id": partner.id,
            "amount": amount,
            "currency_id": currency.id,
            "journal_id": journal.id,
            "date": payment_date,
            "memo": memo,
            "company_id": company.id,
        }
    )
    payment.action_post()
    _liquidity, counterpart_lines, _writeoff = payment._seek_for_lines()
    pay_line = counterpart_lines[:1]
    if not pay_line:
        raise UserError("Could not find payment counterpart line to reconcile.")

    Partial = env["account.partial.reconcile"]
    for bill, alloc in allocations:
        if float_is_zero(alloc, precision_rounding=currency.rounding):
            continue
        inv_lines = bill.line_ids.filtered(
            lambda l: l.account_id == pay_line.account_id
            and not l.reconciled
            and not currency.is_zero(l.amount_residual_currency)
        )
        if not inv_lines:
            inv_lines = bill.line_ids.filtered(
                lambda l: l.account_type == "liability_payable"
                and not l.reconciled
                and not currency.is_zero(l.amount_residual_currency)
            )
        if not inv_lines:
            raise UserError("No open payable line found on bill %s." % bill.name)
        inv_line = inv_lines.sorted(key=lambda l: abs(l.amount_residual_currency), reverse=True)[:1]

        # Cap to available residuals
        avail_inv = abs(inv_line.amount_residual_currency)
        avail_pay = abs(pay_line.amount_residual_currency)
        take = min(alloc, avail_inv, avail_pay)
        take = currency.round(take)
        if float_is_zero(take, precision_rounding=currency.rounding):
            raise UserError("Cannot reconcile allocation %.2f on bill %s (residual changed)." % (alloc, bill.name))
        if float_compare(take, alloc, precision_rounding=currency.rounding) != 0:
            raise UserError(
                "Eligibility/residual drift on bill %s: wanted %.2f, available %.2f. Refresh and retry."
                % (bill.name, alloc, take)
            )

        if inv_line.balance < 0 or inv_line.amount_residual_currency < 0:
            credit_move = inv_line
            debit_move = pay_line
        else:
            credit_move = pay_line
            debit_move = inv_line

        company_amount = abs(
            currency._convert(take, company.currency_id, company, payment_date)
            if currency != company.currency_id
            else take
        )
        Partial.create(
            {
                "amount": company_amount,
                "debit_amount_currency": take,
                "credit_amount_currency": take,
                "debit_move_id": debit_move.id,
                "credit_move_id": credit_move.id,
                "debit_currency_id": currency.id,
                "credit_currency_id": currency.id,
            }
        )
        bill.matched_payment_ids = [(4, payment.id)]
        # refresh pay_line residual for next iteration
        pay_line.invalidate_recordset(["amount_residual", "amount_residual_currency", "reconciled"])

    return payment
