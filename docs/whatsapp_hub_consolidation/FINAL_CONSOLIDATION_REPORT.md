# WhatsApp Hub Consolidation — Final Closure Report

**Executed:** 2026-07-23  
**Branch:** `feature/devhub-modularization-whatsapp`  
**Authoritative architecture:** [`ARCHITECTURE.md`](./ARCHITECTURE.md)  
**Prior migration evidence:** `migration/P0_P2_REPORT.md`, `P3_P8_REHEARSAL_REPORT.md`, `P9_PRODUCTION_CUTOVER_REPORT.md`, `P10_TRAFFIC_ACTIVATION_REPORT.md`  
**Closure evidence root:** `migration/closure/`

---

## A. Final Status

`whatsapp_hub` is the canonical Odoo-side WhatsApp platform on Production.

- Production cutover (P9): **PASS WITH NON-BLOCKERS**
- Production traffic pilot (P10): **PASS WITH NON-BLOCKERS**
- Closure gap (`evolution_message_id`): **FIXED AND RE-PROVEN**
- Legacy modules: **remain installed** (deferred retirement)
- Dev Hub modular stack on Production: **not installed** (correct)
- Additional Production JIDs: **not enabled**
- Global outbound cutover: **not performed**

---

## B. Final Code Pin

| Item | Value |
|------|--------|
| Pre-closure pin (P3–P10) | `4ce0387d45c13eae347e459d1683ee3886da57f4` (`4ce0387`) |
| Closure commit | `c858c0730dfb01e308a2fbf4e0f72fe75f9588d4` (`c858c07`) |
| Branch | `feature/devhub-modularization-whatsapp` |
| Canonical tree | `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel` |

Closure code changes beyond `4ce0387`:

1. Hub: backfill `evolution_message_id` on Chatwoot-keyed duplicate ingest
2. Hub tests: Evolution id preserve + backfill coverage
3. Infra (outside Odoo git): bridge `source_id` / conversation attr update; n8n Build Hub Payload + Filter/Merge nodes

---

## C. Production State

| Item | Value |
|------|--------|
| DB | `pet_spot_elsahel` |
| Port | `8027` (`https://drpaws.ai`) |
| Service | `systemctl --user pet_spot_elsahel.service` — **active** |
| `whatsapp_hub` | installed `19.0.1.0.1` |
| Targeted modules stuck? | **None** (`to install` / `to upgrade` / `to remove` empty for scope) |
| Hub health | `{"ok": true, "module": "whatsapp_hub"}` |
| Bridge health | `{"ok": true}` |
| Clinic intake route | `/petspot/wa/intake` responds (OPTIONS 204) |
| n8n workflow | `chatwoot-ai-analysis` (`gKMYWKVT5FtUAFwB`) **active** |
| Pilot JID | `120363411424964076@g.us` only |
| Dev Hub intake (n8n) | **FORCED OFF** (observe-only) |

---

## D. Canonical WhatsApp Architecture

See [`ARCHITECTURE.md`](./ARCHITECTURE.md). Summary:

```text
EXTERNAL TRANSPORT
WhatsApp → Evolution → Bridge → Chatwoot → n8n

ODOO CANONICAL LAYER
→ whatsapp_hub

BUSINESS CONSUMERS
→ devhub_whatsapp
→ petspot_wa_intake / clinic modules
→ CRM / campaign modules (evolution_whatsapp_chat)
→ future consumers
```

---

## E. Final Data Model Ownership

| Feature | Classification |
|---------|----------------|
| Messages | **CANONICAL IN HUB** (`whatsapp.message`) |
| Groups / JIDs | **CANONICAL IN HUB** (`whatsapp.group`) — policy outside |
| Contacts / senders | **CANONICAL IN HUB** (`whatsapp.contact`) |
| Conversations | **CANONICAL IN HUB** (`whatsapp.conversation`) |
| Instances | **LEGACY COMPATIBILITY** (Hub target + `evolution.instance` still live) |
| Normalized ingest | **CANONICAL IN HUB** |
| Idempotency (message) | **CANONICAL IN HUB** (Chatwoot id preferred) |
| Outbound queue (WA) | **CANONICAL IN HUB** (`whatsapp.outbound.message`) — not globally adopted |
| Message status | **LEGACY COMPATIBILITY** (dual-write Hub + `wa.message.log`) |
| Attachments metadata | **CANONICAL IN HUB** (references only) |
| Campaigns / templates / Discuss | **STILL OWNED BY OLD MODULE** |
| Dev Hub / clinic business | **BUSINESS-SPECIFIC — KEEP OUTSIDE HUB** |

---

## F. Consumer Matrix

| Consumer | Relationship |
|----------|--------------|
| `devhub_whatsapp` | Uses Hub **directly** (`service_ingest_normalized` → `whatsapp_message_id`) — **not on Production** |
| `petspot_wa_intake` | Uses Hub **directly**; clinic fields stay on intake |
| `petspot_clinic_portal` | Hub via notify mixin / intake dependency |
| `petspot_vet_feedback` | Does **not** need Hub migration (DM notify) |
| `petspot_campaign_rewards` | Keep `integration.outbound.queue` for now |
| `evolution_whatsapp_chat` | Compat mirror + still owns CRM WA product |
| `integration_bridge_core` | Platform bridge; soft Hub status updates; token auth for Hub HTTP |
| CRM lead/Discuss WA | Keep in evolution/bridge — not Hub |

---

## G. Inbound Flow

```text
Evolution messages.upsert (fromMe=false)
  → bridge /webhook/evolution
  → Chatwoot message (source_id = Evolution id)
  → n8n chatwoot-ai-analysis
  → Build Hub Payload (pilot JID gate)
  → POST /whatsapp_hub/ingest
  → whatsapp.message
  → optional consumers (Dev Hub OFF on Production pilot)
```

Non-pilot JIDs: Hub ingest skipped; existing Chatwoot/n8n/OP paths unchanged.

---

## H. Outbound Flow

| Caller | Classification |
|--------|----------------|
| Clinic group notify | **MIGRATED TO HUB** (prefer) + Evolution fallback |
| Clinic DM / buttons / Chatwoot notify | **KEEP EXISTING FOR NOW** |
| CRM campaigns / wizards / Discuss | **KEEP EXISTING FOR NOW** |
| Campaign rewards | **KEEP EXISTING FOR NOW** |
| Hub outbound cron/UI | **MIGRATED TO HUB** |
| Dev Hub → `devhub_outbox` → Chatwoot/n8n | **KEEP EXISTING FOR NOW** (governed) |

No global Production outbound switch in this closure.

---

## I. Idempotency Strategy

1. Primary: Chatwoot message id → stable `dedupe_key`
2. Secondary: search by `chatwoot_message_id`
3. Evolution-only events: Evolution id in key when no Chatwoot id
4. Replay: `duplicate=true`, single row
5. Enrichment: missing `evolution_message_id` may be backfilled on duplicate without creating a second row

Business duplicates (intake fingerprints, campaign sends) remain consumer-owned.

---

## J. Evolution ID Mapping Fix

### Root cause

1. Bridge stored `evolution_message_id` on **conversation** custom attributes (often overwritten by later OP sticky patches).
2. Chatwoot message create did **not** persist Evolution id on the message.
3. n8n `Build Hub Payload` read only **sender** custom attributes → Hub rows missing Evolution id (P10 non-blocker).

### Fix (safest layers)

| Layer | Change |
|-------|--------|
| Bridge | Set Chatwoot message `source_id` = Evolution id; update conversation attrs with latest Evolution id; media path supports same |
| n8n | Pass `content_attributes` / `source_id` from webhook + API fetch; Hub payload prefers those, then conv/sender attrs |
| Hub | Backfill `evolution_message_id` on duplicate when empty |

### Proof (closure pilot)

| Field | Value |
|-------|--------|
| Marker | `WHATSAPP-HUB-EVOID-20260723T065927Z` |
| Evolution id | `CLOSUREEVO1784789967` |
| Chatwoot message | `14387` (`source_id` set) |
| Hub row | `whatsapp.message` **id=4** |
| Idempotency replay | `duplicate=true` twice; **count=1** |
| Side effects | intake/campaigns unchanged |

Evidence: `migration/closure/`.

Note: Chatwoot did not persist `content_attributes` for API-created messages in this environment; **`source_id` is the durable per-message carrier**.

---

## K. Compatibility Module Matrix

| Module | Final state now | Notes |
|--------|-----------------|-------|
| `integration_bridge_core` | **KEEP FULL** | Tokens, `/bridge/*`, Evolution instance, generic queue |
| `evolution_whatsapp_chat` | **KEEP FULL** | Campaigns, templates, Discuss, `wa.message.log` |
| `petspot_wa_intake` | **KEEP AS COMPATIBILITY** (business) | Clinic intake; Hub-linked |
| `petspot_clinic_portal` | **KEEP FULL** | Portal + notify |
| `petspot_vet_feedback` | **KEEP FULL** | Survey/coupon DMs |
| `petspot_campaign_rewards` | **KEEP FULL** | Rewards via bridge queue |

---

## L. Production Pilot Status

| Setting | Value |
|---------|--------|
| JID | `120363411424964076@g.us` (Testopenclow) |
| Hub ingest | **ON** (pilot only) |
| Dev Hub intake | **OFF** |
| Observe-only | **ON** |
| Non-pilot | Unchanged |
| Hub messages | ids 1–4 (synth/probe + live P10 + closure evo-id) |
| Recent failures / duplicate business actions | None observed for pilot |

---

## M. Test / Runtime Addons Path Status

| Environment | Status |
|-------------|--------|
| Production `:8027` | **Canonical-only** — PASS |
| Test `:8028` | Still uses `pet_spot_elsahel_test_activation_staging.conf` with **ACTIVE SHADOW** `releases/addons_overlay_staging/dev_session_hub` |
| Switch Test → `pet_spot_elsahel_test.conf` | **DEFERRED** — unrelated Dev Hub modularization dirty/untracked; not required for WhatsApp closure |

Path classification:

| Path | Class |
|------|--------|
| `projects/pet_spot_elsahel` | ACTIVE_RUNTIME |
| `releases/addons_overlay_staging` | ACTIVE_RUNTIME (Test only) |
| Other overlays / worktrees / `pet_spot_elsahel_dh_p0` | REFERENCE_ONLY / ARCHIVE_CANDIDATE / SAFE_TO_EXCLUDE_FROM_RUNTIME |
| Historical releases snapshots | Not deleted |

---

## N. Source / Git Cleanliness

| Class | State |
|-------|--------|
| Committed WhatsApp Hub stack (at `4ce0387`) | Clean through P10 |
| Closure Hub code + docs | Committed with this closure (see B) |
| Uncommitted Dev Hub work | **Preserved** (`devhub_*`, rewritten `dev_session_hub`) — do not discard |
| Untracked artifacts / evidence | Migration docs + `closure/` + UAT folders |
| Temporary runtime | Filestore rehearsal / PIDs — not product code |

Hub-related modules (`whatsapp_hub`, `evolution_whatsapp_chat`, `petspot_wa_intake`, `integration_bridge_core`) were clean at P10 pin; closure only touches Hub + docs (+ infra outside repo).

---

## O. Automated Test Results

| Suite | Result | Notes |
|-------|--------|-------|
| `whatsapp_hub` on `whatsapp_hub_fresh` | **0 failed, 0 errors** (4 tests) | Includes Evolution id tests |
| Bridge `custom_attributes_merge` | **3/3 OK** | unittest |
| Rehearsal `/whatsapp_hub,/integration_bridge_core,/evolution_whatsapp_chat` | 4 failed, 3 errors of 45 | **Pre-existing external HTTP mock blocks** (`External requests verboten`) on outbound queue + one campaign start assertion — **not Hub ingest regressions**; Hub subset passed |
| `petspot_wa_intake` | No dedicated tests in tree | Covered by P7/P9 link proofs |
| `devhub_whatsapp` | Not run on Production DB | Module uninstalled on Production; code links Hub |

Legitimate external skips: Odoo test harness blocks real HTTP to Chatwoot/Evolution mocks without patched requests.

---

## P. Production Smoke Results

| Check | Result |
|-------|--------|
| Odoo login `https://drpaws.ai/web/login` | 200 |
| Hub health | OK |
| Bridge health | OK |
| Clinic intake endpoint | Present |
| n8n workflow active | Yes |
| Pilot routing env | `WHATSAPP_HUB_PILOT_JIDS=120363411424964076@g.us` |
| Modules to install/upgrade/remove (scope) | None |
| Workers reloaded after Hub backfill fix | Yes (`systemctl --user restart`) |

---

## Q. Modules Safe to Keep

All currently installed WhatsApp-related Production modules are safe/required to keep:

`whatsapp_hub`, `integration_bridge_core`, `evolution_whatsapp_chat`, `petspot_wa_intake`, `petspot_clinic_portal`, `petspot_vet_feedback`, `petspot_campaign_rewards`

---

## R. Modules Safe to Slim Later

| Module | Slim condition |
|--------|----------------|
| `integration_bridge_core` | After callers use Hub for WA instance/outbound; keep tokens/non-WA |
| `evolution_whatsapp_chat` | After campaigns/Discuss/reporting rebased on Hub |
| `petspot_wa_intake` | After clinic intake is thinner Hub-event consumer |

---

## S. Modules NOT Safe to Uninstall

| Module | Why |
|--------|-----|
| `evolution_whatsapp_chat` | Owns `wa.campaign`, `wa.campaign.line`, `evo.wa.template`, Discuss WA |
| `integration_bridge_core` | Tokens, `/bridge/*`, generic queue, Evolution instance, CRM webhooks |
| `petspot_wa_intake` | Clinic HTTP + draft confirm; portal dependency |
| `petspot_clinic_portal` | Live clinic product |
| `petspot_vet_feedback` | Live survey/coupon flows |
| `petspot_campaign_rewards` | Live rewards |

**No uninstalls performed in this task.**

---

## T. Deferred Work

1. Stage 2 / Stage 3 JID expansion (approval-gated)
2. Enable Production Dev Hub intake (separate approval)
3. Global outbound migration to Hub
4. Campaign ownership move (explicitly blocked)
5. Legacy module uninstall / slim
6. Test addons_path → canonical-only (`pet_spot_elsahel_test.conf`) after Dev Hub modularization lands
7. Delete historical overlays/worktrees (not now)
8. Harden bridge→Chatwoot `content_attributes` if Chatwoot version supports durable storage (source_id already works)

---

## U. Stage 2 Traffic Expansion Recommendation

**Status: DISABLED — do not enable without approval.**

Pilot remains: `120363411424964076@g.us`.

Recommended next JIDs (low→higher risk), still disabled:

| Priority | JID | Name | Why |
|----------|-----|------|-----|
| 1 | `120363422104853335@g.us` | Dev Needed | Internal/dev traffic; high Hub value |
| 2 | `120363428056737368@g.us` | Asta development | Development group |
| 3+ | Client/project groups | (see map) | Only after Stage 2 stability |

Source: `/home/sabry/nextcloud/group-project-map.json` + `migration/closure/stage2_recommendation.json`.

---

## V. Final Verdict

```text
WHATSAPP HUB CONSOLIDATION COMPLETE WITH DEFERRED RETIREMENT
```

Consolidation is complete because:

- Hub is canonical for generic WhatsApp data/contracts
- Production Hub is installed and healthy
- Live pilot traffic persists into Hub (including Evolution id)
- Consumers can reference Hub (`whatsapp_message_id` / direct ingest)
- Idempotency works (`duplicate=true`, count=1)
- Compatibility routes remain operational
- Module ownership is documented
- Production runtime source is deterministic (canonical-only)
- Unsafe cleanup / uninstalls are explicitly deferred

---

## Module Disposition Table

| Module | Current Role | Final Role | Action Now | Future Action |
|--------|--------------|------------|------------|---------------|
| `whatsapp_hub` | Canonical WA platform | Canonical | Keep; pilot ingest ON | Expand JIDs only with approval |
| `integration_bridge_core` | Bridge / tokens / queue / instance | KEEP FULL → slim later | Keep installed | Slim WA-specific after migration |
| `evolution_whatsapp_chat` | CRM campaigns / Discuss / log | KEEP FULL | Keep; Hub mirror | Slim after CRM rebase |
| `petspot_wa_intake` | Clinic business intake | KEEP AS COMPATIBILITY | Keep; Hub-linked | Slim consumer later |
| `petspot_clinic_portal` | Clinic portal / notify | KEEP FULL | Keep | Prefer Hub outbound for more paths |
| `petspot_vet_feedback` | Survey/coupon WA | KEEP FULL | Keep | Optional Hub DM later |
| `petspot_campaign_rewards` | Rewards via bridge queue | KEEP FULL | Keep | Optional Hub outbound later |
| `devhub_whatsapp` | Dev Hub WA consumer | Consumer (not on Prod) | Do not install on Prod yet | Enable intake when approved |
| `devhub_outbox` | Governed Chatwoot outbox | KEEP EXISTING | Do not replace with Hub send | Keep governance path |
| `chatwoot_evolution_error_bridge` | Legacy CRM Chatwoot | Uninstalled on Prod | Leave uninstalled | Stay out of Hub graph |

---

## Hard Constraints Respected

- No module uninstalls
- No historical snapshot deletes
- No additional Production JIDs enabled
- No global outbound switch
- No Dev Hub modular stack on Production
- No Dev Hub redesign
- No campaign ownership move
- Compatibility routes preserved
- Historical data preserved
- Unrelated Dev Hub uncommitted work preserved
