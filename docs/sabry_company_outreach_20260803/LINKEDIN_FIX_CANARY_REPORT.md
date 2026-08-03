# LinkedIn URL Fix + Corrected Canary

**Verdict:** `SABRY_LINKEDIN_FIXED_CANARY_DELIVERED_READY_FOR_PILOT_APPROVAL`

## Old LinkedIn URL found

```text
https://www.linkedin.com/in/sabry-youssef
```

## Resources corrected

| Resource | Change |
|----------|--------|
| mailing id=1 body_html / body_arch | LinkedIn URL + From/Reply-To/SMTP binding |
| mailing id=3 body_html / body_arch | LinkedIn URL + From/Reply-To/SMTP binding |
| mail.template id=72 `SABRY \| Odoo Outreach \| EN` | LinkedIn URL + From |
| website id=3 `social_linkedin` | corrected |
| `sabry_developer_website/views/templates.xml` | 3 LinkedIn href/JSON-LD refs |
| `sabry_odoo_company_isolation/.../sabry_outreach_setup_wizard.py` | template string default |

PetSpot resources were not modified.

## Final rendered LinkedIn URL

```text
https://www.linkedin.com/in/sabry-youssef-56a878185/
```

## Routing (mailings 1 and 3)

| Field | Value |
|-------|-------|
| From | `"Sabry Odoo Development" <vendorah2@gmail.com>` |
| Reply-To | `vendorah2@gmail.com` |
| SMTP | id=2 `Gmail - Sabry Odoo Development` |
| Company | id=3 |
| Production mailing id=1 | **draft** (not launched) |

## Corrected canary counts

| Attempted | Delivered | Failed |
|-----------|-----------|--------|
| 2 | 2 | 0 |

Recipients: `vendorah2@gmail.com`, `abhorya@gmail.com` only.

## Validation highlights

- Delivered inbox copy contains correct LinkedIn URL; old URL absent
- Reply-To header = `vendorah2@gmail.com`
- CV `Sabry_Youssef_CV.pdf` attached
- `/sabry/*` HTTP 200; correct LinkedIn on pages; no vetelsahel / PetSpot footer
- Canary remains draft; list id=5 only

Evidence JSON: `/home/sabry/.cursor/evidence/sabry-company-outreach-uat-20260803/LINKEDIN_CANARY.json`
