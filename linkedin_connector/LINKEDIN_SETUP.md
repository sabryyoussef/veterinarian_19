# LinkedIn setup — PetSpot El Sahel company page posting

**Milestone:** Post from Odoo to the **PetSpot El Sahel LinkedIn company page** only (not personal feed).

| Item | Value |
|------|--------|
| Company page | [PetSpot El Sahel](https://www.linkedin.com/company/129944345/) |
| Company page ID | `129944345` |
| Author URN (API) | `urn:li:organization:129944345` |
| Posts appear in | Company admin → **Page posts → Published** |

---

## 1. LinkedIn Developer app — Products

Add **all three** products on [LinkedIn Developers](https://www.linkedin.com/developers/) → your app → **Products**:

| Product | Scopes | Purpose |
|---------|--------|---------|
| **Sign In with LinkedIn using OpenID Connect** | `openid`, `profile` | OAuth login + member id for connection |
| **Share on LinkedIn** | `w_member_social` | Base posting permission (required in OAuth) |
| **Community Management API** | `w_organization_social` | **Post as the company page** |

Without OpenID Connect → connection fails (no member id).  
Without Community Management API **Approved** → do not request `w_organization_social` (causes `unauthorized_scope_error`).  
After approval → add scope and reconnect; then company page posts work.

---

## 1b. Two-phase OAuth (important)

| Phase | When | Scopes in `.env` |
|-------|------|------------------|
| **A — Connect** | Community Management still pending | `openid profile w_member_social` |
| **B — Company posts** | Product shows **Added** / Approved | `openid profile w_member_social w_organization_social` |

If you see **`unauthorized_scope_error`** / *Scope "w_organization_social" is not authorized* → you are in Phase A. Remove `w_organization_social` from scopes, sync, reconnect.

---

## 2. Redirect URL

Register **exactly** in LinkedIn Developers → app → **Auth** → Redirect URLs:

**Local dev:**

```
http://127.0.0.1:8027/linkedin_connector/callback?db=pet_spot_elsahel
```

**Production (petspot.odoo.com):**

```
https://petspot.odoo.com/linkedin_connector/callback?db=petspot
```

You do **not** need to expose local Odoo to the internet if you test on the same machine (`127.0.0.1`).

---

## 3. Configure `.env`

Copy `linkedin_connector/.env.example` → `.env` and set:

```env
LINKEDIN_CLIENT_ID=your-client-id
LINKEDIN_CLIENT_SECRET=your-client-secret

LINKEDIN_PUBLIC_BASE_URL=http://127.0.0.1:8027
LINKEDIN_OAUTH_SCOPES=openid profile w_member_social
# After Community Management API is Approved, uncomment:
# LINKEDIN_OAUTH_SCOPES=openid profile w_member_social w_organization_social
LINKEDIN_ORGANIZATION_ID=129944345
LINKEDIN_ACCOUNT_NAME=PetSpot LinkedIn

ODOO_URL=http://127.0.0.1:8027
ODOO_DB=pet_spot_elsahel
ODOO_USERNAME=admin
ODOO_PASSWORD=admin
```

Sync into Odoo:

```bash
cd projects/pet_spot_elsahel/linkedin_connector
../../venv19/bin/python3 scripts/sync_credentials.py
```

---

## 4. Connect in Odoo

1. Open http://127.0.0.1:8027
2. **LinkedIn → Accounts → PetSpot LinkedIn**
3. Confirm **Company page ID** = `129944345`
4. Confirm **OAuth scopes** include `w_organization_social`
5. Click **Disconnect** (if already connected with old scopes)
6. Click **Connect** → sign in on LinkedIn → approve
7. Success page shows **LinkedIn connected!** with a person URN (used for OAuth only)

> **Important:** Adding Community Management API does **not** update an existing token. You must **Disconnect → Connect** after adding the product.

---

## 5. Verify token scopes

After reconnect, confirm the token includes organization scope:

```bash
../../venv19/bin/python3 scripts/test_connection.py
```

Look for:

```
token scopes: openid,profile,w_member_social,w_organization_social
org URN: urn:li:organization:129944345
```

If `w_organization_social` is missing → **Disconnect → Connect** again (Community Management API may still be pending approval).

---

## 6. Test company page post (milestone)

```bash
../../venv19/bin/python3 scripts/run_test_post.py
```

Or in Odoo: **LinkedIn → Accounts → Test Post**

Expected result:

- Script prints `SUCCESS — test post published to LinkedIn`
- Post text: *PetSpot El Sahel — Odoo company page test post at …*

Verify on LinkedIn:

https://www.linkedin.com/company/129944345/admin/page-posts/published/

---

## 7. Create scheduled posts from Odoo

After the test post works:

1. **LinkedIn → Posts → New**
2. Select account **PetSpot LinkedIn**
3. Write message, optional images
4. **Post Now** or **Schedule**

All posts use author `urn:li:organization:129944345` (company page, not personal feed).

---

## Troubleshooting

| Error | Cause | Fix |
|-------|--------|-----|
| `invalid_scope_error` | OpenID Connect or org scope not enabled on app | Add missing product in LinkedIn Developers, then reconnect |
| Token OK but no member id | OpenID Connect missing | Add OpenID Connect product; scopes: `openid profile …` |
| `unauthorized_scope_error` | `w_organization_social` requested before LinkedIn approved Community Management API | Use Phase A scopes only; wait for approval; then add org scope and reconnect |
| `403 ACCESS_DENIED` on `/author` | Token lacks `w_organization_social` | Complete Phase B (add scope + reconnect) |
| Post on personal feed, not company page | Old connector / no org id | Set `LINKEDIN_ORGANIZATION_ID=129944345`; upgrade module; reconnect |
| Token missing `w_organization_social` | Connected before adding Community Management | Disconnect → Connect after product is approved |
| `invalid_client` | Wrong client id/secret | Check `linkedin_connector/.env` |

---

## Scripts reference

| Script | Purpose |
|--------|---------|
| `scripts/sync_credentials.py` | Push `.env` → Odoo `linkedin.account` |
| `scripts/test_connection.py` | Odoo auth + LinkedIn app + token scope check |
| `scripts/run_test_post.py` | Publish one test post to company page |

---

## References

- [Share on LinkedIn](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin) — author must be person or organization URN
- [LinkedIn Developers](https://www.linkedin.com/developers/) — products and OAuth settings
