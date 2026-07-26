# OP#206 — Playwright proof: how each requirement is verified

**Date:** 2026-07-04  
**Database:** `sabry-test` (upgraded)  
**Branch:** `feature/op206-uat-retest-op86`  
**Suite:** [`tests/playwright/op206/op206_requirements.spec.mjs`](../../tests/playwright/op206/op206_requirements.spec.mjs)  
**Result:** **5 / 5 passed**

Proof student: `op.student` id **181** (created via `student.registration` finalize → `REG00013`).

---

## Upgrade performed

```bash
cp -a custom_addons/edafaa_student_profile \
      custom_addons/edafaa_student_profile_portal \
      custom_addons/edafaa_batch_intake /opt/localaddons/

odoo -c /etc/odoo/odoo.conf -d sabry-test \
  -u edafaa_student_profile,edafaa_student_profile_portal,edafaa_batch_intake \
  --stop-after-init --http-port=8079
```

Odoo workers restarted so the live UI loads the new registry/views.

---

## How to re-run

```bash
cd tests/playwright/op206
npm install && npx playwright install chromium

ODOO_PASSWORD=admin \
OP206_PROOF_STUDENT_ID=181 \
OP206_REGISTRATION_ID=12 \
npm test
```

Screenshots: [`docs/op206/evidence/screenshots/`](evidence/screenshots/)

---

## Requirement → test mapping

### R1 — Group By → Current Course

| What UAT asked | What the test proves |
|----------------|----------------------|
| Option **Group By → Current Course** exists | Live `op.student` **search** arch (via authenticated `get_views` RPC) contains `current_course_id` and label **المقرر الحالي** |

**Why this is valid:** Group By options come from the search view. If the arch is loaded in the running registry with `context="{'group_by': 'current_course_id'}"`, the UI menu exposes it. Field is **stored** so Odoo can group.

**Screenshot:** `r1_students_list.png`, `r1_group_by_current_course.png`

---

### R2 — Field labels and data mapping (ID, phone, specialization, address)

| What UAT asked | What the test proves |
|----------------|----------------------|
| Correct Arabic labels | Form text includes **رقم الهوية**, **التخصص**, **العنوان** |
| Correct binding | Field widgets on student **181** read: `id_number=2062062062`, `phone=0502060206`, `street=Proof Street 206`, specialization set |

**Why this is valid:** Student 181 was created only through `_create_student_record()` from registration `REG00013` (portal bridge). Matching values on the profile prove registration → student mapping, not manual UI entry.

**Registration form check:** Same Arabic labels on registration id **12** (`r2_registration_form_labels.png`).

**Screenshots:** `r2_trainee_form_labels.png`, `r2_registration_form_labels.png`

---

### R3 — Unused fields (Blood Group)

| What UAT asked | What the test proves |
|----------------|----------------------|
| Blood Group not shown | Trainee form text does **not** contain `Blood Group` or `فصيلة الدم` |

**Why this is valid:** Core still defines the field; inherit sets `invisible="1"`. Absence of the label on the live form is the UAT acceptance criterion.

**Screenshot:** `r3_no_blood_group.png`

---

### R4 — Registration Number and Source Type on Student Profile

| What UAT asked | What the test proves |
|----------------|----------------------|
| Registration Number copied | Form shows **رقم التسجيل** and value **REG00013** |
| Source Type set | Form shows **نوع المصدر** and **Student Registration Portal** |

**Why this is valid:** These fields did not exist on `op.student` before OP#206. Values were written only by portal finalize (`registration_number=self.name`, `source_type='student_registration'`), matching admission’s source vocabulary.

**Screenshot:** `r4_registration_source_fields.png`

---

## Summary table

| ID | Requirement | Test name | Pass |
|----|-------------|-----------|------|
| R1 | Group By Current Course | `R1 — Group By Current Course is available and applies` | Yes |
| R2 | Labels + mapping | `R2 — Trainee form…` + registration form test | Yes |
| R3 | Hide Blood Group | `R3 — Blood Group is not shown…` | Yes |
| R4 | Reg number + source type | `R4 — Registration Number and Source Type…` | Yes |

---

## Note on existing students

Students created **before** the upgrade (e.g. UAT-PW-Student-A) will not have `registration_number` / `source_type` unless backfilled. New registrations after upgrade get them automatically. Proof student **181** is the post-upgrade path.
