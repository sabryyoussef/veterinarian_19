# Development Plan — OP#357 / Odoo #48

**Title:** Full Arabic UI translation  
**Sprint:** S4 — Weeks 5–8 (after S1–S3)  
**Effort:** 2–4 weeks  
**Scope default (recommended):** Edafaa SIS modules only

---

## Precondition — scope lock (Day 0)

| Scope option | Effort | Recommendation |
|--------------|--------|----------------|
| A. Edafaa + student portal only | 2–3 w | **YES — default** |
| B. + remaining OpenEduCat gaps | +1 w | Optional |
| C. Entire Odoo (HR/Accounting) | 4+ w | Out of this WP |

Client must pick A / B / C in writing on OP#357.

---

## Steps & time (Scope A)

| Step | Days | Action |
|------|------|--------|
| 1 | 1 | Inventory hardcoded AR/EN strings in edafaa_* |
| 2 | 2 | Replace hardcoded Arabic with English source + `_()` |
| 3 | 3 | Generate `i18n/ar_001.po` for each edafaa module |
| 4 | 2 | Translate / fill `.po` |
| 5 | 2 | Load language, UAT critical flows |
| 6 | 1 | Coverage report + OP/Odoo update |

**Modules:**  
`edafaa_student_profile`, `edafaa_student_profile_portal`, `edafaa_batch_intake`, `edafaa_training_crm`, `edafaa_kafaat_sis`, `student_enrollment_portal`

---

## Code pattern

### Bad (current)

```python
id_number = fields.Char(string='رقم الهوية')
```

### Good

```python
id_number = fields.Char(string='National ID')  # translate via ar_001.po
```

```po
#. module: edafaa_student_profile
#: model:ir.model.fields,field_description:edafaa_student_profile.field_op_student__id_number
msgid "National ID"
msgstr "رقم الهوية"
```

### Export

```bash
# From Odoo module export / weblate / odoo i18n export
# Place files at: custom_addons/<module>/i18n/ar_001.po
```

Bump module versions after adding `i18n/`.

---

## UAT checklist

User language = `Arabic / العربية` (`ar_001`):

- [ ] Students list + form  
- [ ] Registration  
- [ ] Batch intake  
- [ ] Program / Courses  
- [ ] No mixed EN labels on in-scope screens  

---

## Acceptance

- [ ] Scope written on WP  
- [ ] `.po` per in-scope module  
- [ ] UAT passed  
- [ ] Coverage report attached  

## Out of scope (unless B/C)

Accounting, Inventory, full Motakamel, HR leave (already separate WPs).
