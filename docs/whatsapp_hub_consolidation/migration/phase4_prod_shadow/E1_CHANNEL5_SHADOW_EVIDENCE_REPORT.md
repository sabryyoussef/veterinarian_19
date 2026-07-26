# Channel #5 Shadow Evidence Completion — E1 Continuation

**Date:** 2026-07-23  
**Scope:** Controlled Production **shadow** evidence on Discuss channel **#5** only  
**Non-goals:** No E2 design/activation; no #5 Hub; no #10/allowlist/flag changes; no Campaign migration

Evidence log: `e1_ch5_shadow_batch.txt`

---

## Final decision

**`CHANNEL #5 SHADOW VALIDATION PASSED`**

**`READY TO DESIGN E2 SECOND-CHANNEL PILOT`**

E2 was **not** designed or activated. Channel #5 was **not** added to the allowlist and remains **`shadow`**.

---

## Precheck

| Check | Result |
|-------|--------|
| Channel #10 mode | **`hub`** |
| Channel #5 mode | **`shadow`** |
| Allowlist raw / parsed | `10` / **`[10]`** |
| #5 in allowlist | **No** |
| Hub-mode channel count | **1** (#10 only) |
| #5 matched before | **2** |
| #5 mismatches before | **0** |
| Pending/processing unified | **0** |
| Global unified / Discuss cutover | `True` / `True` |
| Instance #1 unified / Discuss | `True` / `True` |
| Purposes | `discuss` |
| #5 Hub prerequisites | **Blocked** — not in `discuss_hub_allowed_channel_ids=[10]` |
| Campaign path | still `_send_via_evolution` |

`PRECHECK_OK`

Prior #5 conversation baseline: **#7** (`wa_phone` `201000059085`).

---

## Per-message evidence

Controlled Discuss `message_post` only. Hub transport patched to trap any call (zero invocations).

| seq | body | mail.message | wa.message.log | Hub msg | shadow row | provider ID | conv | class | legacy | Hub tx |
|-----|------|--------------|----------------|---------|------------|-------------|------|-------|--------|--------|
| 03 | Bridge Shadow Evidence 03 | 11336 | 32 | 35 | 14 | `3EB07CB5886C7820A900B8` | 7 | matched | 1 | 0 |
| 04 | Bridge Shadow Evidence 04 | 11337 | 33 | 36 | 15 | `3EB0B67DB8BAD2A1DB1E05` | 7 | matched | 1 | 0 |
| 05 | Bridge Shadow Evidence 05 | 11338 | 34 | 37 | 16 | `3EB0E45429E30BFFD29B45` | 7 | matched | 1 | 0 |
| 06 | Bridge Shadow Evidence 06 | 11339 | 35 | 38 | 17 | `3EB040B3E45490CF458535` | 7 | matched | 1 | 0 |
| 07 | Bridge Shadow Evidence 07 | 11340 | 36 | 39 | 18 | `3EB09077E3EA05D2D2BF7D` | 7 | matched | 1 | 0 |
| 08 | Bridge Shadow Evidence 08 | 11341 | 37 | 40 | 19 | `3EB078CC7EE70C590BF3B8` | 7 | matched | 1 | 0 |
| 09 | Bridge Shadow Evidence 09 | 11342 | 38 | 41 | 20 | `3EB061CB4C236A68D09650` | 7 | matched | 1 | 0 |
| 10 | Bridge Shadow Evidence 10 | 11343 | 39 | 42 | 21 | `3EB001DD0372393B8A1AF7` | 7 | matched | 1 | 0 |

Each row: `purpose=discuss`, instance `sabry min`, destination consistent with `201000059085`, `unified_bridge` jobs for #5 = **0**.

---

## Aggregate

| Metric | Value |
|--------|--------|
| Previous matched | **2** |
| New matched | **8** |
| Final matched | **10** |
| Mismatches | **0** |
| Legacy sends (batch) | **8** |
| Hub unified sends | **0** |
| `unified_bridge` jobs for #5 | **0** |
| Unique provider IDs | **8** |
| Unique Hub messages | **8** |
| Unique conversations | **#7** only |
| Duplicate providers / Hub msgs | **0** |

---

## Isolation (#10)

| Check | Result |
|-------|--------|
| #10 mode throughout / final | **`hub`** |
| Allowlist unchanged | **`10`** |
| #10 unified job delta | **0** |
| #10 `discuss:10:*` message delta | **0** |
| Hub-mode count | **1** |
| Capability flags unchanged | globals + instance #1 remain **ON** for #10 soak |

---

## Final configuration

| Item | Value |
|------|--------|
| Channel #10 | **`hub`** |
| Channel #5 | **`shadow`** |
| Allowlist | **`10`** |
| Global unified / Discuss cutover | **True / True** |
| Instance #1 unified / Discuss | **True / True** |
| Purposes | `discuss` |
| Unified jobs for #5 | **0** |
| Campaign | `_send_via_evolution` (unchanged) |

---

## Stop conditions honored

- E2 not designed or activated  
- #5 not switched to Hub / not allowlisted  
- #10 routing and soak flags untouched  
- Campaign migration not started  
