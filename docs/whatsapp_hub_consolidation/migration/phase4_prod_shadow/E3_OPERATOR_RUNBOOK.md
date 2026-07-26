# Discuss Hub Operator Runbook (E3)

**Status:** Production operational standard  
**Design:** [`E3_DISCUSS_HUB_STANDARDIZATION_DESIGN.md`](./E3_DISCUSS_HUB_STANDARDIZATION_DESIGN.md)  
**Scope:** Governance only — does not change routing code by itself

---

## A1. Supported routing policy

```text
New WA Discuss channel
  → legacy by default
  → optional shadow (evidence)
  → Hub only after validation + explicit allowlist + admin approval
```

Approved Hub path:

```text
Discuss message_post (mode=hub + allowlisted + flags ON)
  → Hub unified outbound
  → canonical whatsapp.message
  → whatsapp.outbound.message (unified_bridge)
  → bridge one-shot → Evolution
```

Unapproved / new channels stay on `_send_via_evolution` (legacy or shadow).  
**Campaign is out of scope** and always uses `_send_via_evolution`.

ICP: `whatsapp_hub.discuss_hub_allowed_channel_ids` (CSV). Empty = fail-closed when Discuss cutover is ON.

---

## A2. Future channel onboarding

1. Channel created → `wa_outbound_mode=legacy` (default).  
2. Optional legacy smoke (one successful Discuss send).  
3. Set mode = `shadow`.  
4. Collect shadow evidence (organic and/or controlled test destinations only).  
5. Gate:
   - ≥10 matched shadow samples  
   - 0 unexplained mismatches  
   - stable JID / instance / conversation  
6. Add channel id to `discuss_hub_allowed_channel_ids` (e.g. `10,5,12`).  
7. Flip channel to `hub` **last**.  
8. Controlled Hub pilot: 3 plain-text Discuss posts.  
9. Pilot gate: 3/3 Hub-only, 0 legacy leakage, unique provider IDs, one canonical per source, compat convergence, 0 duplicates.  
10. Extended soak (≥10 Hub successes or time-box with min 5).  
11. Standard Hub operation (remain `hub` + allowlisted).

Do **not** call `service_send_message` for happy-path pilots — use Discuss `message_post`.

---

## A3. Rollback hierarchy

### Channel

1. `wa_outbound_mode` → `shadow`  
2. `env['whatsapp.outbound.message'].service_quarantine_discuss_channel(id, reason=...)`  
3. Remove id from allowlist  
4. Leave global/instance flags **ON** if other Hub channels remain  

### Instance

1. All Hub Discuss channels on that instance → `shadow`  
2. Quarantine each channel’s incomplete unified jobs  
3. Instance `unified_outbound_enabled` + `discuss_cutover_enabled` → OFF  

### Global Discuss

1. All Hub channels → `shadow`  
2. Quarantine all Discuss `unified_bridge` incomplete jobs  
3. Allowlist → empty (fail-closed)  
4. Instance flags OFF  
5. Global unified + Discuss cutover OFF  

**Never** resend an already provider-accepted Hub message through legacy for the same `mail.message` / business key. Mode→shadow alone does **not** stop already-admitted pending Hub jobs — quarantine is mandatory.

---

## A4. Soak stop thresholds

| Condition | Action |
|-----------|--------|
| Unified job outside allowlist | **Critical** — investigate immediately |
| Legacy leakage on hub channel (`send_origin=legacy` after **current** Hub streak floor) | Rollback / investigate |
| Duplicate provider id or business key | Channel rollback; escalate if multi-cohort |
| Pending/processing > **15 minutes** | Investigate; quarantine if stuck |
| Retry exhaustion (`retry_count >= max_retries` failed) | Investigate |
| Permanent failure rate > **20%** of recent Hub attempts | Pause new Hub promotions |

Leakage floor = start of the trailing contiguous `hub_unified` streak (not first-ever Hub send), so intentional mid-migration shadow regressions are not flagged as current leakage.

Ops UI: **WhatsApp Hub → Discuss Hub Ops**  
Health: **WhatsApp Hub → Discuss Hub Health** (cron hourly; activities on new critical issues only).
