# Development Plan — OP#351 / Odoo #42 (S1 locked)

**Title:** Search trainees by national ID  
**Sprint:** S1  
**Effort:** 2–3 hours  
**Status:** Done (2026-07-15)  
**Module:** `edafaa_student_profile`  
**Branch:** `feature/meeting-s1-351-353-356`

---

## Locked scope

- Add `id_number` to student search view  
- Set `_rec_names_search` for autocomplete by ID / Arabic / English names  
- Unit tests + upgrade on `sabry-test`  
- **Not in S1:** registration/batch changes  

---

## Steps

| Step | Action |
|------|--------|
| 1 | XPath after `name` in `student_search_views.xml` |
| 2 | `_rec_names_search` on `op.student` |
| 3 | Unit tests |
| 4 | Upgrade + UAT |
| 5 | OP#351 / Odoo #42 comment |

## Code

```xml
<field name="name" position="after">
    <field name="id_number" string="رقم الهوية"/>
</field>
```

```python
_rec_names_search = ['name', 'id_number', 'name_arabic', 'name_english']
```

## Acceptance

- [ ] Search finds by رقم الهوية  
- [ ] Many2one picker finds by ID  
- [ ] Existing search filters unchanged  
