# RELEASE MANIFEST — PetSpot WA marketing consent

**Status:** Phase 0 hygiene complete. Phase 1 production install **NOT approved**.

## Dedicated release branch

| Item | Value |
|------|--------|
| Branch | `feature/petspot-wa-marketing-consent` |
| Base (origin/main) | `66344b2e09e2049c39942114029253e919bc6709` |
| Ending SHA (pre-manifest) | `8f16e3db0b8a2ac2288af279ad009ba3c41bf28f` |
| Source commit (cherry-picked) | `2d2bb58808000d4f0d8d0f7aea81d067329c0e1a` |
| Module version | `19.0.1.0.1` |
| Remote | `origin` (`git@github.com:sabryyoussef/veterinarian_19.git`) |

## Scope

Only `petspot_wa_marketing_consent/` (module + docs). No LinkedIn/job-orchestrator, dumps, secrets, or evidence packs.

## Environments

| Env | State |
|-----|--------|
| TEST `pet_spot_elsahel_test` :8028 | Installed (collection-only) |
| Production `pet_spot_elsahel` :8027 | **Not installed** |

## Approved wording

Active: `clinic_v1_1_approved` / `staff_v1_1_approved`. Historical v1 unchanged/inactive.

## Non-actions

No production install/upgrade/restart, no group assignment, no sends, no backfill.
