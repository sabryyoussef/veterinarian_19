# Sabry Canary Delivery Report

**Verdict:** `SABRY_OUTREACH_CANARY_DELIVERED_READY_FOR_PILOT_APPROVAL`

**Timestamp (UTC):** see CANARY_SEND.json / CANARY_INBOX_VERIFY.json

## SMTP

| Item | Value |
|------|-------|
| SMTP record | id=2 `Gmail - Sabry Odoo Development` (**reused**, created manually) |
| Username / from_filter | vendorah2@gmail.com |
| Auth | login + App Password (value never logged) |
| Connection test | `test_smtp_connection()` OK |
| PetSpot SMTP id=1 | unchanged (`vetelsahel@gmail.com`) |

## Canary binding

| Field | Value |
|-------|-------|
| Mailing id | 3 (draft after test send) |
| Company | 3 Sabry Odoo Development |
| From | "Sabry Odoo Development" \<vendorah2@gmail.com\> |
| Reply-To | vendorah2@gmail.com |
| Mail server | id=2 |
| List | id=5 Sabry — Sample Test Only only |
| Recipients | vendorah2@gmail.com, abhorya@gmail.com |
| CV | attachment 11503 |

Production mailing id=1 remains **draft**; 864-partner list was not used.

## Counts

| Metric | Count |
|--------|-------|
| Attempted | 2 |
| Delivered (Odoo chatter + Gmail Sent) | 2 |
| Failed | 0 |

## Validation

- Odoo chatter: successfully sent to both addresses
- Gmail Sent Mail: both messages present with correct From/Reply-To; no vetelsahel
- vendorah2 INBOX: self-addressed canary present with `Sabry_Youssef_CV.pdf` attached
- abhorya: accepted by Gmail (Sent To header); inbox not directly readable from this host
- CV download `/sabry/cv/download` HTTP 200 PDF; attachment present on received mail
- `/sabry/*` links HTTP 200; no PetSpot footer / vetelsahel on pages
- Unsubscribe: `List-Unsubscribe` + `List-Unsubscribe-Post` one-click headers present on delivered message (points at `/mailing/3/unsubscribe...`)
- No partner audience send
- No duplicate same-day Sent rows beyond the two intended recipients

## Next action

Pilot approval from Sabry before any partner wave. Do not launch mailing id=1 until approved.
