# WhatsApp Hub Consolidation — UAT Evidence (W-C7)

**Date:** 2026-07-23  
**Production:** `pet_spot_elsahel` (:8027) — **not modified** (`whatsapp_hub` absent).

## Acceptance: one inbound → one hub row → N consumers

| Proof | DB | Result |
|-------|-----|--------|
| Idempotent ingest (replay twice) | `whatsapp_hub_fresh` | Second call `duplicate: true`; one row per `chatwoot_message_id` |
| Outbound queue | `whatsapp_hub_fresh` | `whatsapp.outbound.message` queued (count ≥ 1) |
| Unit/integration tests | `whatsapp_hub_fresh` | 3 tests, **0 failed / 0 errors** (`tests_whatsapp_hub.log`) |
| Dev Hub consumer | `devhub_modular_fresh` | Hub msg `id=1`; intake `whatsapp_message_id=1`; second hub ingest duplicate; hub count=1 |
| Clinic consumer | `pet_spot_elsahel_test` | Hub msg `id=1`; intake `id=17` linked; duplicate on replay; hub count=1 |

### Dev Hub multi-consumer (shell JSON)

```json
{
  "hub_first": {"message_id": 1, "duplicate": false},
  "devhub_intake": {
    "intake_id": 19,
    "whatsapp_message_id": 1,
    "skip_openproject_autocreate": true
  },
  "hub_second_duplicate": true,
  "hub_message_count_for_cw": 1,
  "same_hub_id": true
}
```

### Clinic multi-consumer (shell JSON)

```json
{
  "hub_first": {"message_id": 1, "duplicate": false},
  "clinic_intake_id": 17,
  "clinic_whatsapp_message_id": 1,
  "hub_second_duplicate": true,
  "same_id": true,
  "hub_count_for_cw": 1
}
```

## Post-UAT install matrix

| Database | Module | State / version |
|----------|--------|-----------------|
| `whatsapp_hub_fresh` (:8034) | `whatsapp_hub` | installed 19.0.1.0.0 |
| `devhub_modular_fresh` (:8032) | `whatsapp_hub` | installed 19.0.1.0.0 |
| `devhub_modular_fresh` | `devhub_whatsapp` | installed 19.0.9.0.1 |
| `pet_spot_elsahel_test` (:8028) | `whatsapp_hub` | installed 19.0.1.0.0 |
| `pet_spot_elsahel_test` | `evolution_whatsapp_chat` | installed 19.0.1.10.1 |
| `pet_spot_elsahel_test` | `petspot_wa_intake` | installed 19.0.1.0.1 |
| `pet_spot_elsahel_test` | `integration_bridge_core` | installed 19.0.1.1.1 |
| `pet_spot_elsahel` prod | `whatsapp_hub` | **absent** |

## Notes / non-blockers

- Full `-u` of all consumers on test DB can hit unrelated `petspot_campaign_rewards` ParseError (`campaign_phone_marassi` missing). Hub + consumer versions above are installed; fix campaign_rewards separately.
- Installing hub on modular fresh may log `dev_session_hub` seed policy conflict during cascade upgrade; hub + `devhub_whatsapp` still end installed and UAT RPC succeeded.
- n8n → hub ingest not yet live in production path (follow-up; dual-write/compat remains).

## Log artifacts

- `install_whatsapp_hub2.log`, `tests_whatsapp_hub.log`
- `install_hub_on_test*.log`, `upgrade_consumers_on_test.log`
- `install_hub_on_modular.log`
