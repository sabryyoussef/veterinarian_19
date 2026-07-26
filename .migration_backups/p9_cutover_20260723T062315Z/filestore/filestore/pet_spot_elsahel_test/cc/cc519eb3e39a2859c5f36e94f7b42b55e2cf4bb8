# OP#206 — Fix Notes (UAT Retest OP#86)

**Status:** Delivered — ready for UAT retest  
**Branch:** `feature/op206-uat-retest-op86`  
**Parent WP:** OpenProject #87 (`edafa_kafaat_parent`) / related #86 / UAT ticket #206  
**Date:** 2026-07-04  
**DB validated:** `sabry-test`

## What was fixed

| # | UAT finding | Fix |
|---|-------------|-----|
| 1 | Group By → Current Course missing | `current_course_id` stored; search filter **المقرر الحالي** |
| 2 | Labels / mapping (ID, phone, specialization, address) | Arabic labels; mapping verified on registration finalize |
| 3 | Blood Group still visible | Hidden on form, list, and search |
| 4 | Registration Number / Source Type not on Student Profile | New fields on `op.student`; set from registration / admission / batch |

## Modules

| Module | Version |
|--------|---------|
| `edafaa_student_profile` | 19.0.2.1.0 |
| `edafaa_student_profile_portal` | bridge mapping |
| `edafaa_batch_intake` | 19.0.2.1.0 |

## Upgrade

```bash
cp -a custom_addons/edafaa_student_profile \
      custom_addons/edafaa_student_profile_portal \
      custom_addons/edafaa_batch_intake /opt/localaddons/

odoo -c /etc/odoo/odoo.conf -d <DATABASE> \
  -u edafaa_student_profile,edafaa_student_profile_portal,edafaa_batch_intake \
  --stop-after-init
```

Reload Odoo workers after upgrade.

## Verification

- Unit tests: **9/9** passed
- Playwright: **5/5** passed (`tests/playwright/op206/op206_requirements.spec.mjs`)
- Screenshots: `delivery/screenshots/` (R1–R4)

## Proof student (post-upgrade path)

- Registration: `REG00013` (id 12)
- Student: id **181** — `registration_number=REG00013`, `source_type=student_registration`

## Attachments in this package

| Path | Content |
|------|---------|
| `notes/FIX_NOTES.md` | This file (EN) |
| `notes/FIX_NOTES_AR.md` | Arabic fix notes |
| `notes/OP206_UAT_FIX_REPORT.md` | Full implementation report |
| `notes/PLAYWRIGHT_PROOF_EXPLAIN.md` | How Playwright proves each requirement |
| `notes/UAT_CHECKLIST.md` | Retest checklist |
| `notes/unit_test_run_2026-07-04.log` | Unit test log |
| `screenshots/r1_*.png` | Group By Current Course |
| `screenshots/r2_*.png` | Labels + mapping |
| `screenshots/r3_*.png` | Blood Group hidden |
| `screenshots/r4_*.png` | Registration number + source type |
