# Direct ATS canary candidate discovery

**Stamp:** `20260803T051948Z`  
**Verdict:** `DIRECT_ATS_DRAFT_CANARY_CANDIDATE_READY`

## Summary

One safe direct-employer ATS candidate was qualified on **TEST only** for the next **draft-only** canary:

| Field | Value |
|--------|--------|
| TEST job id | **40** |
| Title | Software Developer |
| Employer | Odoo S.A. |
| Location | Grand-Rosière (Farm 2), Belgium |
| Direct apply URL | `https://www.odoo.com/jobs/apply/software-developer-1` |
| ATS | `company_ats` / Odoo website recruitment |
| Local score | **65** (`odoo` 30 + `seniority` 25 + `stack` 10) |
| Dify UAT | `match_decision=shortlist`, run `edf3760a-9ec3-4955-bc84-2bac79523a2e` |

## Constraints honored

| Control | Result |
|---------|--------|
| JSearch | Cap already at day_count=3 — **no new JSearch** |
| Production jobs/apps | Unchanged (`12` jobs, `0` apps, module `19.0.2.9.1`) |
| Draft fill / n8n / submit / WhatsApp / LinkedIn automation | **Not executed** |
| Login / CAPTCHA bypass / form fill | **Not done** |
| Public search budget | 6 DuckDuckGo `site:` queries earlier (challenge pages, 0 links); then GET-only career/ATS pages |

## TEST profile facts (id=2)

Stored on TEST only; visa left unset (not inferred):

- Salary: USD 1,000 / month  
- Notice: 1 month  
- On-site: yes (`work_mode_preference=onsite`)  
- Relocate: yes (`uae_relocation=yes`)  
- Visa sponsorship: **unset**

## Discovery rejects (examples)

| Candidate | Why rejected |
|-----------|----------------|
| Stored JSearch ≥65 roles | Indeed / BeBee / aggregators only |
| Odoo ME Software Developer `511` | **0–1 year max** (junior-only) |
| Odoo ME Technical Consultant Education | 0–1 year + Russian/Turkish/Urdu required |
| Tecnativa Odoo role | Spanish-language form (`unsupported_language_es`) |
| OpenInside Senior Engineer (Bahrain) | Form OK / no Turnstile, but JD text contains “junior engineers” → local scorer −40; not used as primary ≥65 gate |
| Qualysoft Lever (prior) | German C1 |

## Recommended canary — preflight (sanitized)

- Redirect chain: apply URL resolves on `www.odoo.com` (employer careers) — **0 suspicious aggregator hops**
- Application form **visible without login** (`partner_name`, `email_from`, `partner_phone` required)
- Optional: LinkedIn URL, Resume file **or** LinkedIn, short introduction  
- Cloudflare Turnstile widget present on page; **does not block form view/access** (no verify-human wall). Draft canary must **stop** if submit path challenges — submit remains disabled  
- Mutations (POST/XHR) **aborted** during inspection  
- Listing chip also shows “Junior or higher” (inclusive floor, not internship); scored description used **About the job** body (no junior-only exclusion)

## Required-field map

| Field | Required | Notes |
|-------|----------|--------|
| Your Name (`partner_name`) | yes | |
| Your Email (`email_from`) | yes | |
| Your Phone (`partner_phone`) | yes | |
| LinkedIn Profile | no | Resume **or** LinkedIn |
| Resume (file) | no | Resume **or** LinkedIn |
| Short Introduction | no | |

## Missing candidate facts

- `visa_sponsorship` — unknown; do not infer (Dify flagged; omitted from sanitized profile)

## Dify UAT pack (sanitized)

- `match_decision`: shortlist  
- `exclusion_flags`: []  
- `recommended_channel`: `manual_linkedin` *(workflow default — **override for canary**: use browser draft on company ATS URL; not LinkedIn)*  
- Cover letter: null (expected until draft pack enrichment)

## Next step (not done here)

Approved **draft-only** live canary against TEST job **40** / apply URL above: dry-run worker fill, mutation containment, stop on Turnstile/CAPTCHA, **no submit**.

## Evidence paths

`linkedin_connector/docs/uat_evidence/direct_ats_discovery_20260803T051948Z/`

- `CANDIDATE_CANONICAL.json`, `TEST_CANDIDATE_RECORD.json`, `DIFY_PACK.json`, `DIFY_UAT_RUN.json`  
- `preflight/odoo_be_sd_1_*.json`, screenshots under `screenshots/`
