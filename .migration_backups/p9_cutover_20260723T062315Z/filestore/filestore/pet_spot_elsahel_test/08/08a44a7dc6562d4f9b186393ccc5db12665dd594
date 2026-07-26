# Development Plan — OP#358 / Odoo #49

**Title:** Batch attendance + QR Code per batch  
**Sprint:** S5 — after design sign-off  
**Effort:** 3–6 weeks  
**Module:** new `edafaa_batch_attendance` (depends on `openeducat_attendance`, `openeducat_core`)

---

## Precondition — design lock (Week 0)

Client chooses:

| Topic | Options |
|-------|---------|
| Check-in UX | Student portal (phone) vs classroom kiosk |
| QR lifetime | Stable per batch vs daily regen |
| Late policy | Allow after start? Grace minutes? |

**No development without written answers on OP#358.**

---

## Phases & time

| Phase | Weeks | Deliverable |
|-------|-------|-------------|
| 0 Design | 0.5 | Sequence diagrams + API contract |
| 1 Batch QR | 1 | Token field + QR image on `op.batch` |
| 2 Attendance link | 1 | Auto/manual register per batch session |
| 3 Check-in endpoint | 1–1.5 | Portal/controller: scan → enroll check → line |
| 4 Security & audit | 0.5 | Rate limit, revoke, logs |
| 5 UAT | 1 | Staging scenarios + fix |

---

## Code sketch

### 1. Model extend `op.batch`

```python
# edafaa_batch_attendance/models/op_batch.py
class OpBatch(models.Model):
    _inherit = 'op.batch'

    attendance_qr_token = fields.Char(copy=False, index=True)
    attendance_qr_image = fields.Binary(compute='_compute_qr')

    def action_regenerate_qr(self):
        for batch in self:
            batch.attendance_qr_token = uuid.uuid4().hex
```

### 2. Controller

```python
# controllers/attendance_qr.py
@http.route('/attendance/batch/<string:token>', type='http', auth='user', website=True)
def batch_checkin(self, token, **kw):
    batch = request.env['op.batch'].sudo().search([('attendance_qr_token', '=', token)], limit=1)
    # verify student partner → op.student enrolled in batch
    # create/update op.attendance.line present=True
```

### 3. Enrollment gate

```python
enrolled = request.env['op.student.course'].search_count([
    ('student_id', '=', student.id),
    ('batch_id', '=', batch.id),
])
if not enrolled:
    raise AccessError(_('Not enrolled in this batch'))
```

### 4. Manifest

```python
{
    'name': 'Edafaa Batch Attendance QR',
    'depends': ['openeducat_attendance', 'openeducat_core', 'portal'],
    'data': ['security/ir.model.access.csv', 'views/op_batch_views.xml', ...],
}
```

### 5. QR library

Use `qrcode` or Odoo barcode if available — pin dependency.

---

## UAT scenarios

1. Enrolled student scans → present  
2. Other student scans → rejected  
3. Revoked QR → rejected  
4. Attendance sheet shows batch roster consistency  

---

## Acceptance

- [ ] Unique QR per batch  
- [ ] Enrollment enforced  
- [ ] Lines match roster  
- [ ] Staging UAT signed  

## Dependencies

`openeducat_attendance` installed on target DB. Enterprise barcode modules **not** required if we build this module.
