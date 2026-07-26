# دليل المستخدم — تخصيصات مشاريع الخليج الصناعى

**Odoo 19** · قاعدة البيانات: **trgulf_Mrp**

---

## 1. المشروع — الوصف في Dashboard

1. افتح **Project** → اختر المشروع.
2. من تبويب **Description** اكتب الوصف (فقرات، قوائم).
3. اضغط **Dashboard** من المشروع.
4. يظهر الوصف في لوحة **Project Details** على اليمين تلقائياً.

---

## 2. المشروع — مبلغ التعاقد

1. افتح المشروع → تبويب **Expected Budget**.
2. حقل **Contract Amount / مبلغ التعاقد** — أدخل القيمة بعملة الشركة.
3. المبلغ **قبل ضريبة القيمة المضافة** ويتزامن مع **Total Amount before VAT**.
4. يظهر أيضاً في Dashboard (بعد تحميل واجهة الويب).

**مثال:** `591,706.80 SR`

---

## 3. عرض السعر — المقاسات والتسعير بالمساحة

### على بنود عرض السعر

فعّل الأعمدة: **Length**، **Width/Height**، **Area**.

| الحقل | الوحدة | مثال |
|-------|--------|------|
| Length | CM | 180 |
| Width/Height | CM | 305 |
| Area | M² | 5.49 (محسوب) |

### إجمالي السطر

```
الإجمالي = Area × Quantity × Unit Price
```

**مثال:** 5.49 × 24 × 490 = **64,562.40 SR**

بدون مقاسات → Area = 1 → يعمل كالكمية × السعر العادي.

### PDF

من **Print** — التقرير يعرض Length و Width/Height و Area.

---

## 4. HR — مسير الرواتب

1. تطبيق **Payroll** مثبت.
2. على عقد الموظف: هيكل **Gulf Standard Payroll**.
3. على كل Payslip — **Other Inputs**:
   - **Overtime Amount** (إضافي)
   - **Bonus / Increase** (زيادة/مكافأة)
   - **Other Deduction** (خصم)
4. **Travel Allowance** و **Other Allowance** من العقد تُطبَّق تلقائياً.

---

## 5. Legacy Payroll

**بدون تغيير** في هذا التسليم. استمر على نظام Legacy الحالي (`trgcc`).

---

## 6. مراجع

- [WP #135](https://master.tailcf9988.ts.net:10081/work_packages/135)
- [WP #150](https://master.tailcf9988.ts.net:10081/work_packages/150) — Phase 1
- [WP #156](https://master.tailcf9988.ts.net:10081/work_packages/156) — Phase 2 HR
