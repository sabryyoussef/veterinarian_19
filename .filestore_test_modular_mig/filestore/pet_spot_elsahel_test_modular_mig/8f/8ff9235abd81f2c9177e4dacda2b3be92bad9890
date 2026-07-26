# OP#206 — ملاحظات الإصلاح (إعادة UAT لـ OP#86)

**الحالة:** مُسلَّم — جاهز لإعادة اختبار القبول  
**الفرع:** `feature/op206-uat-retest-op86`  
**حزمة العمل الأب:** OpenProject #87 / مرتبط بـ #86 / تذكرة UAT #206  
**التاريخ:** 2026-07-04  
**قاعدة الاختبار:** `sabry-test`

## ما تم إصلاحه

| # | ملاحظة الـ UAT | الإصلاح |
|---|----------------|---------|
| 1 | خيار Group By → Current Course غير موجود | تخزين `current_course_id` + فلتر تجميع **المقرر الحالي** |
| 2 | مسميات وربط (هوية / هاتف / تخصص / عنوان) | مسميات عربية + التحقق من الربط عند إنهاء التسجيل |
| 3 | Blood Group ما زال ظاهرًا | إخفاء من النموذج والقائمة والبحث |
| 4 | رقم التسجيل ونوع المصدر لا يُنقلان لملف المتدرب | حقول جديدة على `op.student` من التسجيل / القبول / الاستيراد |

## الوحدات

| الوحدة | الإصدار |
|--------|---------|
| `edafaa_student_profile` | 19.0.2.1.0 |
| `edafaa_student_profile_portal` | جسر الربط |
| `edafaa_batch_intake` | 19.0.2.1.0 |

## الترقية

```bash
cp -a custom_addons/edafaa_student_profile \
      custom_addons/edafaa_student_profile_portal \
      custom_addons/edafaa_batch_intake /opt/localaddons/

odoo -c /etc/odoo/odoo.conf -d <DATABASE> \
  -u edafaa_student_profile,edafaa_student_profile_portal,edafaa_batch_intake \
  --stop-after-init
```

ثم إعادة تحميل عمال Odoo.

## التحقق

- اختبارات الوحدة: **9/9** ناجحة  
- Playwright: **5/5** ناجحة  
- لقطات الشاشة: `delivery/screenshots/` (R1–R4)

## مرفقات هذه الحزمة

| المسار | المحتوى |
|--------|---------|
| `notes/FIX_NOTES_AR.md` | هذا الملف |
| `notes/FIX_NOTES.md` | ملاحظات بالإنجليزية |
| `notes/OP206_UAT_FIX_REPORT.md` | تقرير التنفيذ الكامل |
| `notes/PLAYWRIGHT_PROOF_EXPLAIN.md` | شرح إثبات Playwright |
| `notes/UAT_CHECKLIST.md` | قائمة إعادة الاختبار |
| `screenshots/r1_*.png` … `r4_*.png` | أدلة الواجهة |
