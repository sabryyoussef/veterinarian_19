# Single-Cohort Production Hub Cutover Pilot — Activation Report

**Date:** 2026-07-23  
**Design:** [`SINGLE_COHORT_HUB_CUTOVER_PILOT_DESIGN.md`](./SINGLE_COHORT_HUB_CUTOVER_PILOT_DESIGN.md)  
**Cohort:** Discuss channel **#10** only (`openlowtest` / `Testopenclow`)

---

## Final decision

**`SINGLE-COHORT HUB PILOT PASSED`**

**Next (design only, not started):** `READY TO DESIGN CONTROLLED DISCUSS HUB EXPANSION`

Campaign migration: **not started**. Channel #10 restored to **`shadow`**. All cutover flags **OFF**.

---

## Preflight

### Backup

| Item | Value |
|------|--------|
| Path | `.migration_backups/p4_hub_cohort_20260723T122339Z/pet_spot_elsahel.dump` |
| Size | 18M |
| `db_dump_ok` | 0 |
| Service after restart | **active** |

### Versions

| Module | Version |
|--------|---------|
| `whatsapp_hub` | `19.0.1.3.0` |
| `evolution_whatsapp_chat` | `19.0.1.12.0` |
| `integration_bridge_core` | `19.0.1.1.2` |

### Gate results

| Gate | Result |
|------|--------|
| Service active | PASS |
| Channel #10 `shadow` + JID `120363411424964076@g.us` | PASS |
| Channel #5 `shadow` | PASS |
| Hub-mode channels = 0 | PASS |
| Instance #1 = `sabry min` | PASS |
| Evolution `sabry min` **open** | PASS |
| Pending/processing `unified_bridge` = 0 | PASS |
| Channel #10 shadow all `matched` (10) | PASS |
| Conversation #8 discuss / sabry min / group JID | PASS |
| Fresh backup | PASS |

### T0 baselines

```text
unified_bridge_total=0
unified_bridge_pending=0
shadow_matched=11
shadow_other=0
hub_mode_ch=0
wa_log=13
wa_msg=15
conv8_msgs=10
```

Evidence: `hub_pilot_preflight.txt`, `hub_pilot_backup.txt`

---

## Activation

| Step | Change |
|------|--------|
| 1 | `whatsapp_hub.unified_outbound_purposes = discuss` |
| 2 | `unified_outbound_enabled=True`, `discuss_cutover_enabled=True` (still zero hub channels / zero jobs) |
| 3 | Instance #1 `unified_outbound_enabled=True`, `discuss_cutover_enabled=True` |
| 4 | Channel **#10** `wa_outbound_mode`: `shadow` → **`hub`** (#5 stayed `shadow`; hub-mode count=1) |

Evidence: `hub_pilot_run.txt` SNAP lines.

---

## Pilot 01 — `OpenLow Hub Cutover Pilot 01`

| Field | Value |
|-------|--------|
| `mail.message` | **11320** |
| Business key | `discuss:10:11320` |
| Canonical Hub message | **19** |
| Conversation | **8** |
| Outbound job | **1** (`unified_bridge`, `sent`, retry=0) |
| Provider ID | `3EB06D68816DC7D6CFD6CC` |
| Compat `wa.message.log` | **16** (`send_origin=hub_unified`) |
| Log → Hub | `hub_message_id=19` |
| Hub → Log | `wa_message_log_id=16` |
| Legacy `_send_via_evolution` | **0** |
| Hub transport | **1** (accepted) |
| `walog:*` duplicate | **0** |
| Result | **PASS** |

---

## Pilot 02 — `OpenLow Hub Cutover Pilot 02`

| Field | Value |
|-------|--------|
| `mail.message` | **11321** |
| Business key | `discuss:10:11321` |
| Canonical Hub message | **20** (new) |
| Conversation | **8** (reused) |
| Outbound job | **2** (`unified_bridge`, `sent`) |
| Provider ID | `3EB07360E4226E6C40D8F0` (unique) |
| Compat log | **17** → Hub **20** |
| Legacy | **0** |
| Result | **PASS** |

---

## Pilot 03 — `OpenLow Hub Cutover Pilot 03`

| Field | Value |
|-------|--------|
| `mail.message` | **11322** |
| Business key | `discuss:10:11322` |
| Canonical Hub message | **21** (new) |
| Conversation | **8** (reused) |
| Outbound job | **3** (`unified_bridge`, `sent`) |
| Provider ID | `3EB0896A630B01ACB59256` (unique) |
| Compat log | **18** → Hub **21** |
| Legacy | **0** |
| Result | **PASS** |

---

## Aggregate

| Metric | Value |
|--------|------:|
| Hub unified sends | **3** |
| Legacy `_send_via_evolution` | **0** |
| Unique provider IDs | **3** |
| Canonical Hub messages | **3** |
| Compatibility logs | **3** |
| Conversations | **1** (#8) |
| Canonical duplicates | **0** |
| Provider duplicates | **0** |
| `unified_bridge` jobs outside #10 | **0** |
| Other channels in `hub` | **0** |
| `integration.outbound.queue` delta | **0** |

Discuss log lines: `Outbound mode=hub` × 3 (no legacy “Sent to” via `_send_via_evolution`).

---

## Canonical convergence

All three compatibility logs:

- `send_origin=hub_unified`
- `hub_message_id` = matching canonical Hub id
- `mail_message_id` = source Discuss message
- Hub `business_key` remained `discuss:10:{mm}`
- Hub `wa_message_log_id` attached to same record
- No `walog:{id}` second canonical row

---

## Final safety state

```text
channel #10 = shadow
channel #5  = shadow
hub-mode channels = 0

whatsapp_hub.unified_outbound_enabled = False
whatsapp_hub.discuss_cutover_enabled  = False
whatsapp_hub.unified_outbound_purposes = discuss   # kept tightened (documented)

instance #1 unified_outbound_enabled = False
instance #1 discuss_cutover_enabled  = False

pending/processing unified_bridge for #10 = 0 (quarantine N/A; all sent)
Campaign path unchanged
```

Evidence: `hub_pilot_final_state.txt`

---

## Final decision

**`SINGLE-COHORT HUB PILOT PASSED`**

Recommended next step (not executed): **`READY TO DESIGN CONTROLLED DISCUSS HUB EXPANSION`**

Stopped after pilot + safe shadow restore. No Campaign migration. No permanent Hub mode left on.
