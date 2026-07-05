# PetSpot WhatsApp Staff Flow — Phase 1 Checkpoint

**Date:** 2026-07-05  
**Branch:** `feature/wa-staff-flow-phase2`  
**Checkpoint tag:** `checkpoint-pre-wa-staff-flow-20260705`

## Git checkpoints

| Repo | Branch | Tag commit | Tag name |
|------|--------|------------|----------|
| pet_spot_elsahel | `feature/wa-staff-flow-phase2` | `40daa2c36b7e6b5bf11588065ebb779f9d476691` | `checkpoint-pre-wa-staff-flow-20260705` |
| chatwoot-evolution-bridge | `master` | `319db96104a92822abd8a9a2aefd95afe1fd864e` | `checkpoint-pre-wa-staff-flow-20260705` |

## Database backup

- **Path:** `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/backups/pet_spot_elsahel_20260705_212303.dump`
- **Format:** PostgreSQL custom (`pg_dump -Fc`)
- **Restore:** `pg_restore -h localhost -U odoo -d pet_spot_elsahel --clean --if-exists <backup.dump>`

## Current flow map (pre-implementation)

```
WhatsApp group → Evolution → n8n → chatwoot_evolution_bridge/petspot_clinic_bot.py
  → odoo_lookup POST /petspot/portal/lookup
  → classify_intent (start|book|exam|status|other)
  → mint_portal_token POST /petspot/portal/token (patient|vet)
  → Portal: /p/b/<code> booking | /p/e/<code> exam
  → Creates: res.partner, pet.pet, pet.appointment, pet.medical.visit
  → payment_status / invoice_id: fields only on appointment/visit — not wired to account.payment
```

## Odoo models (real names)

| Data | Model |
|------|-------|
| Owner | `res.partner` |
| Pet | `pet.pet` |
| Appointment | `pet.appointment` |
| Medical visit | `pet.medical.visit` |
| Portal token | `petspot.portal.token` |
| Submit audit | `petspot.portal.submit.log` |
| Invoice (manual backend) | `account.move` via `pet.appointment.action_create_invoice()` |

## Rollback

1. `git checkout checkpoint-pre-wa-staff-flow-20260705` (per repo)
2. Restore DB from backup path above
3. Restart Odoo: `systemctl restart pet_spot_elsahel` and bridge service
