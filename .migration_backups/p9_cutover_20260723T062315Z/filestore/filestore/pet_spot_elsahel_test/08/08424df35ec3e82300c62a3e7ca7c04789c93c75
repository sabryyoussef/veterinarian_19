# User Guide — Gulf Industrial Projects Customizations

**Odoo 19** · Database: **trgulf_Mrp**

---

## 1. Project — Description on Dashboard

1. Open **Project** → select your project.
2. Go to tab **Description** and enter formatted text (paragraphs, lists).
3. Click **Dashboard** on the project.
4. The right **Project Details** panel shows the same description automatically.

---

## 2. Project — Contract Amount

1. Open the project → tab **Expected Budget** (or project form).
2. Field **Contract Amount / مبلغ التعاقد** — enter the value in company currency.
3. The amount is **before VAT** and stays in sync with **Total Amount before VAT**.
4. Contract amount also appears on the Project Dashboard panel (when web assets are loaded).

**Example:** `591,706.80 SR`

---

## 3. Quotation — Dimensions and Area Pricing

### On quotation / sales order lines

Enable columns if hidden: **Length**, **Width/Height**, **Area**.

| Field | Unit | Notes |
|-------|------|-------|
| Length | CM | e.g. 180 |
| Width/Height | CM | e.g. 305 |
| Area | M² | Auto: (Length × Width) ÷ 10,000 |

### Line total

```
Total = Area × Quantity × Unit Price
```

**Example:** 5.49 × 24 × 490 = **64,562.40 SR**

If you do not use dimensions, Area = 1 and pricing works as normal Quantity × Price.

### PDF

Print the quotation — the PDF includes Length, Width/Height, Area columns.

---

## 4. HR — Payroll (Payslip Rules)

1. Install app **Payroll** (`hr_payroll_community`) if not already installed.
2. Assign salary structure **Gulf Standard Payroll** to employee contracts.
3. On each payslip, use **Other Inputs** for:
   - **Overtime Amount** (OT_AMT)
   - **Bonus / Increase** (BONUS)
   - **Other Deduction** (DED_OTHER)
4. Contract fields **Travel Allowance** and **Other Allowance** apply automatically each period.

---

## 5. Legacy Payroll

**No changes** in this delivery. Continue using existing Legacy Payroll on `trgcc` as before.

---

## 6. Support references

- OpenProject: [WP #135](https://master.tailcf9988.ts.net:10081/work_packages/135)
- Phase 1 delivery: [WP #150](https://master.tailcf9988.ts.net:10081/work_packages/150)
- Phase 2 HR delivery: [WP #156](https://master.tailcf9988.ts.net:10081/work_packages/156)
