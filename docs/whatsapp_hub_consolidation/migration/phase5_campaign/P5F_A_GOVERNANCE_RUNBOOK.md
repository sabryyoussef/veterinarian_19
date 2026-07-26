# P5F-A — Broader Text Campaign Governance Runbook

**Status:** Implemented with modules `whatsapp_hub` **19.0.1.10.0**, `evolution_whatsapp_chat` **19.0.1.19.0**  
**Design:** [`P5F_BROADER_TEXT_CAMPAIGN_CUTOVER_DESIGN.md`](./P5F_BROADER_TEXT_CAMPAIGN_CUTOVER_DESIGN.md)

---

## Allowlist semantics

`whatsapp_hub.campaign_hub_allowed_campaign_ids` means:

> Campaigns **currently authorized to admit NEW Hub jobs**.

It does **not** mean every historical Hub Campaign must remain listed forever.

| Situation | Health |
|-----------|--------|
| Active Hub Campaign (not completed/cancelled) missing from allowlist | **Critical** `hub_not_allowlisted` |
| Completed/cancelled Campaign removed from allowlist | **OK** (historical evidence preserved) |
| Completed/cancelled still on allowlist | **Warning** `completed_campaign_still_allowlist` |
| Incomplete Hub jobs for non-allowlisted Campaign while plane active | **Critical** `job_outside_allowlist` |

---

## Defense in depth (Hub send)

All required:

1. Global `campaign_cutover_enabled`
2. Instance `campaign_cutover_enabled`
3. `unified_outbound_purposes` includes `campaign`
4. Campaign ID on allowlist
5. `wa_outbound_mode = hub`
6. Text-only (no attachments)
7. Freeze before/at admit

New Campaigns default **`legacy`**.

---

## Ops workflow (Campaign Hub Ops)

1. Create Campaign (`immediate`, text-only, ≤ volume band).
2. Load recipients → **Freeze Lines**.
3. **Approve Hub** (allowlist only — does **not** flip mode).
4. When ready: flip `wa_outbound_mode` → **hub** last (separate operator step).
5. Start / process batches (batch=5, max_pending=20).
6. On complete: **Cleanup Allowlist** (or Revoke) → prefer mode → `shadow`.
7. Quarantine only if incomplete Hub jobs remain.

### Approve rejects

* attachments/media
* `send_mode=scheduled` or `state=scheduled`
* `send_mode=queue` with `scheduled_date`
* non-immediate orchestration
* completed/cancelled
* missing phones / instance

### Revoke

* Refuses if pending/processing Hub jobs exist → quarantine first.
* Never deletes Hub messages/jobs/provider IDs/logs.

---

## Render freeze

* **Freeze Lines**: freeze unlocked pending lines from `campaign.message`.
* **Re-render for Hub** (admin, line): only if no `hub_message_id` / `hub_outbound_id` / provider ID.
* After Hub admission: payload immutable.
* Campaign message edits do not change locked lines.

---

## Standing control plane (future — not activated by P5F-A)

```text
purposes = discuss,campaign
campaign_cutover = True (global + instance)
allowlist = fail-closed (active IDs only)
new Campaign mode = legacy
```

P5F-A leaves Production Campaign plane **OFF** by default. P5F-B decides temporary vs standing activation.

---

## P5F-B first real Campaign (do not run in P5F-A)

* Fresh immediate text Campaign
* ≤20 recipients
* freeze + approve + hub last
* batch 5 / max pending 20
* health: before, after first 5, completion
* #10–14 remain legacy until P5F-E scheduled parity
* #15 media remains Tier C / P5G

### Volume bands

| Stage | Recipients | Batch / max |
|-------|------------|-------------|
| F1 | ≤20 | 5 / 20 |
| F2 | ≤50 | stay 5/20 until evidence |
| F3 | ≤100 | evidence-based raise |
| F4 | larger text | evidence-based |

### Semantics note

Campaign line **Sent** = provider **accepted**. Not necessarily delivered/read.

### Fairness

Campaign priority = 3. Discuss unchanged. Monitoring-only for starvation initially.

### Rollback (one Campaign)

Pause → mode shadow/legacy → quarantine incomplete → remove allowlist → never legacy-resend accepted lines.
