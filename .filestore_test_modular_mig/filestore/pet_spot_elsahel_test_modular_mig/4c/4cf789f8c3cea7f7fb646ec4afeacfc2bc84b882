# Phase 2 Delivery — Gulf HR Payroll (Odoo)

**Date:** 2026-07-03  
**Module:** `gpc_gulf_hr_payroll_ext`  
**Database:** `trgulf_Mrp` (Odoo 19)  
**Parent WP:** [#135](https://master.tailcf9988.ts.net:10081/work_packages/135)

---

## Assumed client decisions (no reply on HR/Legacy)

See [`ASSUMED_CLIENT_DECISIONS_AR.md`](ASSUMED_CLIENT_DECISIONS_AR.md)

| # | Decision | Assumed answer |
|---|----------|----------------|
| 3 | Contract VAT | Before VAT |
| 5 | HR approach | Payslip Rules only |
| 6 | Legacy | Deferred |
| 7 | Scope | HR only |
| 8 | Test DB | trgulf_Mrp |

---

## Scope delivered

| WP | Feature | Status |
|----|---------|--------|
| [#139](https://master.tailcf9988.ts.net:10081/work_packages/139) | HR Payslip Rules | Done |
| [#145](https://master.tailcf9988.ts.net:10081/work_packages/145) | Legacy Payroll | Deferred |

Phase 1 ([#136–#138](https://master.tailcf9988.ts.net:10081/work_packages/150)) unchanged.

---

## Technical summary

### Module: `gpc_gulf_hr_payroll_ext`

Path: `/opt/localaddons/gpc_gulf_hr_payroll_ext/`

| Component | Description |
|-----------|-------------|
| Structure | `GULF_STANDARD` on `hr_payroll_community.structure_base` |
| Allowances | Travel + Other from contract |
| Inputs | OT_AMT, BONUS, DED_OTHER per payslip period |
| Template | `Gulf Payroll Template UAT` contract template |

### UAT (Odoo shell) — PASSED

| Item | Value |
|------|-------|
| Wage | 10,000 |
| Travel | 500 |
| Other | 200 |
| OT | 1,500 |
| Bonus | 1,000 |
| Deduction | 300 |
| **NET** | **12,900.00** |

Scripts: `scripts/seed_payroll_uat.py`, `scripts/uat_payroll_scenario.py`

### Screenshots

Path: `gpc_gulf_hr_payroll_ext/e2e/screenshots/gulf-phase2/`  
Index: `e2e/screenshots/gulf-phase2/README.md`

---

## WP #135 closure status

| Item | Status |
|------|--------|
| Odoo Community (1–4) | Complete |
| Legacy (#145) | Open — awaiting client screen/entry-type decision |
