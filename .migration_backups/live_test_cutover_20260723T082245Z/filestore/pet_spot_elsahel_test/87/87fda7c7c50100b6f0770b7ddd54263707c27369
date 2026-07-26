# OP#206 — UAT Retest Fixes for OP#86

**Date:** 2026-07-04  
**Branch:** `feature/op206-uat-retest-op86`  
**Parent:** OpenProject #206 (related #86 / parent #87)  
**Database:** `sabry-test`  
**Status:** Ready for UAT retest

## Summary

Correction pass for four UAT findings that remained after OP#86 delivery.

| # | Finding | Fix |
|---|---------|-----|
| 1 | Group By → Current Course missing | `current_course_id` stored; search filter `group_current_course` |
| 2 | Labels / mapping (ID, phone, specialization, address) | Arabic labels on student + registration forms; mapping verified |
| 3 | Blood Group still visible | Hidden on form, list, and search |
| 4 | Registration Number / Source Type not on Student Profile | New fields on `op.student`; mapped from registration, admission, batch |

## Modules

| Module | Version |
|--------|---------|
| `edafaa_student_profile` | 19.0.2.1.0 |
| `edafaa_student_profile_portal` | (bridge mapping) |
| `edafaa_batch_intake` | 19.0.2.1.0 |

## Field labels (Arabic)

| Client field | Canonical | Label |
|--------------|-----------|-------|
| رقم الهوية | `op.student.id_number` | رقم الهوية |
| رقم الهاتف | partner `phone` | رقم الهاتف |
| التخصص | `specialization_id` | التخصص |
| العنوان | `street` / `city` / `country_id` | الشارع / المدينة / الدولة |
| رقم التسجيل | `registration_number` | رقم التسجيل |
| نوع المصدر | `source_type` | نوع المصدر |
| المقرر الحالي | `current_course_id` | المقرر الحالي |

## Source type values

Same as admission:

- `manual` — Manual Entry
- `student_registration` — Student Registration Portal
- `batch_intake` — Batch Intake
- `contact_pool` — Contact Pool Manager

## Write paths

- **Student Registration finalize** → `registration_number=name`, `source_type=student_registration`
- **Batch intake process** → `source_type=batch_intake`
- **Admission enroll** (`get_student_vals`) → copies `source_type` and registration number when linked

## Upgrade

```bash
cp -a custom_addons/edafaa_student_profile custom_addons/edafaa_student_profile_portal \
  custom_addons/edafaa_batch_intake /opt/localaddons/

odoo -c /etc/odoo/odoo.conf -d sabry-test \
  -u edafaa_student_profile,edafaa_student_profile_portal,edafaa_batch_intake \
  --stop-after-init --http-port=8079
```

Reload Odoo workers after upgrade.

## Tests

```bash
odoo -c /etc/odoo/odoo.conf -d sabry-test \
  -u edafaa_student_profile \
  --test-enable --stop-after-init \
  --test-tags=/edafaa_student_profile \
  --http-port=8079
```

**Result (2026-07-04):** 9 tests, 0 failed, 0 errors (includes OP#86 + OP#206 cases).

### Playwright (UI proof)

```bash
cd tests/playwright/op206
ODOO_PASSWORD=admin OP206_PROOF_STUDENT_ID=181 OP206_REGISTRATION_ID=12 npm test
```

**Result:** 5/5 passed. Explanation: [`PLAYWRIGHT_PROOF_EXPLAIN.md`](PLAYWRIGHT_PROOF_EXPLAIN.md). Screenshots: [`evidence/screenshots/`](evidence/screenshots/).

## UAT checklist (retest)

- [ ] Students list → Group By → **المقرر الحالي** / Current Course works
- [ ] Trainee form shows Arabic labels for رقم الهوية، رقم الهاتف، التخصص، الشارع/المدينة/الدولة
- [ ] Blood Group not visible on form or list
- [ ] Finalize Student Registration → Student Profile has رقم التسجيل and نوع المصدر = Student Registration Portal
- [ ] Values match registration source for ID, phone, address, specialization
