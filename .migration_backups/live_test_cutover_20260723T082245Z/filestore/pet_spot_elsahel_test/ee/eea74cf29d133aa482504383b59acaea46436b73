# Development Plan — OP#355 / Odoo #46 (S3 locked)

**Title:** Excel bulk assign trainees to sales staff  
**Sprint:** S3  
**Effort:** 5–7 days  
**Branch:** `feature/meeting-s3-355`  
**Module:** `edafaa_student_profile` → `19.0.2.6.0`

---

## Locked decisions

| Topic | Decision |
|-------|----------|
| Trainee match | `op.student.id_number` (exact trim) |
| Staff match | `res.users` by login first, else email (ilike) |
| Field | `assigned_user_id` → `res.users`, string `موظف المبيعات المسؤول` |
| Overwrite | Always overwrite; report overwrite count |
| File | `.xlsx` via openpyxl |
| Security | `sales_team.group_sale_manager` + `openeducat_core.group_op_back_office_admin` |
| CRM / grants | Out of scope |

### Template columns

| Column | Required |
|--------|----------|
| `id_number` | yes |
| `staff_login` | yes if staff_email empty |
| `staff_email` | yes if staff_login empty |
| `trainee_name` | optional |

---

## Steps

| Step | Action |
|------|--------|
| 1 | Field + form/list/search |
| 2 | Wizard: template / import / rejects CSV |
| 3 | ACL + Students → General menu |
| 4 | Unit + Playwright |
| 5 | OP/Odoo delivery + close |

---

## Acceptance

- [ ] Template downloadable  
- [ ] Import assigns sales staff  
- [ ] Reject report works  
- [ ] UAT on sabry-test  

## Out of scope

CRM lead assignee, grants `assigned_agent_id`, auto-create users/students, TR_K19.
