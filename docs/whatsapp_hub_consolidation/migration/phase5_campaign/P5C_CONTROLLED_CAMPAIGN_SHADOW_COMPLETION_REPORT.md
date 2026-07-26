# P5C — Controlled Campaign Shadow — Completion Report

**Date:** 2026-07-23  
**Decision:** `P5C CONTROLLED CAMPAIGN SHADOW PASSED`  
**Next (not started):** `READY TO DESIGN P5D CONTROLLED CAMPAIGN HUB PILOT`

Design: [`PHASE5_CAMPAIGN_HUB_MIGRATION_DESIGN.md`](./PHASE5_CAMPAIGN_HUB_MIGRATION_DESIGN.md)

---

## Shadow implementation

### Call graph

```text
wa.campaign._process_campaign_queue
  → resolve_outbound_route → shadow
  → _process_campaign_queue_shadow
       → (replay guard) find_completed_for_line / legacy_send_completed
       → service_preview_campaign_line  # no Hub create
       → _shadow_legacy_send_one_line   # _send_via_evolution OR bridge queue
       → whatsapp.campaign.shadow.classify_and_record
```

Hard rule enforced: **Shadow = observe and compare, never Hub-send.**

### Files changed

| Area | Path |
|------|------|
| Shadow processor | `evolution_whatsapp_chat/models/wa_campaign.py` |
| Preview API | `whatsapp_hub/models/whatsapp_campaign_hub_routing.py` |
| Evidence model | `whatsapp_hub/models/whatsapp_campaign_shadow.py` |
| Ops UX | `whatsapp_hub/views/whatsapp_campaign_shadow_views.xml` |
| Tests | `whatsapp_hub/tests/test_whatsapp_campaign_shadow.py` |
| Test import | `whatsapp_hub/tests/__init__.py` |

### Module versions

| Module | Version |
|--------|---------|
| `whatsapp_hub` | **19.0.1.8.0** |
| `evolution_whatsapp_chat` | **19.0.1.17.0** |

---

## Preview

`whatsapp.campaign.hub.routing.service_preview_campaign_line(campaign, line)`

### Candidate fields

* `business_key` = `campaign:{campaign_id}:{line_id}` (proposed only)
* destination / normalized `remote_jid`
* instance_id / instance_reference
* purpose / source_app = `campaign`
* partner / lead / campaign / line ids
* rendered body + body_hash
* message_type = text
* priority = 3
* expected_conversation_identity_key (when resolvable)
* eligibility + classification + errors

### No-send guarantees

Preview does **not**:

* create `whatsapp.message`
* create `whatsapp.outbound.message`
* reserve `campaign:*` as a sendable Hub message
* call Hub transport / bridge queue
* modify Campaign line status

Shadow does **not** require Campaign cutover, allowlist, instance Campaign cutover, or `campaign` in `unified_outbound_purposes`.

---

## Evidence model

`whatsapp.campaign.shadow` records structured comparison evidence.

### Key fields

campaign_id, campaign_line_id, partner_id, destination, normalized_jid, candidate/actual instance, candidate business key, body previews/hashes, eligibility, legacy_transport (`immediate` / `bridge_queue` / `none`), legacy provider message id, wa.message.log id, bridge queue id, mirrored Hub message, `legacy_send_completed`, classification, mismatch_reason, create_date.

### Classifications

`matched`, `unsupported_message_type`, `missing_instance`, `invalid_destination`, `has_attachments`, `body_mismatch`, `instance_mismatch`, `destination_mismatch`, `campaign_identity_mismatch`, `provenance_mismatch`, `conversation_mismatch`, `legacy_queue_limited_evidence`, `validation_error`, `legacy_only`, `replay_skipped`

**Note:** `walog:*` vs `campaign:*` business keys are **not** treated as identity mismatches (legacy-first shadow traffic).

---

## Immediate-mode shadow

1. Preview Hub candidate  
2. Legacy `_send_via_evolution` exactly once  
3. `wa.message.log` (+ observational Hub mirror when compat runs)  
4. Classify evidence (strong: destination, body, campaign/line provenance, instance when mirror present)

Evidence quality: **high** — provider id + log + optional mirror available synchronously.

---

## Queue-mode shadow

1. Preview Hub candidate  
2. Preserve legacy `integration.outbound.queue` enqueue semantics  
3. Classify `legacy_queue_limited_evidence` when provider/log not yet present  
4. Optional later `reconcile_queue_evidence(line_id)` when log appears  

Does not create Hub outbound jobs. Does not falsely require immediate provider evidence.

---

## Replay protection

* Guard identity: prior shadow row with `legacy_send_completed=True` for the same `campaign_line_id`
* Unintentional processor re-run: **no second provider send**; append `replay_skipped` evidence row
* Prior `matched` rows remain queryable (replay is append-only)
* Does **not** reserve future Hub `campaign:*` send keys

Manual retry after a true failed send (no `legacy_send_completed`) remains possible via normal pending-line semantics.

---

## Tests

| Suite | Result |
|-------|--------|
| `whatsapp_p5c_campaign` | **0 failed / 14** |
| `whatsapp_p5a_campaign` + `whatsapp_p5b_campaign` | **0 failed / 27** |
| `whatsapp_discuss_p4` + `whatsapp_e1_quarantine` | **0 failed / 23** |

---

## Test UAT

| Scenario | Result |
|----------|--------|
| A — Immediate shadow matched | PASS (legacy 1 / Hub 0 / matched) |
| B — Ten-line controlled batch | PASS (10 sends, 10 matched, 0 Hub jobs) |
| C — Replay | PASS (0 duplicate sends; replay_skipped appended) |
| D — Deliberate body mismatch | PASS (`body_mismatch`) |
| E — Queue-mode shadow | PASS (`legacy_queue_limited_evidence`) |
| F — Attachments | PASS (no Hub transport; `has_attachments`) |
| G — Hub regression (P5B) | PASS |
| H — Discuss regression | PASS |

Test Campaign modes restored to `legacy` after UAT. Flags remained OFF / purposes=`discuss`.

---

## Production shadow campaign

| Item | Value |
|------|-------|
| Backup | `backups/pet_spot_elsahel_pre_p5c_20260723T145426Z.dump` |
| Campaign ID / name | **16** / `P5C Controlled Campaign Shadow (PROD)` |
| Recipients | **10** dedicated test partners (not customer bulk) |
| Send mode | `immediate` |
| `wa_outbound_mode` | `shadow` (left shadow for continued observation) |
| Observations | 20 rows (10 matched + 10 replay_skipped) |
| Matched | **10** |
| Mismatch | **0** |
| Legacy sends | **10** (provider mocked in shell — no customer WhatsApp spam; path = real shadow processor) |
| Hub transport calls | **0** |
| Hub Campaign jobs delta | **0** |
| Duplicate sends on replay | **0** |
| Other Campaigns | all remain `legacy` |

Provider transport was intentionally mocked on Production to avoid sending to synthetic test numbers while still exercising the live shadow processor, evidence model, and Hub-zero guarantees. Test DB UAT already validated the same path end-to-end under controlled conditions.

---

## Production safety

| Control | Value |
|---------|-------|
| Campaign cutover | **False** |
| Campaign allowlist | **empty** |
| Instance Campaign cutover | **False** |
| `unified_outbound_purposes` | **discuss** |
| Normal Campaigns | **legacy** |
| Discuss #5 / #10 | **hub** |
| Discuss allowlist | **10,5** |
| purpose=campaign Hub jobs | **0** |
| Discuss health | **healthy** (rechecked; #5/#10 hub, allowlist `10,5`) |

---

## Final decision

**P5C CONTROLLED CAMPAIGN SHADOW PASSED**

Recommendation: `READY TO DESIGN P5D CONTROLLED CAMPAIGN HUB PILOT`

P5D was **not** started. Production Campaign Hub remains **OFF**. No Campaign was added to the Hub Campaign allowlist. `campaign` was **not** added to Production `unified_outbound_purposes`.
