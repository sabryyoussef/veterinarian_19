# Sabry Odoo Development — Multi-Company Outreach Implementation Plan

**Date:** 2026-08-03  
**Database:** `pet_spot_elsahel` (ONE DB, ONE admin user, TWO companies)  
**Target verdict:** `SABRY_COMPANY_WEBSITE_AND_OUTREACH_UAT_READY_FOR_REVIEW`  
**Hard rule:** No real partner campaign send. Sample only to `abhorya@gmail.com` / `vendorah2@gmail.com`. Never send from `vetelsahel@gmail.com`.

---

## 1. Current-state findings (Phase 0 audit)

| Item | Finding |
|------|---------|
| Companies | Only `pet.spot` (id=1), currency EGP (id=74), email `vetelsahel@gmail.com`, website_id=1 |
| Websites | (1) `pet.spot` → https://drpaws.ai company 1; (2) `sabry_youssef_resume` company 1; (3) `Sabry / Odoo Developer` company 1 |
| Admin users | `admin` (id=2) company_id=1; Shopify system user (id=5) |
| Partners | ~9026 with `company_id` NULL (shared); 7 with company 1 |
| Eligible audience | Email Ready ∩ (Gold∪Silver) ∩ active ∩ email ∩ ¬Needs Review ¬Duplicate Candidate ≈ **879** |
| Odoo Partner tagged | 6726 |
| Modules | `mass_mailing` installed; `odoo_partners` installed; `sabry_developer_website` installed; `developer_hub` installed |
| Missing modules | `mass_mailing_partner` (not on addons_path); `mail_partner_opt_out` (same) |
| Mailing lists | Only `Newsletter` (id=1) |
| Mailings | None |
| SMTP | Only `vetelsahel@gmail.com` — **forbidden for outreach** |
| Gmail connector | `abhorya@gmail.com` / `vendorah2@gmail.com` accounts exist but OAuth `invalid_grant` (re-auth needed for live sample) |
| `web.base.url` | https://drpaws.ai (frozen) |
| CRM | Team `Odoo Partner Outreach` exists (company unset) |
| CV | `/home/sabry/private/job_orchestrator/handoff/session_cv/Sabry_Youssef_CV.pdf` valid PDF 76123 bytes |
| Tags | From `odoo_partners` XML: Gold/Silver/Bronze, Email Ready, Fully Outreach Ready, Ready for Outreach, regions, etc. |

### company_id on key models (DB schema)

| Model | Has company_id? |
|-------|-----------------|
| `res.partner` | Yes |
| `website` | Yes |
| `crm.lead` | Yes |
| `ir.attachment` | Yes |
| `mailing.list` | **No** |
| `mailing.contact` | **No** |
| `mailing.mailing` | **No** |
| `mail.template` | **No** |

---

## 2. Data model gaps

1. Mass mailing models lack `company_id` → need `sabry_odoo_company_isolation`.
2. Existing Sabry websites are bound to PetSpot company → rebind to new company.
3. Partner directory rows are company-shared (NULL) → curated **copies** under Sabry company (never global reassignment).
4. No personal outgoing mail server for Sabry company.
5. `mass_mailing_partner` / `mail_partner_opt_out` not on pet_spot addons_path → add OCA path or vendor modules into project.

---

## 3. Multi-company isolation strategy

```
PetSpot (id=1)                    Sabry Odoo Development (new)
├── pet.spot website              ├── Sabry website (rebound/enhanced)
├── clinic/store contacts         ├── curated partner COPIES (company_id=Sabry)
├── vetelsahel SMTP               ├── personal SMTP / mailing email_from
├── Newsletter list               ├── Sabry — Odoo Partners — Gold Silver
└── operational CRM               ├── Outreach CRM team + contact form leads
```

- Same `admin` user; `company_ids` includes both; default remains PetSpot for ops safety when possible.
- Isolation is **data-level** (company_id + constraints), not hiding records from admin.
- No restrictive rules that lock admin out of PetSpot.

---

## 4. Website strategy

- Keep website 1 (`pet.spot` / drpaws.ai) untouched.
- Rebind website 3 (`Sabry / Odoo Developer`) → Sabry company; rename to `Sabry Odoo Development`.
- Archive or leave website 2 unused (duplicate resume site).
- Expand `sabry_developer_website` (+ isolation hooks) with pages: `/`, `/about`, `/services`, `/portfolio`, `/experience`, `/cv`, `/contact`.
- Contact form → `crm.lead` / partner with `company_id` = Sabry; team = Odoo Partner Outreach (Sabry company).
- Domain: document DNS later; do not block on domain.

---

## 5. Contact migration / duplication strategy

- Source: PetSpot DB partners matching eligibility (read in place).
- Action: create/update **copies** with `company_id` = Sabry.
- Idempotency: `normalized_email` + Sabry `company_id`.
- Fields: name, email, phone, website, company_name, categories (by name), `x_source_partner_id` audit link.
- Never empty `company_id` on outreach copies.
- Never reassign source rows globally.

---

## 6. Mailing strategy

- Channel: Email Marketing (`mailing.mailing`), not lead_engine.
- List: `Sabry — Odoo Partners — Gold Silver` (company_id=Sabry).
- Template design: `SABRY | Odoo Outreach | EN`.
- Draft only: `Sabry CV Outreach — Gold Silver — Canary`.
- Attach CV under Sabry company attachment.
- Production audience frozen to CSV; campaign stays Draft.
- Test list: only abhorya + vendorah2.

---

## 7. Attachment strategy

- Copy latest CV into `ir.attachment` with `company_id` = Sabry.
- Link to draft mailing via `attachment_ids`.
- Also expose download on `/cv` page from same file.

---

## 8. Risks

| Risk | Mitigation |
|------|------------|
| Accidental partner send | Draft-only; test list separate; no schedule |
| Wrong SMTP (vetelsahel) | Force mailing `mail_server_id` / email_from to Sabry; refuse vetelsahel |
| Gmail OAuth dead | Document re-auth as manual blocker for sample; still leave draft ready |
| Cross-company contamination | company_id constraints + tests |
| PetSpot downtime | Short service restart windows only; backup first |
| Duplicate partners | Idempotent upsert by email+company |

---

## 9. Test plan

- Unit/ORM tests in `sabry_odoo_company_isolation`.
- Verify 0 exclusion leaks, 0 empty company_id, 0 PetSpot-company on list.
- PetSpot website still HTTP 200; company 1 unchanged.
- Contact form creates Sabry company lead.

---

## 10. Rollback plan

1. Restore from `pg_dump` backup taken before Phase 1.
2. Or: deactivate Sabry company, archive Sabry website, delete Sabry-company partners by domain filter `company_id = Sabry`, uninstall isolation module.

---

## 11. Exact implementation sequence

1. Write this plan + take DB backup.
2. Append OCA mass_mailing (+ mail_partner_opt_out) to addons_path safely.
3. Create module `sabry_odoo_company_isolation` + enhance website module.
4. Create company Sabry Odoo Development; grant admin both companies.
5. Install/upgrade modules.
6. Copy eligible partners; apply exclusions; blacklist.
7. Rebind website; build pages; SEO; contact routing.
8. Create list, template, draft mailing + CV.
9. Export CSVs / audit reports.
10. Attempt controlled sample (or document SMTP blocker).
11. Run tests; collect evidence; write FINAL_REPORT.

---

## Defaults chosen (no wait for confirmation)

- Currency for Sabry company: **USD** (professional services) with EGP available.
- Email on company: `abhorya@gmail.com` (not vetelsahel).
- Audience: Email Ready ∩ Gold/Silver; also prefer Odoo Partner tag when present.
- Do **not** blanket-exclude free-mail domains.
- Archive duplicate website `sabry_youssef_resume` if unused.
- Sample sender preference: abhorya Gmail after re-auth; never vetelsahel.
