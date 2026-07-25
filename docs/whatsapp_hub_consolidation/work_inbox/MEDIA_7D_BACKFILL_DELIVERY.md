# Controlled seven-day WhatsApp media backfill — Test

Status: **PAUSED BY SAFETY THRESHOLD — not accepted as complete**

Database: `pet_spot_elsahel_test`

Production deployment: none

OpenProject activity: none

## 1. Exact date window

The selection uses an inclusive rolling 168-hour interval:

- UTC / Odoo: `2026-07-18 09:22:14` through `2026-07-25 09:22:14`
- UTC+3: `2026-07-18 12:22:14+03:00` through
  `2026-07-25 12:22:14+03:00`

Every selector applies both timestamp boundaries. The guarded service rejects a
window longer than seven days.

## 2. Final source scope

Included confirmed single-project sources:

- Source 1 — Testopenclow (openlowtest) — PETSPOT
- Source 2 — Clinic Hub Smoke — PETSPOT
- Source 3 — Clinic Multi UAT — PETSPOT
- Source 5 — Asta development — ASTA
- Source 6 — AZone - WorldPosta — AZONE
- Source 7 — Bright&I zone (Odoo ERP) — AZONE
- Source 8 — Cycle X — CYCLEX
- Source 10 — Izone - Internal BIS — AZONE
- Source 11 — Pet spot sahel branch — PETSPOT
- Source 12 — Torz Trading - Qatar client internal — TOURZ
- Source 13 — انهاء مشروع ASTA — ASTA
- Source 14 — مهمات مفتوحة لاستكمال فرع الساحل petspot — PETSPOT

Included multi-project source:

- Source 9 — Dev Needed
  - mapping state: `ambiguous`
  - lane: `multi_project`
  - AI triage: disabled
  - mandatory human confirmation: enabled
  - the PETSPOT baseline FK was not treated as a confirmed mapping

Excluded:

- Source 4 — Alzaeem Medial project - internal BIS
  - inactive mapping state: `unmapped`
  - historical-review approval: disabled
  - review lane: `excluded`

No inactive or additional invalid-lane sources existed in the Test source table.
The source model has no company field; project/source access and media
`company_id` provide the available isolation boundary.

## 3. Preflight inventory

Service and capacity checks:

- Worker free disk: `263,425,089,536` bytes before processing
- Test Odoo filestore: `268,215,366` bytes before processing
- Worker temporary media directory: `0` bytes
- Estimated temporary safety need: 500 MB
- n8n workflow `j3xV5kXRQUu1k0p4`: active, 12 nodes
- Odoo health: pass
- media-worker syntax/startup: healthy
- attachment preprocessor health: enabled and healthy
- Evolution instance `sabry min`: open
- Dify console API: HTTP 200
- OpenAI credential: present without disclosure
- Tesseract, ffmpeg, and ffprobe: available
- Production URLs in worker configuration: none
- Configured Odoo endpoints: localhost and Test host only

Inventory by included source:

- Source 5 / Asta development / ASTA
  - 2 messages; 0 media; no existing analyses or reviews
- Source 13 / انهاء مشروع ASTA / ASTA
  - 0 messages
- Source 6 / AZone - WorldPosta / AZONE
  - 2 messages; 0 media
- Source 7 / Bright&I zone / AZONE
  - 0 messages
- Source 10 / Izone - Internal BIS / AZONE
  - 0 messages
- Source 8 / Cycle X / CYCLEX
  - 0 messages
- Source 12 / Torz Trading / TOURZ
  - 33 messages; 12 messages marked with media
  - 4 images, 5 audio, 0 video, 1 document
  - 5 already downloaded; 5 already enriched
  - 0 pending; 0 expired/unavailable; 1 permanently failed
  - 1 historical analysis; 0 completed questionnaires
  - known stored size: 605,946 bytes
- Source 1 / Testopenclow / PETSPOT
  - 2 messages; 1 unsupported/unspecified media marker
- Source 2 / Clinic Hub Smoke / PETSPOT
  - 1 message; 1 unsupported/unspecified media marker
- Source 3 / Clinic Multi UAT / PETSPOT
  - 1 message; 0 media
- Source 11 / Pet spot sahel branch / PETSPOT
  - 0 messages
- Source 14 / open PetSpot Sahel tasks / PETSPOT
  - 0 messages
- Source 9 / Dev Needed / multi-project
  - 181 messages; 47 messages marked with media
  - 15 images, 25 audio, 2 video, 0 documents
  - 9 already downloaded; 9 already enriched
  - 0 pending; 0 expired/unavailable in-window
  - 1 historical analysis; 0 completed questionnaires
  - known stored size: 35,150,829 bytes

Observed downloaded-file averages used for estimation:

- image: 114,736 bytes; observed maximum 324,245 bytes
- audio: 75,404 bytes; observed maximum 157,823 bytes
- video: 20,087,235 bytes; observed maximum 34,501,204 bytes

Estimated new downloadable volume was approximately 23 MB from observed
averages. Current hard limits and 263 GB free disk made storage safe.

## 4. Deterministic dry-run

The guarded Odoo service selected 37 new supported media identities:

- TOURZ
  - image: 1
  - audio: 3
- Dev Needed
  - image: 11
  - audio: 21
  - video: 1

ASTA, AZONE, CYCLEX, and confirmed PETSPOT sources had zero new supported
candidates.

The selector excluded:

- already downloaded source identities
- terminal `expired`, `unavailable`, and `failed` identities
- open duplicate download jobs
- missing Evolution message identities
- unsupported/unspecified media kinds
- documents, because no approved safe document parser is implemented

The existing TOURZ document remained permanently MIME-rejected. It was not
retried.

## 5. Processing performed before pause

Controlled order was respected:

- ASTA: no candidates
- AZONE: no candidates
- CYCLEX: no candidates
- TOURZ image batch:
  - 1 enqueued
  - 1 downloaded
  - 1 attachment stored
  - 1 Tesseract `ara+eng` enrichment succeeded
- TOURZ audio batch:
  - 3 enqueued
  - 3 downloaded
  - 3 attachments stored
  - 3 Whisper jobs returned provider errors and entered retry
- PETSPOT: no supported candidates
- Dev Needed: **not enqueued**

Worker log evidence:

- media 189 / message 422 / image
  - attachment 6061
  - 104,382 bytes
  - OCR duration 1,506 ms
  - provider `tesseract`
  - model `tesseract-5-ara+eng`
  - enrichment `succeeded`
- media 190 / message 434 / audio
  - 53,132 bytes; enrichment pending
- media 191 / message 431 / audio
  - 8,148 bytes; enrichment pending
- media 192 / message 416 / audio
  - 35,536 bytes; enrichment pending

## 6. Stop-threshold event

All three initial TOURZ Whisper requests returned HTTP 500. After the manual
pause, one controlled retry returned HTTP 503.

Current jobs:

- 197 — audio transcription — retry — attempt 2 — `provider_outage`
- 198 — audio transcription — retry — attempt 1 — `provider_outage`
- 199 — audio transcription — retry — attempt 1 — `provider_outage`

Provider errors were 3 of the latest 20 jobs (15%), above the 10% threshold.
Direct OpenAI API health checks continued to return `server_error`. The
credential is present; this was not diagnosed as a missing-credential error.

No local Whisper model is installed. Ollama is healthy but has no speech model,
so changing provider would be an unapproved quality-policy change.

The on-demand media worker is stopped. No further batch will be enqueued until
the provider is healthy and these three retries are manually inspected.

## 7. Safety and non-mutation checks

Pre-backfill baseline:

- Work Items: 60
- selected messages linked to Work Items: 0
- selected-message inbox/work-link hash:
  `687cb6cfc9386eb27ef430bbf2878206`

A separate, concurrently running whitelist-admission script admitted 80 TOURZ
messages while the backfill was running. Four were in this backfill's selected
set. The Odoo inbox audit showed their exact transition:

- messages 416, 422, 431, and 434
- `untriaged` to `new`
- event type `add_to_inbox`

Those four were restored to the audited prior state with compensating `restore`
events. The exact selected-message safety hash returned to:

`687cb6cfc9386eb27ef430bbf2878206`

Post-restoration:

- Work Items: 60
- selected messages linked to Work Items: 0
- selected messages have their exact baseline inbox/work-link hash
- Work Item creations: 0
- Work Item attachments: 0

The concurrent whitelist script was not started by this backfill. Its other
non-selected changes were not modified.

## 8. Storage growth

Database attachment totals:

- before: 2,175 attachments / 137,231,655 bytes
- after partial run: 2,179 attachments / 137,432,853 bytes
- growth: 4 attachments / 201,198 bytes

Test filestore:

- before: 268,215,366 bytes
- after: 268,416,564 bytes
- growth: 201,198 bytes

Temporary media directory after processing: 0 bytes.

Worker free disk after processing: 263,393,894,400 bytes.

## 9. Review queues and questionnaire

Implemented in module version `19.0.9.3.1`:

- deterministic controlled-backfill service
- confirmed and multi-project queue domains
- image/audio/video filters
- partial/failed/manual-review filters
- corrected and reprocess-requested filters
- project, source, classification, and decision grouping
- downloaded, enriched, partial, failed, pending-review, reviewed, corrected,
  and reprocess counters

No new historical analysis was generated because the TOURZ segment has pending
audio enrichment and the safety threshold paused the run.

## 10. Automated tests

Command:

```bash
./venv19/bin/python3 ./odoo19/odoo19/odoo-bin \
  -c ./config/projects/pet_spot_elsahel_test.conf \
  -d pet_spot_elsahel_test \
  -u devhub_whatsapp \
  --test-enable \
  --test-tags=/devhub_whatsapp \
  --stop-after-init \
  --http-port=18188
```

Exact final result:

- Odoo stats: 115 tests, 16.60 seconds, 8,228 queries
- result runner: 97 test methods
- failures: 0
- errors: 0

Six new controlled-backfill test methods cover inclusive dates, source/lane
scope, Alzaeem exclusion, unsupported documents, idempotent enqueue, terminal
media exclusion, company assignment, and no inbox/Work Item mutation.

## 11. Browser UAT

Not completed. The configured `cursor-ide-browser` MCP server exposed no browser
tools in this session. No screenshots are claimed.

The module upgrade and XML view validation succeeded as part of the full test
run, but that is not a substitute for the requested browser UAT.

## 12. Dify, quality, and v2.4 status

No new Dify analysis was generated after the backfill began because terminal
media enrichment was not reached.

Therefore, the following are intentionally not fabricated:

- Dify schema-validity rate for this backfill
- classification distributions
- unsupported-claim rate
- reviewer accuracy or correction rate
- v2.4 real-example recommendations

The existing prompt remains `wa_project_aware_v2.3`. No prompt change was made.

## 13. Git status

Committed Phase 0–2 work:

- `4630333` — `feat(devhub): add WhatsApp media enrichment`
- `143cb9f` — `docs(devhub): document WhatsApp media enrichment`

The controlled-backfill code and this paused report are to be committed
separately after final review. Raw media, dumps, environment snapshots, probe
results, and sensitive evaluation exports remain excluded.

The external directory `/home/sabry/infra/` is not a Git repository, so the
media-worker files cannot receive a repository commit there.

## 14. Acceptance and expansion recommendation

The seven-day backfill does **not** currently satisfy acceptance criteria:

- 33 Dev Needed items were not enqueued
- 3 TOURZ audio enrichments remain non-terminal
- no new Dify analyses/questionnaires were generated
- browser UAT is unavailable

Do not expand to 14 or 30 days. Reconsider expansion only after:

1. OpenAI transcription health is restored.
2. The three TOURZ retries reach terminal state.
3. Dev Needed processing completes without another stop threshold.
4. Dify schema validity is 100%.
5. Browser UAT and human-review readiness checks pass.

No expired historical bulk retry occurred. Production and OpenProject were
untouched.
