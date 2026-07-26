# Phase 1 Delivery — Gulf Industrial Projects (Odoo)

**Date:** 2026-07-03  
**Module:** `gpc_gulf_project_ext`  
**Database:** `trgulf_Mrp` (Odoo 19)  
**Parent WP:** [#135](https://master.tailcf9988.ts.net:10081/work_packages/135)

---

## Scope delivered (client-approved)

| WP | Feature | Status |
|----|---------|--------|
| [#136](https://master.tailcf9988.ts.net:10081/work_packages/136) | Project Description on Dashboard | Done |
| [#137](https://master.tailcf9988.ts.net:10081/work_packages/137) | Contract Amount (`contract_amount`) | Done |
| [#138](https://master.tailcf9988.ts.net:10081/work_packages/138) | Quotation dimensions + Area pricing + PDF | Done |

**Out of scope:** WP #139 / #145 (HR / Legacy) — awaiting client.

---

## Technical summary

### Module: `gpc_gulf_project_ext`

Path: `/opt/localaddons/gpc_gulf_project_ext/`

| Area | Implementation |
|------|----------------|
| WP #136 | `get_panel_data()` + OWL patch on `ProjectRightSidePanel` — shows HTML description |
| WP #137 | `contract_amount` Monetary on `project.project`; bidirectional sync with `project_valuebvat` |
| WP #138 | `length_cm`, `width_cm`, `area_sqm` on `sale.order.line`; tax base uses `Area × Qty × Price`; invoice + PDF |

### UAT (Odoo shell)

Script: `scripts/uat_scenario.py` — **PASSED**

Client scenario: 180×305 → 5.49 m² × 24 × 490 = **64,562.40** (quotation + invoice)

### Playwright E2E + screenshots

Path: `e2e/screenshots/gulf-phase1/`  
Index: `e2e/screenshots/gulf-phase1/README.md`

---

## Screenshot index

| # | File | What we did | WP |
|---|------|-------------|-----|
| 01 | login-page | Open login | — |
| 02 | after-login | Authenticate | — |
| 03 | project-form | Open UAT project | #136 #137 |
| 04 | expected-budget | Contract Amount **591,706.80 SR** | #137 |
| 05 | description-tab | Rich-text description | #136 |
| 06 | project-dashboard | Dashboard navigation | #136 |
| 08 | quotation-dimensions | Length/Width/Area + **64,562.40** | #138 |
| 09 | order-lines | Line table crop | #138 |
| 10 | print-dialog | Print report | #138 |
| 11 | final-quotation | Final totals | #138 |

---

## Local documentation

| File | Purpose |
|------|---------|
| `openproject_docs/REQUIREMENTS_REVIEW_CLIENT_ANSWERS_AR.md` | Client specs |
| `openproject_docs/REQUIREMENTS_REVIEW_DECISIONS_CHECKLIST.md` | Decision tracker |
| `gpc_gulf_project_ext/e2e/README.md` | Playwright run guide |
| `gpc_gulf_project_ext/e2e/screenshots/gulf-phase1/INDEX_AR.md` | Arabic index |

---

## Pending (non-blocking)

- VAT treatment for `contract_amount` — confirm on WP #140
- Dashboard **Project Details** panel may require Odoo restart for web assets
- HR / Legacy (WP #139, #145) — awaiting client
