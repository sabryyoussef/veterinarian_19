# Identity verification & personal UAT — 2026-08-02

## Verdict

**`BLOCKED_PERSONAL_LINKEDIN_IDENTITY_CONFIRMATION_REQUIRED`**

Secondary (not reached): `BLOCKED_DEFAULT_CV_REQUIRED` — no approved CV PDF found in project/module locations.

Phases 3–5 (reclassify, CV attach, controlled application UAT) were **not executed** because identity of the connected member was not proven to the required vanity URL.

---

## Phase 1 — Baseline

| Item | Value |
|------|--------|
| Database | `pet_spot_elsahel_test` only |
| Branch | `feature/petspot-vendor-sell-through` |
| Start commit | `1999e63c42dec600f2bca7f3e54dcae43e57ad4c` |
| Working tree | Dirty (many unrelated modules; preserved) |
| Manifest version | `19.0.2.8.0` |
| Installed module version | `19.0.2.8.0` (`installed`) |
| Production | Untouched |

### Live-search / cron state

| Control | Before this phase | After safety hardening |
|---------|-------------------|------------------------|
| `linkedin_connector.live_job_search_enabled` | `False` | `False` |
| LinkedIn: Daily Job Digest | inactive | inactive |
| LinkedIn: Publish Scheduled Posts | **active** | **inactive** (test DB only) |
| LinkedIn: Refresh Feed | **active** | **inactive** (test DB only) |
| LinkedIn: Sync Messages | **active** | **inactive** (test DB only) |

Inspection used SQL + Odoo shell read-only probes. No posts published, no job search, no applications opened/submitted.

### Accounts (masked)

| id | name | account_type | active | org_id | member_urn (masked) | profile_url | token | scopes | fallback |
|----|------|--------------|--------|--------|---------------------|-------------|-------|--------|----------|
| 1 | PetSpot LinkedIn | company | yes | present:`129944345` | absent | (empty) | no_token | `openid profile w_member_social` | false |
| 2 | PetSpot LinkedIn (Test) | personal | yes | absent | `urn:li:person:d7Sy…2VJ9` | (empty) | token_present (expires 2026-08-18) | `openid profile w_member_social` | false |

### Posts

| account_id | purpose | state | count |
|------------|---------|-------|------:|
| 1 | — | none | 0 |
| 2 | job_branding | posted | 10 |

Draft/scheduled posts: **0**.  
CV versions: **0**. Applications: **0**.

---

## Phase 2 — Identity evidence for account id=2

**Target personal profile:** Sabry Youssef — `https://www.linkedin.com/in/sabry-youssef-56a878185/`

**Method:** read-only OIDC `GET https://api.linkedin.com/v2/userinfo` using the existing bearer token (token value never logged).

| Field | Result |
|-------|--------|
| HTTP status | `200` |
| Keys returned | `family_name`, `given_name`, `locale`, `name`, `picture`, `sub` |
| `name` | `sabry youssef` |
| `given_name` / `family_name` | `sabry` / `youssef` |
| `sub` vs stored member URN | **match** (stored member matches userinfo `sub`) |
| Email | not returned |
| Vanity URL / public profile slug | **not returned by userinfo** |
| Org identity | no organization ID on record; cannot prove PetSpot org from this token |

### Conclusion

API shows a connected **person** whose OpenID display name is “sabry youssef” and whose `sub` matches the stored member URN.

Per mandatory rule — **do not declare a match based only on the displayed name** — and because LinkedIn userinfo **does not expose** `/in/sabry-youssef-56a878185/`, identity of account id=2 is **not proven** to the required vanity URL.

Also insufficient to prove PetSpot organization ownership (no org ID / org URN on this record).

**Classification of identity state:** unknown / unproven (name-similar, vanity URL unproven).

**Account left unchanged** (no rename, reclassify, disconnect, archive, or reconnect).

---

## Phase 3 — Classification (not performed)

Blocked pending your confirmation.

### Manual confirmation steps (choose one)

**Option A — Confirm existing token is your personal profile**

1. In a private browser, open LinkedIn while logged in as  
   `https://www.linkedin.com/in/sabry-youssef-56a878185/`.
2. Confirm you are the only session that authorized the Odoo LinkedIn app recently.
3. Reply in chat with one of:
   - `CONFIRM_ACCOUNT_2_IS_SABRY_PERSONAL` — I confirm account id=2 is my personal profile at that URL.
   - `ACCOUNT_2_IS_NOT_SABRY` — it is someone else / unknown.

**Option B — Fresh OAuth reconnect under the target profile**

1. Leave account id=2 unchanged for now (or later disconnect after confirmation).
2. Create a new `linkedin.account` named `Sabry Youssef — Personal` with:
   - `account_type=personal`
   - `profile_url=https://www.linkedin.com/in/sabry-youssef-56a878185/`
   - scopes: `openid profile w_member_social` (no `w_organization_social`)
   - no company page ID
3. Click **Connect** while logged into that LinkedIn profile.
4. After callback, re-run identity probe; compare new member URN to prior id=2 URN.
5. Only then mark ready / reclassify leftovers.

Until then: do **not** schedule personal posts, enable publish cron, or attach job applications to account id=2 as “verified Sabry”.

---

## Phase 4 — Default CV (blocked)

Searched:

- `linkedin_connector/**`
- `pet_spot_elsahel/**` for `*.pdf` / resume-named assets

**Candidates:** none suitable for personal job-hunt CV.  
Only unrelated PDF found: `reports/sahel_partner_ledger_reconciliation.pdf` (not a CV).

**Result:** `BLOCKED_DEFAULT_CV_REQUIRED`

Please provide the path to the approved CV PDF (or attach it under an approved module path) and confirm selection. No LinkedIn document upload will be performed in this phase.

---

## Phase 5 — Controlled UAT (not performed)

Skipped because identity is unproven and no default CV exists.

Planned offline UAT (fixtures only) remains ready in code/tests; will execute after you clear identity (+ CV) blockers.

---

## Phase 6 — Regression note

Prior suite on this DB: **16/16 passed** (`test_run_20260801d.log`).  
Full suite re-run deferred until after identity confirmation to avoid implying personal UAT readiness.

Production: **untouched**.

---

## Safety confirmation

| Action | Status |
|--------|--------|
| Live LinkedIn search | not run |
| Publish / test post | not run |
| Open/submit application | not run |
| Profile edit / document upload to LinkedIn | not run |
| Account id=2 modified | **no** |
| Tokens/secrets logged | **no** |
| Production upgrade/cron | **no** |

---

## What I need from you

1. Identity confirmation: `CONFIRM_ACCOUNT_2_IS_SABRY_PERSONAL` **or** `ACCOUNT_2_IS_NOT_SABRY` (then Option B OAuth).  
2. Path/selection of the approved CV PDF for Odoo-side `linkedin.cv.version` only.
