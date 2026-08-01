# Identity verification & personal UAT — 2026-08-02

## Verdict

**`BLOCKED_DEFAULT_CV_REQUIRED`**

Identity of account id=2 is now confirmed by Sabry. Phase 3 personal-account configuration on `pet_spot_elsahel_test` is complete.  
Phases 4–5 stopped because the approved CV path is not readable on this host.

---

## Identity confirmation (user)

Sabry confirmed in chat:

> `CONFIRM_ACCOUNT_2_IS_SABRY_PERSONAL`  
> Connected account id=2 via OAuth while logged into  
> `https://www.linkedin.com/in/sabry-youssef-56a878185/`  
> CV path given: `/home/sabry3/Sabry_Youssef_CV.pdf`

Supporting prior API evidence (read-only OIDC userinfo): display name `sabry youssef`, `sub` matches stored member URN (vanity URL not returned by API; confirmation supplied by Sabry).

---

## Phase 1 / safety (still true)

| Item | Value |
|------|--------|
| Database | `pet_spot_elsahel_test` only |
| Branch | `feature/petspot-vendor-sell-through` |
| Module | `linkedin_connector` `19.0.2.8.0` installed |
| Production | Untouched |
| Live search ICP | `False` |
| All LinkedIn crons | **inactive** (publish / feed / messages / digest) |

No live LinkedIn publish, search, apply, message, profile edit, or document upload performed.

---

## Phase 3 — Account classification (done)

### Before → after (account id=2, masked)

| Field | Before | After |
|-------|--------|-------|
| name | PetSpot LinkedIn (Test) | Sabry Youssef — Personal |
| account_type | personal | personal |
| profile_url | (empty) | `https://www.linkedin.com/in/sabry-youssef-56a878185/` |
| org_id | absent | absent |
| fallback_personal_post | false | false |
| scopes | `openid profile w_member_social` | same |
| connected | yes | yes |
| member_urn | `urn:li:person:d7Sy…2VJ9` | unchanged |
| author resolver | member URN | **member URN only** (`author_urn_is_member=true`) |

### Isolation proofs (test DB)

| Check | Result |
|-------|--------|
| Personal account rejects `company_marketing` post create | PASS |
| Company account (id=1) rejects `job_branding` post create | PASS |

Account id=1 remains PetSpot company (`org_id=129944345`, disconnected).

---

## Phase 4 — Default CV (blocked)

| Item | Result |
|------|--------|
| Declared path | `/home/sabry3/Sabry_Youssef_CV.pdf` |
| Readable on master host | **NO** — path does not exist (`/home/sabry3` home not present) |
| LinkedIn upload | not attempted |
| `linkedin.cv.version` created | no |

### How to unblock

Copy the PDF onto this host, then reply with the reachable path. Recommended:

```bash
mkdir -p /home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/linkedin_connector/docs/cv
# from the machine that has the file:
scp Sabry_Youssef_CV.pdf sabry@<master>:/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/linkedin_connector/docs/cv/Sabry_Youssef_CV.pdf
```

Or place it at any absolute path under `/home/sabry/...` and tell me the path.  
Do **not** commit the PDF if it contains personal data you do not want in git (we will attach Odoo-side only and keep it out of the commit unless you explicitly ask).

---

## Phase 5 — Controlled UAT

**Not run** — waiting on CV file on this host.

Will then: fixture senior Odoo job, score/dedupe, application pack through `pack_ready`/`approved`, intercept open-URL, schedule 3 unpublished personal drafts, re-prove isolation, keep UAT-marked records.

---

## Phase 6

- Evidence updated this file.
- Full suite re-run deferred until CV attach + controlled UAT complete (prior: 16/16 on 2026-08-01).
- Production untouched.

---

## Manual next step required

1. Make `Sabry_Youssef_CV.pdf` available on this master host.  
2. Reply with the absolute path (or confirm the recommended `linkedin_connector/docs/cv/` location).  

Then continue Phase 4–5 without live LinkedIn side effects.
