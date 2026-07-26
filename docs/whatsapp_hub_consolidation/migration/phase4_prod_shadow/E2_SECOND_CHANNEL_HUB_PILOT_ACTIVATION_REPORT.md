# E2 Second-Channel Hub Pilot — Activation Report

**Date:** 2026-07-23  
**Design:** [`E2_SECOND_CHANNEL_HUB_PILOT_DESIGN.md`](./E2_SECOND_CHANNEL_HUB_PILOT_DESIGN.md)  
**Cohort:** Discuss channel **#5** (Sabry Bridge Test DM) added alongside ongoing **#10** Hub soak

---

## Final decision

**`E2 SECOND-CHANNEL HUB PILOT PASSED`**

**`TWO-CHANNEL HUB SOAK ACTIVE`**

- Channel **#5** remains **`hub`**
- Channel **#10** remains **`hub`** (unchanged)
- Allowlist remains **`10,5`**
- Global/instance capability flags remain **ON**
- Campaign unchanged (`_send_via_evolution`)
- E3 / Campaign migration: **not started**

---

## Preflight

### Backup

| Item | Value |
|------|--------|
| Path | `.migration_backups/p4_e2_ch5_20260723T125424Z/pet_spot_elsahel.dump` |
| Size | 18M |
| `db_dump_ok` | 0 |
| Production HTTP | **200** |

### Hard gate

All **PASS** (`e2_activation_preflight.txt`): Evolution `sabry min` active; #10 Hub healthy (last 3 jobs `sent`/retry=0); #5 shadow + matched≥10/mismatch=0; JID/`#7` stable; pending=0; allowlist=`[10]`; hub-mode=`{10}`; quarantine available; Campaign uses `_send_via_evolution`.

### T0 baselines

| Metric | Value |
|--------|--------|
| #10 / #5 mode | `hub` / `shadow` |
| Allowlist | `10` → `[10]` |
| Hub-mode IDs | `[10]` |
| Pending unified | 0 |
| Jobs #5 / #10 | 0 / 13 |
| Conv #7 / #8 msgs | 10 / 24 |
| `wa.message.log` / `whatsapp.message` | 36 / 38 |

---

## Activation

| Step | Result |
|------|--------|
| Allowlist | `10` → **`10,5`** (parsed `[10,5]`, set `{10,5}`) |
| Isolation probe | mail **11344**; legacy **1**; Hub tx **0**; #5 unified jobs **0**; mode still `shadow` |
| Flip #5 | `shadow` → **`hub`** |
| #10 | remained **`hub`** |
| Hub-mode set | **`{5,10}`** |
| Flags | unchanged (globals + instance #1 ON; purposes=`discuss`) |

Evidence: `e2_activation_run.txt` (`PROBE_OK`, `ACTIVATION_COMMITTED`).

---

## Pilot 01 — `Bridge Hub Pilot 01`

| Field | Value |
|-------|--------|
| `mail.message` | **11345** |
| Business key | `discuss:5:11345` |
| Canonical Hub message | **44** |
| Conversation | **7** |
| Outbound job | **15** (`unified_bridge`, `sent`, retry=0) |
| Provider ID | `3EB002722711287688137D` |
| Compat log | **41** (`send_origin=hub_unified`) |
| Legacy `_send_via_evolution` | **0** |
| Hub transport | **1** |
| Result | **PASS** |

## Pilot 02 — `Bridge Hub Pilot 02`

| Field | Value |
|-------|--------|
| `mail.message` | **11346** |
| Business key | `discuss:5:11346` |
| Canonical Hub message | **45** |
| Conversation | **7** |
| Outbound job | **16** (`unified_bridge`, `sent`, retry=0) |
| Provider ID | `3EB0C20D278D0C940860F2` |
| Compat log | **42** (`hub_unified`) |
| Legacy | **0** |
| Result | **PASS** |

## Pilot 03 — `Bridge Hub Pilot 03`

| Field | Value |
|-------|--------|
| `mail.message` | **11347** |
| Business key | `discuss:5:11347` |
| Canonical Hub message | **46** |
| Conversation | **7** |
| Outbound job | **17** (`unified_bridge`, `sent`, retry=0) |
| Provider ID | `3EB0E5205626796D709791` |
| Compat log | **43** (`hub_unified`) |
| Legacy | **0** |
| Result | **PASS** |

All three: instance `sabry min`; remote contains `201000059085`; Hub↔log convergence; no `walog:` twin; queue delta 0.

---

## Aggregate

| Metric | Value |
|--------|--------|
| Hub sends (#5 pilot) | **3** |
| Legacy sends | **0** |
| Unique provider IDs | **3** |
| Canonical Hub messages | **3** (44–46) |
| Compatibility logs | **3** (41–43) |
| Conversation reuse | **#7** only |
| Duplicates | **0** |
| Retries | **0** |
| Jobs outside allowlist | **0** |
| #10 job delta during pilot | **0** |

---

## Multi-cohort isolation

| Check | Result |
|-------|--------|
| #5 pilots → conversation #7 | **PASS** |
| #10 remains Hub; conversation #8 baseline | **PASS** (jobs10 delta 0) |
| Allowlist `{10,5}` / hub-mode `{5,10}` | **PASS** |
| No cross-linking / no non-allowlisted Hub jobs | **PASS** |
| Namespaces `discuss:5:*` vs `discuss:10:*` | **PASS** |

`ISOLATION_OK True`

---

## Final Production state

| Item | Value |
|------|--------|
| Channel #10 mode | **`hub`** |
| Channel #5 mode | **`hub`** |
| Allowlist | **`10,5`** |
| Hub-mode channel IDs | **`[5, 10]`** |
| Global unified / Discuss cutover | **True / True** |
| Instance #1 unified / Discuss | **True / True** |
| Purposes | `discuss` |
| Pending/processing unified | **0** |
| Campaign path | `_send_via_evolution` |

---

## Evidence files

- `e2_activation_backup.txt`
- `e2_activation_preflight.txt`
- `e2_activation_run.txt`
- `e2_activation_final_db.txt`

---

## Stop conditions

E3 not started. Campaign migration not started. No systemic rollback required.
