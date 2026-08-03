# Production deployment plan — Pet Spot WA Marketing Queue

**Do not run until Sabry approves Phase 6 + Phase 7/8.** TEST/UAT only until then.

## Preconditions

- Prod backup of `pet_spot_elsahel`
- `petspot_wa_marketing_consent` already installed on prod
- Evolution `petspot-marketing` healthy on isolated stack `:8199`
- Global marketing pause remains the safety default

## Steps

1. Deploy module `petspot_wa_marketing_queue` to prod addons path (same SHA as TEST UAT).
2. Install: `-i petspot_wa_marketing_queue` on `pet_spot_elsahel` only after backup.
3. Verify settings: `global_pause=True`, `evolution_instance=petspot-marketing`, `mock_send=False` only after allowlist set.
4. Assign Consent Manager / Queue Manager to Sabry (`admin`) only.
5. Do **not** approve any customer campaign until Phase 7 internal test PASS and Phase 8 pilot approval.
6. Configure system parameter `petspot_wa_marketing_queue.evolution_apikey` from secret store (never commit).
7. Point PetSpot Evolution webhook for marketing replies to `/petspot/wa/marketing/evolution/webhook` (or bridge that filters instance=petspot-marketing).

## Rollback

1. Set global pause ON.
2. Cancel all campaigns / pending queue items.
3. If no real customer sends occurred, uninstall module is optional; prefer leave installed paused.
4. Never route marketing through `sabry min`.

## Forbidden

- Selecting or configuring `sabry min` / `+201000059085`
- Auto tier increase
- Catch-up bursts
- Historic backfill of consent or queue
