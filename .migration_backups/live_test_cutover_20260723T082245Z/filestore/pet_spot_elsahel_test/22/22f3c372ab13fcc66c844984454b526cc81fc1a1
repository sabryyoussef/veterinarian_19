# Developer Guide — Gulf Industrial Projects (WP #135)

**Odoo:** 19 · **DB:** `trgulf_Mrp` · **Date:** 2026-07-03

---

## 1. Modules

### 1.1 `gpc_gulf_project_ext`

**Path:** `/opt/localaddons/gpc_gulf_project_ext/`

**Depends:** `project`, `sale_management`, `account`, `itech_construction_project`, `order_line_sequences`, `retention_performance_bond`

| WP | Feature | Implementation |
|----|---------|----------------|
| #136 | Project description on Dashboard | `project.project.get_panel_data()` + OWL patch `ProjectRightSidePanel` |
| #137 | Contract amount | Field `contract_amount` (Monetary); bidirectional sync with `project_valuebvat` |
| #138 | Quotation dimensions | `length_cm`, `width_cm`, `area_sqm` on `sale.order.line`; `_compute_amount` uses `Area × Qty × Price` |

**Key files:**

```
models/project_project.py      # contract_amount + get_panel_data()
models/sale_order_line.py      # dimensions + amount override
models/account_move_line.py    # invoice propagation
views/project_project_views.xml
views/sale_order_views.xml
report/report_saleorder.xml
static/src/components/project_right_side_panel/
scripts/uat_scenario.py
tests/test_gpc_gulf_project_ext.py
```

**Install:**

```bash
sudo -u odoo odoo -c /etc/odoo/odoo.conf -d trgulf_Mrp -i gpc_gulf_project_ext --stop-after-init
sudo systemctl restart odoo
```

**UAT:**

```bash
sudo -u odoo odoo shell -c /etc/odoo/odoo.conf -d trgulf_Mrp --no-http \
  < /opt/localaddons/gpc_gulf_project_ext/scripts/uat_scenario.py
```

Expected: line/total **64,562.40** (180×305 → 5.49 × 24 × 490).

---

### 1.2 `gpc_gulf_hr_payroll_ext`

**Path:** `/opt/localaddons/gpc_gulf_hr_payroll_ext/`

**Depends:** `hr_payroll_community`

Data-only module — payroll structure **GULF_STANDARD** with rules:

| Code | Category | Source |
|------|----------|--------|
| GULF_TRAVEL | ALW | `contract.travel_allowance` |
| GULF_OTHER_ALW | ALW | `contract.other_allowance` |
| GULF_OT | ALW | Payslip input `OT_AMT` |
| GULF_BONUS | ALW | Payslip input `BONUS` |
| GULF_DED | DED | Payslip input `DED_OTHER` |

**Install:**

```bash
sudo -u odoo odoo -c /etc/odoo/odoo.conf -d trgulf_Mrp \
  -i hr_payroll_community,gpc_gulf_hr_payroll_ext --stop-after-init
```

**UAT:**

```bash
sudo -u odoo odoo shell -c /etc/odoo/odoo.conf -d trgulf_Mrp --no-http \
  < /opt/localaddons/gpc_gulf_hr_payroll_ext/scripts/seed_payroll_uat.py
sudo -u odoo odoo shell -c /etc/odoo/odoo.conf -d trgulf_Mrp --no-http \
  < /opt/localaddons/gpc_gulf_hr_payroll_ext/scripts/uat_payroll_scenario.py
```

Expected NET: **12,900.00** (10,000 + 500 + 200 + 1,500 + 1,000 − 300).

---

## 2. Architecture notes

### Quotation pricing (#138)

```
area_sqm = (length_cm × width_cm) / 10_000
line_subtotal = area_sqm × product_uom_qty × price_unit × (1 - discount/100)
```

Fallback: if length/width empty → `area_sqm = 1` → standard qty × price.

### Contract amount sync (#137)

Writing `contract_amount` updates `project_valuebvat` and vice versa (before VAT).

### Dashboard OWL (#136)

Assets in `web.assets_backend`. After install/upgrade, **restart Odoo** to load JS for the right-side Project Details panel.

---

## 3. E2E / Playwright

**Phase 1:**

```bash
cd /opt/localaddons/gpc_gulf_project_ext/e2e
export GPC_GULF_ODOO_URL=http://127.0.0.1:8069
npm run test:screenshots
```

**Phase 2 HR:**

```bash
cd /opt/localaddons/gpc_gulf_hr_payroll_ext/e2e
npm run test:screenshots
```

---

## 4. Legacy (#145)

**No changes.** Client decision: no expansion on `legacy_mixed_system` / `trgcc`.

---

## 5. OpenProject sync scripts

| Script | Purpose |
|--------|---------|
| `sync_gulf_final_delivery_wp135.py` | Final delivery WP + attachments + Nextcloud |
| `sync_close_wp135_complete.py` | Close WP family |
| `ssh_to_master_and_sync.sh` | Run sync on master via SSH |

---

## 6. Decisions (final)

| # | Decision | Value |
|---|----------|-------|
| 3 | VAT | Before VAT |
| 5 | HR | Payslip Rules only |
| 6 | Legacy | No expansion |
| 8 | Test DB | `trgulf_Mrp` |

See `openproject_docs/WP135_FINAL_CLOSURE.md`.
