# Phase 4 Production Discuss Shadow Pilot Report

**Date:** 2026-07-23  
**Scope:** Limited Production **shadow** pilot only (NOT Hub cutover)  
**Prior Test baseline:** [`../phase4/PHASE4_COMPLETION_REPORT.md`](../phase4/PHASE4_COMPLETION_REPORT.md)

---

## Confirmations (hard constraints)

| Constraint | Status |
|------------|--------|
| No Production channel in `hub` mode | **Confirmed** |
| `whatsapp_hub.unified_outbound_enabled` | **False** |
| `whatsapp_hub.discuss_cutover_enabled` | **False** |
| Instance unified / discuss cutover flags | **OFF** (0 instances with flags true) |
| Hub unified outbound transport used | **No** (0 `unified_bridge` jobs; probe guard = 0 calls) |
| Campaign cutover / Campaign send changes | **Not started / unchanged** |
| Legacy transport sole WhatsApp sender | **Confirmed** (`_send_via_evolution`, Evolution HTTP 201) |

---

## 1. Preflight

### Production identity

| Item | Value |
|------|--------|
| DB | `pet_spot_elsahel` |
| Service | `pet_spot_elsahel.service` (port **8027**) |
| Addons path | `…/projects/pet_spot_elsahel` (same tree as Test Phase 4) |
| Disk manifests before upgrade | Hub `19.0.1.3.0`, chat `19.0.1.12.0`, bridge `19.0.1.1.2` |
| Git HEAD (addons tree) | `5d627a7e4b6ec4a29928dfd3c57f3fcf000f66cc` (working tree also has later Phase 4 module files on disk) |

### Versions before upgrade

| Module | Version |
|--------|---------|
| `whatsapp_hub` | `19.0.1.0.1` |
| `evolution_whatsapp_chat` | `19.0.1.10.1` |
| `integration_bridge_core` | `19.0.1.1.1` |

### ICP / flags before (no Phase 4 ICPs yet)

- No `whatsapp_hub.unified_outbound_enabled` / `discuss_cutover_enabled` rows yet (pre–Phase 3/4 schema).
- Evolution configured via ICP singleton (`integration_bridge.evolution_instance=sabry min`, local Evolution URL). **API key redacted in evidence.**

### Instances before

- `whatsapp.instance`: **0 rows**
- `evolution.instance`: **0 rows** (ICP singleton path)

### Discuss WA channels before

| ID | Name | Phone | Partner | Last outbound |
|----|------|-------|---------|---------------|
| 5 | WA: كريم ايهاب الساحل 2022 | `201000059085` | Sabry Bridge Test | 2026-06-19 |

Only **one** Production WA Discuss channel existed.

### Counts / queues before

| Metric | Count |
|--------|------:|
| `whatsapp.message` | 4 |
| `wa.message.log` | 2 |
| `whatsapp.outbound.message` | 0 |
| `whatsapp.conversation` | 3 |
| Bridge queue `sent` | 51 |
| Bridge queue `failed` | 76 (historical; **no pending** active WA Hub outbound) |
| Provider ID duplicates | 0 |

Service was **active** and healthy enough for a controlled upgrade (no pending unified outbound; historical bridge failures noted, not blocking shadow).

### Backup / snapshot evidence

| Item | Path / result |
|------|----------------|
| Backup root | `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/.migration_backups/p4_shadow_pilot_20260723T113020Z/` |
| DB dump | `pet_spot_elsahel.dump` (**17M**, `pg_dump -Fc`, `db_dump_ok=0`) |
| Filestore | live path retained (`348M`); not fully duplicated (DB dump is primary rollback for this schema upgrade) |
| Evidence file | `backup_paths.txt` |

Service stopped before dump/upgrade.

Evidence: `preflight.txt`, `backup_paths.txt`

---

## 2. Upgrade

### Modules upgraded

| Module | Before | After |
|--------|--------|-------|
| `whatsapp_hub` | `19.0.1.0.1` | **`19.0.1.3.0`** |
| `evolution_whatsapp_chat` | `19.0.1.10.1` | **`19.0.1.12.0`** |
| `integration_bridge_core` | `19.0.1.1.1` | **`19.0.1.1.2`** |

Command: `-u whatsapp_hub,evolution_whatsapp_chat,integration_bridge_core --stop-after-init`  
**Exit code: 0**

### Migration results

- Hub / bridge / chat modules loaded successfully (see `upgrade_prod.log`).
- No upgrade-blocking errors for focus modules.
- Pre-existing ambient warnings (`ai.embedding`, pet searchable fields) — unrelated.

### Flags immediately after upgrade

```text
whatsapp_hub.unified_outbound_enabled = False
whatsapp_hub.discuss_cutover_enabled = False
whatsapp_hub.unified_outbound_purposes = (empty)
discuss.channel #5 wa_outbound_mode = legacy
whatsapp.instance cutover flags = N/A then later created OFF
```

Service restarted: **active**.

---

## 3. Post-upgrade regression (all channels `legacy`)

Evidence: `regression_legacy.txt` (mocked HTTP + **rolled back** — no lasting fake traffic).

| Check | Result |
|-------|--------|
| Wrapper `_send_whatsapp_discuss_message` present | Yes |
| `_send_via_evolution` still used for Campaign module source | Yes |
| Clinic `service_queue_outbound` present | Yes |
| Channel #5 mode | `legacy` |
| Mock Discuss send | **1** legacy HTTP, **0** Hub transport |
| Compatibility log + Hub mirror | 1 log (`send_origin=legacy`), 1 Hub msg `purpose=discuss` |
| `unified_bridge` job delta | **0** |
| Shadow rows on legacy send | **0** |
| Global/instance cutover flags | All **False** / 0 |
| Channels in `hub` | **0** |

Conclusion: Production Discuss behavior remained legacy-equivalent before enabling shadow.

---

## 4. Pilot cohort

### Selection

Only one Production WA Discuss channel exists. It matches the selection criteria as a **non-customer Bridge Test** channel:

| Field | Value |
|-------|--------|
| Channel ID | **5** |
| Name | WA: كريم ايهاب الساحل 2022 |
| Partner | Sabry Bridge Test |
| Phone / JID | `201000059085` → `201000059085@s.whatsapp.net` |
| Evolution instance | `sabry min` (ICP / Hub instance map) |
| Volume | Low (last organic outbound 2026-06-19) |
| Mode before | `legacy` |
| Mode after | **`shadow`** |

**Not selected:** Campaign paths, clinic channels, attachment-heavy channels (none other available).

### Hub instance map (non-cutover)

Created `whatsapp.instance` id=1 `instance_name=sabry min` with:

- `unified_outbound_enabled=False`
- `discuss_cutover_enabled=False`
- no API key copied into Hub for this map row

Purpose: improve shadow instance/conversation comparison only — **does not enable Hub transport**.

---

## 5. Shadow observations

### Observation 1 — controlled Bridge Test probe

| Field | Value |
|-------|--------|
| Source channel | #5 (shadow) |
| `mail.message` | **11308** |
| Legacy log | `wa.message.log` **#5** (`send_origin=legacy`, `delivery_status=sent`) |
| Evolution message id | `3EB08FFFE4C53F413CAF8A` |
| Canonical Hub message | `whatsapp.message` **#8** (`business_key=walog:5`, `purpose=discuss`) |
| Shadow row | `whatsapp.discuss.shadow` **#1** |
| Classification | **`matched`** |
| Eligible | True |
| Candidate business key | `discuss:5:11308` |
| Actual business key | `walog:5` (expected for legacy-first mirror; keys differ by design, conversation matched) |
| Destination | candidate `201000059085` / actual `201000059085@s.whatsapp.net` |
| Purpose | `discuss` / `discuss` |
| Instance ref | `sabry min` / `sabry min` |
| Conversation identity | **equal** (expected == actual) |
| Legacy transport | Evolution HTTP **201** (real) |
| Hub unified transport calls | **0** (guarded; would raise if invoked) |
| `unified_bridge` jobs | **0** |
| Duplicate Hub messages for log | **None** |

Note: This was a **controlled pilot probe** on the Bridge Test partner channel (not customer outreach), required because Production had no recent organic Discuss WA traffic on the only available channel.

Evidence: `pilot_enable_and_probe.txt`

---

## 6. Aggregate results

| Metric | Value |
|--------|------:|
| Total shadow observations | **1** |
| `matched` | **1** (100%) |
| Other mismatch classes | **0** |
| Duplicate WhatsApp sends detected | **0** |
| Unexpected Hub unified jobs | **0** |
| Hub transport invocations | **0** |
| Channels in `hub` | **0** |

---

## 7. Issues found

| Issue | Severity | Action |
|-------|----------|--------|
| No organic recent Discuss WA traffic on Prod | Low / observational | Used one controlled Bridge Test probe; leave channel in `shadow` for further organic observation |
| Historical bridge queue `failed=76` | Pre-existing / unrelated | Noted; no pending unified Hub jobs; not introduced by this pilot |
| Ambient `ai.embedding` / pet field warnings on upgrade | Noise | Unrelated; upgrade succeeded |

No Phase 4 shadow code hotfixes required. No Test re-validation cycle needed for this pilot.

---

## 8. Final configuration

```text
whatsapp_hub                19.0.1.3.0
evolution_whatsapp_chat     19.0.1.12.0
integration_bridge_core     19.0.1.1.2

whatsapp_hub.unified_outbound_enabled = False
whatsapp_hub.discuss_cutover_enabled  = False

whatsapp.instance#1 unified_outbound_enabled = False
whatsapp.instance#1 discuss_cutover_enabled  = False

discuss.channel#5 wa_outbound_mode = shadow   # pilot continues
hub-mode channels = 0
unified_bridge outbound jobs = 0
```

Service: **active**.

Campaign path: still `_send_via_evolution` (source confirmed; not modified).

**Rollback remains config-only:** set channel #5 `wa_outbound_mode=legacy`.

---

## 9. Recommendation

**READY for additional / continued shadow observation** on the current Bridge Test cohort (channel #5 remains `shadow`).

**NOT READY** for Discuss Hub cutover (even single-channel), because:

1. Only **one** shadow sample was observed in this session.
2. Exit criteria require enough real samples to establish match-rate confidence.
3. Hub cutover flags must stay OFF until a separate explicit Hub pilot is approved.

**Do not** start Phase 5 Campaign migration.

---

## Evidence index

| File | Content |
|------|---------|
| `preflight.txt` | Pre-upgrade state (secrets redacted) |
| `backup_paths.txt` | DB dump location |
| `upgrade_prod.log` | Module upgrade log |
| `versions_after.txt` | Post-upgrade versions |
| `flags_after_upgrade.txt` | ICP flags |
| `regression_legacy.txt` | Legacy regression (mocked, rolled back) |
| `pilot_enable_and_probe.txt` | Shadow enable + probe results |
| `final_config.txt` | Final flags / modes / aggregates |

**Stopped after Production shadow pilot. No Hub cutover. No Campaign cutover.**
