# Development Plan — OP#353 / Odoo #44 (S1 locked)

**Title:** Voucher Number on student profile  
**Sprint:** S1  
**Effort:** 2–3 hours  
**Status:** Done (2026-07-15)  
**Module:** `edafaa_student_profile`  
**Branch:** `feature/meeting-s1-351-353-356`

---

## Locked scope

- `voucher_number` Char on `op.student`  
- Form + list (optional) + search  
- Manual entry only  
- **Not in S1:** batch CSV / registration mapping  

---

## Steps

| Step | Action |
|------|--------|
| 1 | Field on model next to `id_number` |
| 2 | Form after `id_number`; list + search |
| 3 | Unit tests |
| 4 | Upgrade + UAT |
| 5 | OP#353 / Odoo #44 comment |

## Code

```python
voucher_number = fields.Char(
    string='رقم قسيمة الاختبار',
    size=64,
    index=True,
)
```

## Acceptance

- [ ] Field editable on profile  
- [ ] Persists; visible on list/search  
