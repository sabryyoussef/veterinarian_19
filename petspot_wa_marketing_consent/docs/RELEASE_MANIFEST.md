# RELEASE MANIFEST — PetSpot WA survey consent (post-visit)

**Status:** Production deploy of survey-consent route (collection only). Marketing remains paused.

## Dedicated release branch

| Item | Value |
|------|--------|
| Branch | `feature/petspot-wa-survey-consent` |
| Base | `feature/petspot-wa-marketing-queue` @ `54d7f74be484f4bb6cf04cbd8ad3fdf5202c0b6e` |
| Module versions | consent `19.0.1.0.2` · feedback `19.0.1.1.0` |
| UAT evidence | `/home/sabry/.cursor/evidence/petspot-wa-survey-consent-uat-20260803/` |
| UAT verdict | `SURVEY_CONSENT_UAT_READY_FOR_APPROVAL` |

## Scope

- `petspot_wa_marketing_consent/` — `pending_review`, Sabry confirm, wording `post_visit_v1_1`
- `petspot_vet_feedback/` — optional unticked survey checkbox; capture after coupon; invitation unchanged

## Non-actions

- No campaign schedule/send
- Global pause ON, mock send ON, Warm Pilot draft
- No consent backfill; no historic survey → consent
- Operations WhatsApp / `sabry min` untouched
