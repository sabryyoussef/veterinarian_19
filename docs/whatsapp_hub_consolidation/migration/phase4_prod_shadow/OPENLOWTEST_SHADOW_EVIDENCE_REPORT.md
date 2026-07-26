# OpenLowTest Production Shadow Evidence Report

**Date:** 2026-07-23  
**Scope:** Controlled Production **shadow** evidence collection only  
**Prior:** [`PROD_SHADOW_PILOT_REPORT.md`](./PROD_SHADOW_PILOT_REPORT.md)

---

## Final decision

**`SHADOW VALIDATION PASSED`**

**`READY TO DESIGN SINGLE-COHORT HUB CUTOVER PILOT`**

Hub cutover was **not** enabled. Campaign / Phase 5 were **not** started.

---

## OpenLowTest mapping

| Field | Value |
|-------|--------|
| User label | `openlowtest` |
| Evolution group subject | **`Testopenclow`** (exact WhatsApp subject on instance `sabry min`) |
| Group JID | **`120363411424964076@g.us`** |
| Evolution instance | `sabry min` |
| Hub group record | `whatsapp.group` **#1** (`prod-cutover-synth` — same JID; pre-existing) |
| Discuss channel | **#10** `WA Group: Testopenclow (openlowtest)` — **created** for this cohort |
| Channel `wa_phone` | full group JID `120363411424964076@g.us` |
| Routing mode before | n/a (new) → briefly `legacy` |
| Routing mode after | **`shadow`** |

### What was created / linked

1. **Created** Discuss channel `#10` with `channel_type=group`, `wa_phone=<group JID>`, admin member.
2. Set `wa_outbound_mode=shadow` on channel `#10` only.
3. Linked to existing Hub group `#1` by JID (no Hub transport flags enabled).
4. Did **not** rename Evolution group; documented alias `openlowtest` ↔ subject `Testopenclow`.

No other channels switched to Hub. Channel `#5` remains `shadow` from the earlier DM pilot.

---

## Controlled batch

| Item | Value |
|------|--------|
| Messages sent | **10** |
| Sequence | `OpenLow Shadow Evidence 01` … `10` |
| Path | Odoo Discuss `message_post` → `_send_whatsapp_discuss_message` → shadow → `_send_via_evolution` |
| Provider accepts | **10 / 10** (Evolution HTTP **201** each) |
| Duplicate provider IDs | **0** |
| Duplicate Hub messages | **0** |
| Hub unified transport calls | **0** (guarded) |
| New `unified_bridge` jobs | **0** |

Evidence: `openlowtest_batch.txt`, `openlowtest_batch_stderr.txt`

### Per-message observations

| Seq | mail.message | wa.log | whatsapp.message | shadow | provider id | class | conv |
|-----|-------------:|-------:|-----------------:|-------:|-------------|-------|-----:|
| 01 | 11310 | 6 | 9 | 2 | `3EB0921AB7BA930E95F586` | matched | 8 |
| 02 | 11311 | 7 | 10 | 3 | `3EB09826D2397214ED8856` | matched | 8 |
| 03 | 11312 | 8 | 11 | 4 | `3EB05A29A82EC1CBBB8126` | matched | 8 |
| 04 | 11313 | 9 | 12 | 5 | `3EB0B3AA3C4CE66158F7FF` | matched | 8 |
| 05 | 11314 | 10 | 13 | 6 | `3EB0B1309D5EF97B04DE90` | matched | 8 |
| 06 | 11315 | 11 | 14 | 7 | `3EB01DF8B989626521ED11` | matched | 8 |
| 07 | 11316 | 12 | 15 | 8 | `3EB0DEDEE31A5576A084B0` | matched | 8 |
| 08 | 11317 | 13 | 16 | 9 | `3EB0525248B7C74F1636AE` | matched | 8 |
| 09 | 11318 | 14 | 17 | 10 | `3EB0FE7FC4FB0D84BB0D95` | matched | 8 |
| 10 | 11319 | 15 | 18 | 11 | `3EB06243F94EF7B7E32549` | matched | 8 |

For every row: `purpose=discuss`, instance `sabry min`, remote JID `120363411424964076@g.us`, expected conversation identity **equals** actual.

---

## Shadow results (including prior Production sample)

| Metric | Value |
|--------|------:|
| Total shadow observations | **11** (1 prior DM + 10 OpenLow) |
| `matched` | **11** (**100%**) |
| All other mismatch classes | **0** |
| Hub transport calls | **0** |
| `unified_bridge` jobs | **0** |

---

## Canonical integrity (OpenLow batch)

| Metric | Result |
|--------|--------|
| Canonical messages created | **10** |
| Unique conversations | **1** (`whatsapp.conversation` **#8**) |
| Duplicate canonical records | **0** |
| Group conversation reuse | **Pass** — same instance + same group JID + `purpose=discuss` |

---

## Safety confirmation

```text
whatsapp_hub.unified_outbound_enabled = False
whatsapp_hub.discuss_cutover_enabled  = False
instance.unified_outbound_enabled     = False (0 true)
instance.discuss_cutover_enabled      = False (0 true)
hub-mode channels/groups              = 0
unified_bridge jobs                   = 0
Campaign path                         = unchanged (_send_via_evolution)
```

Final channel modes:

| Channel | Mode |
|---------|------|
| #5 Sabry Bridge Test (DM) | `shadow` |
| #10 Testopenclow / openlowtest (group) | `shadow` |

Preferred state kept: OpenLow remains **`shadow`** for continued harmless observation.

---

## Issues

None for this batch. Name clarification only: WhatsApp subject is **`Testopenclow`**, not the literal string `openlowtest`; JID mapping is definitive.

---

## Decision (exact)

**READY TO DESIGN SINGLE-COHORT HUB CUTOVER PILOT**

Do **not** enable Hub cutover in this step. Design-only readiness.
