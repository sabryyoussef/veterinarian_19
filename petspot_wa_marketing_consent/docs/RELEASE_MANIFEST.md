# RELEASE MANIFEST — PetSpot WA marketing consent

**Status:** Phase 0 hygiene complete. Phase 1 production install **NOT approved**.

## Dedicated release branch

| Item | Value |
|------|--------|
| Branch |  |
| Base (origin/main) |  |
| Ending SHA |  |
| Cherry-picked source |  |
| Module version |  |
| Remote |  () |

## Scope

Only  (module + docs). No LinkedIn/job-orchestrator, dumps, secrets, or evidence packs.

## Changed files vs origin/main

See petspot_wa_marketing_consent/__init__.py
petspot_wa_marketing_consent/__manifest__.py
petspot_wa_marketing_consent/data/consent_wording_data.xml
petspot_wa_marketing_consent/data/consent_wording_v1_1_activate.xml
petspot_wa_marketing_consent/docs/RELEASE_MANIFEST.md
petspot_wa_marketing_consent/docs/WORDING_V1_1_APPROVED.md
petspot_wa_marketing_consent/migrations/19.0.1.0.1/post-migrate.py
petspot_wa_marketing_consent/models/__init__.py
petspot_wa_marketing_consent/models/res_partner.py
petspot_wa_marketing_consent/models/wa_consent_wording.py
petspot_wa_marketing_consent/models/wa_marketing_consent.py
petspot_wa_marketing_consent/models/wa_marketing_consent_log.py
petspot_wa_marketing_consent/models/wa_marketing_eligibility.py
petspot_wa_marketing_consent/security/consent_security.xml
petspot_wa_marketing_consent/security/ir.model.access.csv
petspot_wa_marketing_consent/views/menu.xml
petspot_wa_marketing_consent/views/res_partner_views.xml
petspot_wa_marketing_consent/views/wa_marketing_consent_views.xml
petspot_wa_marketing_consent/wizard/__init__.py
petspot_wa_marketing_consent/wizard/staff_consent_wizard.py
petspot_wa_marketing_consent/wizard/staff_consent_wizard_views.xml (21 files under the module).

## Environments

| Env | State |
|-----|--------|
| TEST  :8028 | Installed (collection-only) |
| Production  :8027 | **Not installed** |

## Approved wording

Active:  / . Historical v1 unchanged/inactive.

## Non-actions

No production install/upgrade/restart, no group assignment, no sends, no backfill.
