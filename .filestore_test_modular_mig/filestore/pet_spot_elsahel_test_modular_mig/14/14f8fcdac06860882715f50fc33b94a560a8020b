# Gulf Phase 2 — HR Payroll Screenshots Index

**Module:** `gpc_gulf_hr_payroll_ext`  
**Database:** `trgulf_Mrp`  
**WP:** #139  
**Date:** 2026-07-03

---

## 01-after-login.png

Logged in to Odoo for payroll UAT.

---

## 02-payroll-structure-gulf-standard.png

**Gulf Standard Payroll** structure (`GULF`) with OT, bonus, and deduction rules.

---

## 03-employee-uat.png

UAT employee **GPC Gulf Payroll UAT Employee** with Gulf payroll contract.

---

## 04-payslips-list.png

Payslips linked to UAT employee.

---

## 05-payslip-form.png

Payslip with computed lines (BASIC, allowances, OT, bonus, deduction).

---

## 06-payslip-net-12900.png

**NET = 12,900.00** — UAT scenario: 10,000 + 500 + 200 + 1,500 + 1,000 - 300

---

## Re-run

```bash
sudo -u odoo odoo shell -c /etc/odoo/odoo.conf -d trgulf_Mrp --no-http \
  < /opt/localaddons/gpc_gulf_hr_payroll_ext/scripts/seed_payroll_uat.py
sudo -u odoo odoo shell -c /etc/odoo/odoo.conf -d trgulf_Mrp --no-http \
  < /opt/localaddons/gpc_gulf_hr_payroll_ext/scripts/uat_payroll_scenario.py

cd /opt/localaddons/gpc_gulf_hr_payroll_ext/e2e
export GPC_GULF_ODOO_URL=http://127.0.0.1:8069
npm run test:screenshots
```
