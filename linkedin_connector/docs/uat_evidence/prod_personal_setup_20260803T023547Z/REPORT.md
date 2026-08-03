# Production Personal LinkedIn Account Setup — UAT Report

**Approval scope:** Personal account setup on Production only  
**Stamp:** `20260803T023547Z`  
**DB:** `pet_spot_elsahel` (Production)  
**Module:** `linkedin_connector` **19.0.2.8.0**  
**Verdict:** `PERSONAL_LINKEDIN_PRODUCTION_SETUP_READY_FOR_APPROVAL`

## Scope held

| Action | Status |
| --- | --- |
| Change PetSpot company account **id=1** | **Not changed** (row fingerprint MD5 unchanged) |
| New LinkedIn OAuth authorize / reconnect | **Not performed** (no live LinkedIn HTTP) |
| Publish / messages / job apply / digest activation | **Not performed** |
| Upload CV to LinkedIn Documents | **Not performed** |
| Activate LinkedIn crons / live job search | **Kept OFF** |

## 1) CV verification (before attach)

| Check | Result |
| --- | --- |
| Source | `/home/sabry/private/linkedin_cv/Sabry_Youssef_CV.pdf` |
| Size | 76123 |
| SHA-256 | `29e968d70baf80e04607dcc526d23b776796245cd4ac5c56a0301ebbd7d6f539` |
| Match approved prefix `29e968d7…d6f539` | **Yes** |

## 2) Personal account (separate from company)

| Field | Production value |
| --- | --- |
| Record | `linkedin.account` **id=2** (reconfigured; not copied from TEST) |
| Name | `Sabry Youssef — Personal` |
| Type | `personal` |
| Profile URL | `https://www.linkedin.com/in/sabry-youssef-56a878185/` |
| Public base URL | `https://drpaws.ai` |
| Redirect URI | `https://drpaws.ai/linkedin_connector/callback?db=pet_spot_elsahel` |
| Scopes | `openid profile w_member_social` (no `w_organization_social`) |
| Org ID | empty |
| `fallback_personal_post` | `false` |
| OAuth connected (token + member URN present) | **yes** (pre-existing token; not refreshed via LinkedIn in this step) |
| Token expires | ~2026-08-18 (see UI screenshot) |

## 3) PetSpot company account (untouched)

| Field | Production value |
| --- | --- |
| Record | `linkedin.account` **id=1** |
| Name | `PetSpot LinkedIn` |
| Type | `company` |
| Org ID / URN | `129944345` / `urn:li:organization:129944345` |
| Connected | **no** |
| Profile URL | empty/null |
| Fingerprint MD5 before/after | `480bd24a87cbe7707874cc72beb5a460` (**match**) |

## 4) CV attachment (Odoo filestore only)

| Field | Value |
| --- | --- |
| `linkedin.cv.version` | **id=1** `Sabry Youssef — Senior Odoo CV` |
| Account | personal **id=2** |
| Attachment | `ir.attachment` **id=11383** `Sabry_Youssef_CV.pdf` |
| Default | **yes** |
| Re-read SHA | matches approved |
| Readable PDF | **yes** (`%PDF-`) |
| LinkedIn document upload field | empty |

**Note:** An isolation negative-test briefly created a `bad` CV on company id=1 inside the same transaction catch path; it was **deleted immediately**. Re-test with explicit savepoint confirmed company CV create is blocked. Final CV count on Production: **1** (personal only).

## 5) Gates

| Gate | Result |
| --- | --- |
| LinkedIn: Publish Scheduled Posts | **inactive** |
| LinkedIn: Refresh Feed | **inactive** |
| LinkedIn: Sync Messages | **inactive** |
| LinkedIn: Daily Job Digest | **inactive** (`lastcall` null) |
| `linkedin_connector.live_job_search_enabled` | **False** |

## 6) Isolation + side effects

| Check | Result |
| --- | --- |
| Company + `job_branding` post | **blocked** |
| Personal + `company_marketing` post | **blocked** |
| CV on company account | **blocked** (after savepoint-safe retest) |
| Jobs / applications | **0 / 0** |
| New posts written during setup window | **0** |
| Live LinkedIn API calls in this phase | **none** |

## 7) Screenshots

Directory: `screenshots/`

| File | Shows |
| --- | --- |
| `01_login_page.png` | Production login |
| `02_after_login.png` | Authenticated web client |
| `03b_accounts_list_action.png` | Both accounts: company vs personal, connected flags |
| `04_personal_form.png` | Personal OAuth config + Connected + CV versions=1 |
| `05_company_form.png` | PetSpot company org `129944345`, not connected |
| `06b_cv_list_action.png` | Single default CV on personal account |
| `07_cv_form.png` | CV form + “not uploaded to LinkedIn” note |
| `08b_digest_cron_form.png` | Daily Job Digest **Active=OFF** |
| `08c_publish_cron_form.png` | Publish Scheduled Posts cron form |

## 8) Residual / next approvals required

- Confirm OAuth member matches Sabry’s profile in LinkedIn UI (human check; no API call done here).
- Token expiry ~Aug 18 — reconnect only under a later approval if needed.
- **Still require separate explicit approval for:** digest activation, publishing, job applications, outbound LinkedIn actions, LinkedIn CV upload.

## Stop line

**`PERSONAL_LINKEDIN_PRODUCTION_SETUP_READY_FOR_APPROVAL`**
