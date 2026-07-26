# E1 Extended Production Hub Soak — Completion Report

**Date:** 2026-07-23  
**Cohort:** Discuss channel **#10** only (`openlowtest` / `Testopenclow`)  
**Design baseline:** [`CONTROLLED_DISCUSS_HUB_EXPANSION_DESIGN.md`](./CONTROLLED_DISCUSS_HUB_EXPANSION_DESIGN.md)

---

## Final decision

**`E1 EXTENDED HUB SOAK PASSED`**

- Channel **#10 remains in Hub extended soak** (`wa_outbound_mode=hub`)
- Allowlist remains exactly **`10`**
- Channel **#5 remains `shadow`** (not activated)
- Campaign migration: **not started**
- E2: **not started**

**E2 recommendation:** do **not** yet declare `READY TO DESIGN E2 SECOND-CHANNEL PILOT` — channel #5 shadow matched count is **2** (needs ≥10 matched before E2 design).

---

## Safety hardening

### Allowlist (`whatsapp_hub.discuss_hub_allowed_channel_ids`)

| Item | Detail |
|------|--------|
| ICP | `whatsapp_hub.discuss_hub_allowed_channel_ids` (default empty) |
| Parser | `_parse_discuss_hub_allowlist(env)` in `evolution_whatsapp_chat/models/discuss_channel.py` |
| Enforcement | `_wa_hub_cutover_prerequisites` — required whenever Discuss cutover is ON |
| Fail-closed | Empty / missing → deny all Hub Discuss; malformed → deny; channel not listed → deny |
| Empty ≠ allow-all | Confirmed — Production empty allowlist blocks Hub transport |
| No legacy fallback | Hub mode with failed prerequisites returns pre-admission error only |

### Quarantine service

```python
env["whatsapp.outbound.message"].service_quarantine_discuss_channel(channel_id, reason="...")
```

| Job state | Behavior |
|-----------|----------|
| `pending` (incl. retry scheduled) | → `cancelled`, clear `next_retry_at`, preserve canonical message |
| `processing` + provider ID | → treat as `sent` (no cancel) |
| `processing` without provider ID | → `cancelled` as **uncertain**, clear retry |
| `sent` | unchanged |
| `failed` | unchanged (no legacy resend) |
| Idempotent | re-run counts `already_cancelled` / `already_sent` |

Admin button: **Quarantine Hub Outbound Jobs** on Discuss WA form (`base.group_system`).

### Files changed

| File | Change |
|------|--------|
| `whatsapp_hub/data/whatsapp_hub_outbound_flags.xml` | Allowlist ICP |
| `whatsapp_hub/models/whatsapp_outbound.py` | `service_quarantine_discuss_channel` |
| `whatsapp_hub/tests/test_whatsapp_outbound_quarantine.py` | Quarantine tests |
| `whatsapp_hub/tests/__init__.py` | Import quarantine tests |
| `whatsapp_hub/__manifest__.py` | `19.0.1.4.0` |
| `evolution_whatsapp_chat/models/discuss_channel.py` | Allowlist parse + prerequisites + admin action |
| `evolution_whatsapp_chat/views/discuss_channel_wa_views.xml` | Quarantine button |
| `evolution_whatsapp_chat/tests/test_whatsapp_discuss_phase4.py` | Allowlist helpers + E1 cases |
| `evolution_whatsapp_chat/__manifest__.py` | `19.0.1.13.0` |

### Module versions

| Module | Before | After |
|--------|--------|-------|
| `whatsapp_hub` | `19.0.1.3.0` | **`19.0.1.4.0`** |
| `evolution_whatsapp_chat` | `19.0.1.12.0` | **`19.0.1.13.0`** |
| `integration_bridge_core` | `19.0.1.1.2` | `19.0.1.1.2` (unchanged) |

### Tests / Test UAT

| Suite | Result |
|-------|--------|
| `whatsapp_discuss_p4` + `whatsapp_e1_quarantine` + `whatsapp_hub` | **0 failed, 0 errors / 49 tests** |
| Allowlist allow / deny / empty fail-closed / shadow / legacy / campaign path | PASS |
| Quarantine pending / retry / sent / idempotent / isolation / uncertain | PASS |
| Test UAT (`e1_test_uat.txt`) | Empty allowlist fail-closed; allowlisted OK; #5-style deny; quarantine cancels pending; safe restore |

Note: `TestWaCampaignStateMachine` has pre-existing race failures (campaign completes instantly); Phase 4 `test_21_campaign_still_uses_legacy` remains green. Campaign code still imports `_send_via_evolution`.

---

## Production preflight

### Backup

| Item | Value |
|------|--------|
| Path | `.migration_backups/p4_e1_soak_20260723T124022Z/pet_spot_elsahel.dump` |
| Size | 18M |
| `db_dump_ok` | 0 |
| Service after upgrade restart | **active** (port 8027 HTTP 200) |

### Baselines (pre-upgrade)

- hub-mode channels = **0**
- #10 / #5 = **shadow**
- global + instance unified/Discuss cutover = **OFF**
- `unified_outbound_purposes = discuss`
- pending/processing `unified_bridge` = **0**
- prior pilot jobs 1–3 remain `sent`

### Post-upgrade safe gate

- Flags OFF; allowlist ICP present empty; #10/#5 shadow; hub-mode = 0
- Shadow regression on #10: **1 legacy**, **0** unified delta (`REGRESSION_OK`)

---

## E1 activation

| Step | Value |
|------|--------|
| `unified_outbound_purposes` | `discuss` |
| `discuss_hub_allowed_channel_ids` | **`10`** → parse **`[10]`** |
| Global unified | `True` |
| Global Discuss cutover | `True` |
| Instance #1 `sabry min` unified + Discuss | `True` / `True` |
| #10 mode | `shadow` → **`hub`** |
| #5 mode | **`shadow`** (unchanged) |
| Hub-mode count | **1** |
| Deny #5 dry-check | Fail closed: not in allowlist (mode not changed) |

Evidence: `e1_soak_run.txt` SNAP / `ACTIVATION_COMMITTED`

---

## E1 soak results

Controlled Discuss `message_post` only (`OpenLow Hub Soak 01`–`10`). Zero `_send_via_evolution`. Conversation **#8** reused. JID `120363411424964076@g.us`. Instance `sabry min`.

| seq | mail.message | Hub msg | outbound job | provider ID | compat log | conv | retries | legacy |
|-----|--------------|---------|--------------|-------------|------------|------|---------|--------|
| 01 | 11325 | 24 | 5 | `3EB0A279C304A9D0929044` | 21 | 8 | 0 | 0 |
| 02 | 11326 | 25 | 6 | `3EB0590A4C9EE48064D9D1` | 22 | 8 | 0 | 0 |
| 03 | 11327 | 26 | 7 | `3EB09F5EF5F266A3A07D16` | 23 | 8 | 0 | 0 |
| 04 | 11328 | 27 | 8 | `3EB0A70F68599108CA1A8F` | 24 | 8 | 0 | 0 |
| 05 | 11329 | 28 | 9 | `3EB0B6E9B558C4C24F2495` | 25 | 8 | 0 | 0 |
| 06 | 11330 | 29 | 10 | `3EB0070288D9B14B65B2B1` | 26 | 8 | 0 | 0 |
| 07 | 11331 | 30 | 11 | `3EB0C15BE49980FF7FFA99` | 27 | 8 | 0 | 0 |
| 08 | 11332 | 31 | 12 | `3EB0815263ED014A6E3AA8` | 28 | 8 | 0 | 0 |
| 09 | 11333 | 32 | 13 | `3EB06B15B0EE71A4C1CCF7` | 29 | 8 | 0 | 0 |
| 10 | 11334 | 33 | 14 | `3EB0DF76F5AEE1C5330D0C` | 30 | 8 | 0 | 0 |

Each row: business key `discuss:10:{mail_id}`; `send_origin=hub_unified`; Hub↔log convergence; no `walog:` twin; no bridge queue delta.

---

## Aggregate

| Metric | Value |
|--------|--------|
| Additional successful Hub sends | **10 / 10** |
| Unique Hub messages | 10 |
| Unique provider IDs | 10 |
| Legacy leakage | **0** |
| Duplicate business keys / provider IDs | **0** |
| Canonical duplicates | **0** |
| Failures / retries | **0** |
| Jobs outside allowlist | **0** |
| Conversation reuse | **#8** only |
| Wrong JID / instance | **0** |

---

## #5 shadow progress

| Item | Value |
|------|--------|
| Previous matched (`channel_id=5`) | **1** |
| New observation | `OpenLow E1 Shadow Progress 01` → mail **11335**, classification **matched**, legacy **1**, Hub transport **0** |
| Final matched | **2** |
| Mismatches | **0** |
| Mode | remains **`shadow`** |

Insufficient for E2 (≥10 matched required).

---

## Quarantine readiness

| Check | Result |
|-------|--------|
| Service present on Production | Yes |
| Dry-run on #10 | `jobs_found=13`, `already_sent=13`, `cancelled=0`, `uncertain=0` |
| Test UAT pending cancel | Verified |
| Rollback sequence documented | #10→shadow → quarantine → (optional) clear allowlist → disable instance → disable global |

Changing #10 to shadow alone does **not** stop admitted pending Hub jobs — quarantine remains mandatory on rollback.

---

## Final Production state

| Item | Value |
|------|--------|
| Channel #10 mode | **`hub`** (continued approved E1 soak) |
| Channel #5 mode | **`shadow`** |
| Allowlist | **`10`** |
| Global unified | **True** |
| Global Discuss cutover | **True** |
| Instance #1 unified / Discuss | **True / True** |
| Hub-mode channel count | **1** |
| Pending/processing unified jobs | **0** |
| `unified_outbound_purposes` | `discuss` |
| Campaign path | still `_send_via_evolution` |

---

## Evidence files

- `e1_prod_preflight.txt`, `e1_prod_backup.txt`, `e1_upgrade_prod.log`, `e1_versions_after.txt`
- `e1_post_upgrade_safe.txt`, `e1_test_uat.txt`, `e1_test_suite_rerun.log`
- `e1_soak_run.txt`, `e1_soak_rows.jsonl`, `e1_final_state.txt`

---

## Stop conditions honored

- No Hub activation of channel #5  
- No additional Discuss channels  
- No Campaign migration / sending changes  
- No global Discuss expansion beyond allowlisted #10  
