# WP#356 Findings — Limited courses visible in the system

**Date:** 2026-07-15  
**OP:** [#356](https://master.tailcf9988.ts.net:10081/work_packages/356)  
**Odoo:** [#47](http://127.0.0.1:8069/web#id=47&model=project.task&view_type=form&db=sabry-test)  
**Sprint:** S1  
**Code change in S1:** **None** (investigation + recommendations only)

---

## Executive summary

**Root cause: expected UX / data — not an `ir.rule` bug limiting courses to two records.**

Non-admin Kafaat users are steered to **Program → Linked Courses**, which shows only courses with `program_id` equal to that program. On **TR_K19**, only **1 of 4** active courses is linked to a program; the other **3** are orphans (`program_id` NULL) and never appear under any program tab. The standalone **Courses** menu is **SIS admin only**.

---

## SQL evidence (2026-07-15)

### sabry-test

| Metric | Value |
|--------|-------|
| Active courses | **14** |
| Orphan (`program_id` IS NULL) | **12** |
| Linked to a program | **2** (both on program “P2 Evidence Program”) |

### TR_K19 (client DB)

| id | Code | program_id | Active |
|----|------|------------|--------|
| 1 | CBPLC-2026 | NULL | t |
| 2 | PHRI-2026 | NULL | t |
| 3 | PMP-2026 | NULL | t |
| 4 | 001 (C++) | **1** (Front end) | t |

| Program | Linked active courses |
|---------|------------------------|
| Front end (id=1) | **1** |

**Client “only a few courses / only two”** matches opening Program → Linked Courses when the open program has 1–2 linked courses, **not** a global cap of two in code.

---

## Code behavior (by design)

| Mechanism | Path | Effect |
|-----------|------|--------|
| Courses menu ACL | `edafaa_kafaat_sis/views/menu_views.xml` → `openeducat_core.menu_op_course_sub` | `group_sis_admin` only |
| Linked Courses domain | `edafaa_training_crm/models/op_program.py` → `action_view_linked_courses` | `domain=[('program_id', '=', self.id)]` |
| Record rules on `op.course` | — | **None** found that cap count |

---

## Recommended remediation (ops / process — S1)

1. **Data:** On TR_K19, assign `program_id` for CBPLC / PHRI / PMP (and any future courses) so they appear under the correct Program → Linked Courses.  
2. **Access:** Users who need a **global** course list need `group_sis_admin` (or equivalent) so the Courses menu is visible.  
3. **Training:** Document for client: normal SIS users manage courses via **Configuration → Programs → [program] → Linked Courses**, not the admin Courses menu.  
4. **Follow-up WP:** Only if an **admin** user opens **Courses** (global list) and still sees a wrong subset when SQL shows more — then investigate as a bug. Not observed as a code defect in S1.

---

## S1 acceptance

- [x] Root cause documented with SQL  
- [x] No ACL/domain code change in S1  
- [ ] Posted to OP#356 + Odoo #47 (delivery step)
