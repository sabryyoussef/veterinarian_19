# Sabry SMTP Blocker — vendorah2 Preflight & Stop Report

**Date:** 2026-08-03  
**Company:** Sabry Odoo Development (id=3)  
**Required sender:** vendorah2@gmail.com  

## Verdict

```text
BLOCKED_VENDORAH2_GMAIL_REAUTH_REQUIRED
```

Canary was **not** retried for delivery because no valid Sabry-isolated SMTP authentication exists for `vendorah2@gmail.com`.

---

## Preflight findings (no duplicates created)

### `ir.mail_server`

| id | name | smtp_user | from_filter | auth | pass | gmail_refresh | active |
|----|------|-----------|-------------|------|------|---------------|--------|
| 1 | Gmail - vetelsahel@gmail.com | vetelsahel@gmail.com | vetelsahel@gmail.com | login | empty | empty | true |

- **No** existing SMTP record for `vendorah2@gmail.com`.
- **No** App Password configured on any outgoing server for vendorah2.
- PetSpot SMTP **not modified**.

### `mail.gmail.account` for vendorah2

| Field | Value (sanitized) |
|-------|-------------------|
| id | 9 |
| email | vendorah2@gmail.com |
| state | **error** |
| company_id | 1 (legacy connector row; not Sabry-provisioned) |
| outgoing_mail_server_id | null |
| refresh_token | present but **unusable** |
| last_error | **invalid_grant** |

Probe: `action_gmail_refresh_profile()` → fails with `invalid_grant`.  
Cannot provision OAuth SMTP (`action_provision_mail_servers` requires state=`connected`).

### Isolation notes

- `ir.mail_server` has **no** `company_id` column in this DB; isolation is via `from_filter` + explicit `mailing.mail_server_id` + Sabry mailing constraints (block `vetelsahel@gmail.com` on Sabry mailings).
- Draft mailings **1** and **3** updated to:
  - From: `"Sabry Odoo Development" <vendorah2@gmail.com>`
  - Reply-To: `vendorah2@gmail.com`
  - `mail_server_id`: empty (must **not** bind PetSpot server id=1)
  - `company_id`: 3
- Test list id=5 currently has **2** addresses: `vendorah2@gmail.com`, `abhorya@gmail.com` (not three). No third address invented.

---

## What was NOT done (by design)

- Did **not** create a broken vendorah2 SMTP row with dead OAuth tokens.
- Did **not** send canary mail (would fall back to PetSpot/vetelsahel path or fail auth).
- Did **not** change PetSpot SMTP.
- Did **not** touch the 864-partner audience.
- No credentials written to git/logs/evidence.

---

## Exact manual action required from Sabry

Choose **one** auth method, then notify the agent to resume SMTP provisioning + canary.

### Option A — Google App Password (recommended for SMTP login)

1. Sign in to Google as **vendorah2@gmail.com**.
2. Enable 2-Step Verification if not already on.
3. Google Account → Security → App passwords → create one labeled `Odoo Sabry SMTP`.
4. In Odoo (admin), create **Outgoing Mail Server**:
   - Name: `Gmail — vendorah2@gmail.com (Sabry)`
   - Host: `smtp.gmail.com`
   - Port: `587`
   - Encryption: `STARTTLS` / `starttls`
   - Authentication: `Username / Password` (`login`)
   - Username: `vendorah2@gmail.com`
   - Password: the **16-character App Password** (not the normal Gmail password)
   - From Filter: `vendorah2@gmail.com`
5. Test Connection in Odoo.
6. Assign that server as `mail_server_id` on Sabry mailing ids 1 and 3 only.
7. Do **not** change PetSpot server id=1.

### Option B — Gmail OAuth re-authorization

1. Open Odoo → Gmail Connector / Google Gmail settings.
2. Ensure Google Cloud OAuth client is configured for this Odoo instance (`google_gmail_client_id` / secret system parameters were **not** set at probe time; connector account 9 stores its own client fields — use the UI Connect flow).
3. On account **vendorah2** (id=9): run **Connect with Google** and complete consent for `gmail.send` (and related scopes).
4. Confirm account `state=connected` (not `error` / not `invalid_grant`).
5. Run **Provision mail servers** so an `ir.mail_server` with `smtp_authentication=gmail` and `from_filter=vendorah2@gmail.com` is created.
6. Re-assign Sabry company context on the connector account if UI allows (`company_id=3`).
7. Bind the new server to Sabry canary mailing only.

After either option succeeds, the agent will:

1. Verify SMTP test connection (no 535).
2. Retry **only** the internal canary (test list / mailing id=3).
3. Confirm inbox receipt where accessible.
4. Leave production audience untouched.

---

## Isolation confirmation (current)

| Check | Status |
|-------|--------|
| PetSpot SMTP id=1 unchanged | PASS |
| Sabry From/Reply-To set to vendorah2 | PASS (draft config) |
| Sabry not bound to vetelsahel server | PASS (`mail_server_id` empty) |
| Code still blocks vetelsahel From on Sabry mailings | PASS (existing constraint) |
| Valid Sabry SMTP for vendorah2 | **FAIL — blocker** |
| Canary delivered | **NOT ATTEMPTED** |

---

## Counts

| Metric | Value |
|--------|-------|
| SMTP reused | none |
| SMTP created | none |
| Auth method available | none valid |
| Canary attempted | 0 |
| Canary delivered | 0 |
| Canary failed | 0 (not sent) |
