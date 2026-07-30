# PetSpot Fulfillment × Vetution — Manual Testing Guide

**Status:** Production = Shadow Mode only  
**Commit baseline:** `6bed0eb` / modules `petspot_fulfillment` 19.0.1.1.1 + `petspot_fulfillment_vetution` 19.0.1.4.0  
**Related:** [RUNBOOK_MASTER_EXECUTION.md](RUNBOOK_MASTER_EXECUTION.md) · [CANARY_READINESS_CHECKLIST.md](CANARY_READINESS_CHECKLIST.md) · [PHASE15A_SHADOW.md](PHASE15A_SHADOW.md)

Use this checklist for operator UAT in the Odoo UI. Tick each row Pass / Fail / N/A and note evidence (screenshot or record ID).

---

## 0. Hard rules (read first)

| Never do on Production | Why |
|---|---|
| Flip `auto_quote_enabled` to True | Canary not authorized |
| Set Chatwoot / Shopify / ShipBlu transport to `live` | Live writes unimplemented / blocked |
| Enable ShipBlu shipment creation or pickup automation | Track-only posture |
| Activate or copy `TEST-SYNTHETIC-E2E-NOT-FOR-COMMERCE` costs | Synthetic fixtures — not for commerce |
| Allowlist Production DB in `synthetic_policy_allowed_dbs` | Must stay `pet_spot_elsahel_test` only |
| Create a real ShipBlu AWB / message a real customer / publish Shopify prices | Out of scope for Shadow Mode |
| Treat WhatsApp screenshots as payment proof | Not trusted payment evidence |

**Environments**

| DB | URL / service | What you may test |
|---|---|---|
| Production `pet_spot_elsahel` | port 8027 | Shadow assessments, menus, allowlist/mapping UI, flag checks only |
| TEST `pet_spot_elsahel_test` | port 8028 | Full synthetic E2E with mocks (no live carrier/customer) |

---

## 1. Pre-flight (both environments)

Login as a user in **PetSpot Fulfillment User** (or Admin).

| # | Step | Expected | ☐ |
|---|---|---|---|
| 1.1 | Open **PetSpot Fulfillment → Vetution Bridge** | Menu loads; no traceback | |
| 1.2 | Open **Shadow Assessments**, **Mapping Reviews**, **Automation Allowlist**, **Landed Cost Policy**, **Vetution Data Health** | Each list/form opens | |
| 1.3 | Settings → Technical → System Parameters: search `petspot_fulfillment_vetution` | See flags below | |
| 1.4 | Confirm ShipBlu backend (ShipBlu menus / backend form) | `shipping_owner_mode = track_only`, creation OFF, pickup automation OFF | |

**Required ICP values (Production)**

| Key | Must be |
|---|---|
| `petspot_fulfillment_vetution.auto_quote_enabled` | `False` |
| `petspot_fulfillment_vetution.chatwoot_transport` | `mock` |
| `petspot_fulfillment_vetution.shopify_publish_transport` | `mock` |
| `petspot_fulfillment_vetution.shipblu_create_transport` | `mock` |
| `petspot_fulfillment_vetution.rfq_send_enabled` | `False` |
| `petspot_fulfillment_vetution.shipblu_package_size_verified` | `False` |
| `petspot_fulfillment_vetution.synthetic_policy_allowed_dbs` | `pet_spot_elsahel_test` (not Production DB name) |
| `petspot_fulfillment.automation_enabled` | `False` |

---

## 2. Production — Shadow Mode manual tests

### 2.1 Landed-cost policy (read-only review)

| # | Step | Expected | ☐ |
|---|---|---|---|
| 2.1.1 | Open **Landed Cost Policy** | Commercial policy active; synthetic policy **inactive** | |
| 2.1.2 | Open active commercial policy | `allow_auto_quotation`, `allow_customer_message`, `allow_supplier_po`, `allow_price_publish` all **False** | |
| 2.1.3 | Check `max_auto_delivery_subsidy` | `0` | |
| 2.1.4 | Check customer delivery charge / revenue rule | EGP **118** configured (order-level, not product COGS) | |
| 2.1.5 | Note incomplete cost rows (unknown packaging/fees/tax/etc.) | Document gaps — do **not** invent zeros | |

### 2.2 Mapping & allowlist

| # | Step | Expected | ☐ |
|---|---|---|---|
| 2.2.1 | Open **Automation Allowlist** | Production may be empty (OK for Shadow Mode) | |
| 2.2.2 | Search product `SHP-139-144` | **Not** on allowlist; no exact size → stays blocked | |
| 2.2.3 | Search product `SHP-472-1065` | Has `vetution_size_id` **3975** when mapped; only allowlist after exact proof | |
| 2.2.4 | Open **Mapping Reviews** | List loads; pending/confirmed/rejected visible if any | |
| 2.2.5 | Do **not** confirm a size by title match | Only exact Shopify variant ↔ Odoo ↔ Vetution size identity | |

### 2.3 Shadow assessment (safe on Production)

| # | Step | Expected | ☐ |
|---|---|---|---|
| 2.3.1 | Open an existing **Availability Inquiry** (or create a **manual** inquiry on a known SKU) | Inquiry saved | |
| 2.3.2 | Run Vetution / shadow assess action (button on inquiry or create assessment from Bridge) | **Shadow Assessment** created | |
| 2.3.3 | Open the assessment | Shows supplier cost, completeness, decision codes, blockers | |
| 2.3.4 | Check `eligible_future_automation` | Usually **False** until costs complete + allowlist + gates | |
| 2.3.5 | Confirm **no** new Sale Order / RFQ / Chatwoot send / ShipBlu AWB / Shopify price change | Side-effect free | |

**Side-effect spot-check (optional, Accounting/Inventory menus)**  
Note counts or last create dates for SO, PO, payments, stock moves, ShipBlu shipments before/after assess — must not increase from this shadow step alone.

### 2.4 Delivery economics (worksheet understanding)

| # | Step | Expected | ☐ |
|---|---|---|---|
| 2.4.1 | On a shadow assessment with delivery context (or TEST worksheet), confirm product price ≠ delivery charge | Delivery (e.g. 118) separate from product price | |
| 2.4.2 | Mentally apply Giza→North Coast with carrier ~196 vs charge 118 | Must **not** auto-pass; needs `DELIVERY_PRICE_REVIEW_REQUIRED` when engine run with those inputs | |

### 2.5 Menus that must stay idle on Production

Open each list; confirm empty or historical only — **do not** click “publish live”, “send live”, or “create AWB”:

| Menu | Production expectation |
|---|---|
| Quotation Ledger | Empty / no new auto quotes |
| Message Log | No live customer sends |
| Payment Trust / Payment Events | No new trusted payments from this UAT |
| Price Publish Queue | Mock only; do not approve-for-live |
| Mock ShipBlu AWBs | TEST-oriented; do not use as live create |
| Supplier Order Tasks | No real supplier order send |

---

## 3. TEST database — Synthetic E2E manual tests

**Only on `pet_spot_elsahel_test`.**  
Policy: `TEST-SYNTHETIC-E2E-NOT-FOR-COMMERCE` (activate for the session if needed; deactivate after).  
Transports stay **mock**. Never message a real customer.

### 3.1 Activate synthetic fixture (TEST only)

| # | Step | Expected | ☐ |
|---|---|---|---|
| 3.1.1 | Confirm ICP `synthetic_policy_allowed_dbs` includes `pet_spot_elsahel_test` | Allowlisted | |
| 3.1.2 | Open synthetic policy; set **Active** for UAT | Name clearly NOT FOR COMMERCE | |
| 3.1.3 | Deactivate other commercial policies temporarily if `get_active_policy` ambiguity | Only one active policy during UAT | |
| 3.1.4 | Ensure allowlist contains exact `SHP-472-1065` ↔ size **3975** | Allowed | |

### 3.2 Pickup path (happy path)

| # | Step | Expected | ☐ |
|---|---|---|---|
| 3.2.1 | Create availability inquiry: product `SHP-472-1065`, qty 1, fulfillment **store_pickup** | Inquiry created | |
| 3.2.2 | Run shadow assessment | `state` ok / eligible when costs + mapping fresh | |
| 3.2.3 | Create auto-quotation (TEST / synthetic path) | One ledger row; product price separate from delivery (pickup fee 0) | |
| 3.2.4 | Send template **quotation_ready** (mock transport) | Message Log `transport=mock`, `state=sent` | |
| 3.2.5 | Accept quotation | State accepted; price lock | |
| 3.2.6 | Register cash/store pickup payment trust | Payment accepted; case paid / manual_paid | |
| 3.2.7 | Create **draft** RFQ/PO only | Draft PO; never confirm/send to supplier API | |
| 3.2.8 | Synthetic Giza receipt (TEST) | Picking done into Haram/Giza stock location | |
| 3.2.9 | Store pickup complete / handover | Case completed; **no AWB** | |

### 3.3 Delivery path (mock AWB)

| # | Step | Expected | ☐ |
|---|---|---|---|
| 3.3.1 | Repeat lifecycle with fulfillment **shipblu_delivery** + trusted payment/COD policy | Gates pass only if delivery margin OK | |
| 3.3.2 | Create **mock** ShipBlu AWB | Tracking like `MOCK-…`; exactly one per case | |
| 3.3.3 | Attempt second AWB | Blocked (duplicate guard) | |
| 3.3.4 | Confirm live ShipBlu create still OFF | ICP mock / package-size unverified | |

### 3.4 Exception matrix (manual spot checks)

| # | Scenario | Expected | ☐ |
|---|---|---|---|
| 3.4.1 | Duplicate CTA / same message idempotency | One inquiry / one message log | |
| 3.4.2 | Stale supplier data (>2h for auto-quote) | Auto-quote blocked | |
| 3.4.3 | Missing mapping / no size | Mapping review / not eligible | |
| 3.4.4 | OOS offer | Unavailable / not eligible | |
| 3.4.5 | Incomplete real cost profile (set a cost to unknown) | Incomplete; no auto-quote | |
| 3.4.6 | Price change ~9% vs current | Within ±10% band (no excessive increase) | |
| 3.4.7 | Price change ~11% | Price review required | |
| 3.4.8 | Accept quote then supplier price moves | RFQ blocked / exception | |
| 3.4.9 | Negative product margin | Blocked | |
| 3.4.10 | Giza→North Coast cost 196 vs charge 118 | `DELIVERY_PRICE_REVIEW_REQUIRED` | |
| 3.4.11 | Duplicate quotation / payment / RFQ / AWB | Idempotent or hard block | |
| 3.4.12 | Expired quotation accept | Rejected; state expired | |
| 3.4.13 | Unsigned Paymob callback | Rejected | |
| 3.4.14 | Wrong payment amount | Rejected | |

### 3.5 After TEST UAT cleanup

| # | Step | Expected | ☐ |
|---|---|---|---|
| 3.5.1 | Deactivate synthetic policy | Inactive again | |
| 3.5.2 | Restore commercial TEST policy active if needed | One non-synthetic policy | |
| 3.5.3 | Leave all transports on **mock** | No live leftovers | |

---

## 4. ShipBlu operational checks (Production — track only)

| # | Step | Expected | ☐ |
|---|---|---|---|
| 4.1 | Backend: Track Only ON | Confirmed | |
| 4.2 | Shipment creation disabled | Confirmed | |
| 4.3 | Pickup automation disabled | Confirmed | |
| 4.4 | Existing AWB / tracking sync (if any live shipment) | Track/sync only; no new create from Odoo | |
| 4.5 | Giza pickup reference | Haram clinic, 451 Haram Street Nasr Eldin, ShipBlu pickup id **10067** | |
| 4.6 | Package-size IDs | Still **unverified** — do not invent API IDs from Shopify labels | |

---

## 5. Sign-off sheet

| Field | Value |
|---|---|
| Tester name | |
| Date | |
| Environment | ☐ Production Shadow · ☐ TEST Synthetic |
| Build / commit | |
| Overall result | ☐ Pass · ☐ Pass with notes · ☐ Fail |
| Blockers found | |
| Evidence location | `~/.cursor/evidence/…` (masked reports only; no raw dumps in Git/PR) |

**Production Shadow sign-off statement**

> I confirm Shadow Mode manual tests completed without enabling auto-quote, live messaging, Shopify publish, ShipBlu create, pickup automation, or supplier order send. Side effects were checked and no unintended SO/PO/payment/stock/AWB/customer message was created by this UAT.

Signature: ______________________ Date: __________

---

## 6. Quick reference — UI paths

```
PetSpot Fulfillment
 └── Vetution Bridge
      ├── Shadow Assessments
      ├── Mapping Reviews
      ├── Supplier Snapshots
      ├── Automation Allowlist
      ├── Landed Cost Policy
      ├── Ops Health
      ├── Auto-Quote Runs
      ├── Message Log / Message Templates
      ├── Payment Trust / Payment Events
      ├── Quotation Ledger
      ├── Price Publish Queue
      ├── Mock ShipBlu AWBs
      ├── Giza Receipts
      ├── Supplier Order Tasks
      └── Vetution Data Health
```
