# Development Plan — OP#352 / Odoo #43 (S2 locked)

**Title:** Student application status (`حالة الطالب`)  
**Sprint:** S2  
**Effort:** 2–3 days  
**Branch:** `feature/meeting-s2-352-354`  
**Modules:** `edafaa_student_profile` (+ `edafaa_student_profile_portal` sync)

---

## Locked decisions

| Topic | Decision |
|-------|----------|
| Storage | Stored Selection `application_status` on `op.student` |
| Not reused | `training_status` (new/active/completed) stays separate |
| Labels | accepted→مقبول, rejected→مرفوض, under_review→تحت المراجعة, cancelled→ملغي |
| Default | `under_review` |
| Manual edit | Allowed (`tracking=True`) |
| ملغي | Does **not** set `active=False` |
| Sync | From `student.registration.state` via portal bridge |

### Registration → application_status map

| `student.registration.state` | `application_status` |
|---------------------------|----------------------|
| `approved`, `enrolled` | `accepted` |
| `rejected` | `rejected` |
| `draft`, `submitted`, `eligibility_review`, `document_review` | `under_review` |

ملغي is set only on `op.student` (no new registration cancelled state in S2).

---

## Steps

| Step | Hours | Action |
|------|-------|--------|
| 1 | 2 | Add field + Arabic labels |
| 2 | 2 | Form + list + search/group-by |
| 3 | 3 | Portal sync on create/update + write(state) |
| 4 | 1 | post_init fill blanks → `under_review` |
| 5 | 2 | Unit tests + UAT |
| 6 | 1 | OP/Odoo close + delivery screenshots |

---

## Code touchpoints

- [`custom_addons/edafaa_student_profile/models/student.py`](../../custom_addons/edafaa_student_profile/models/student.py)
- [`custom_addons/edafaa_student_profile/views/student_views.xml`](../../custom_addons/edafaa_student_profile/views/student_views.xml)
- [`custom_addons/edafaa_student_profile/views/student_search_views.xml`](../../custom_addons/edafaa_student_profile/views/student_search_views.xml)
- [`custom_addons/edafaa_student_profile_portal/models/student_registration.py`](../../custom_addons/edafaa_student_profile_portal/models/student_registration.py)
- Tests: `tests/test_meeting_s2.py`

Version bump: `edafaa_student_profile` → `19.0.2.5.0`

---

## Acceptance

- [ ] Four statuses on profile (Arabic)
- [ ] Form + list + search/group-by
- [ ] Mapping documented + sync works
- [ ] UAT on sabry-test

## Out of scope

Auto-archive on ملغي; new registration `cancelled` state.
