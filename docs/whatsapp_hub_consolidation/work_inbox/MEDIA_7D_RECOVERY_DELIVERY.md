# Recover and harden 7-day media backfill — TOURZ canary

Status: **TOURZ RECOVERED — Dev Needed not enqueued**

Database: `pet_spot_elsahel_test` only

Production deployment: none

OpenProject activity: none

## 1. Exact Whisper failure root cause

Temporary **OpenAI upstream outage** returning HTTP **500/503** on Whisper
(`/v1/audio/transcriptions`) and `/v1/models` during the pause window.

Ruled out before classifying as provider outage:

- local attachment openability
- codec/MIME (OGG/Opus → ffmpeg normalize → MP3 `audio/mpeg`, size > 0)
- empty normalized file
- incorrect endpoint / multipart construction (same client path as Phase-2 successes)
- credential absence (key present in preprocessor container)
- preprocessor proxy as sole cause

After recovery, OpenAI `/v1/models` returned **HTTP 200**.

## 2. Affected media / job IDs

| Media | Message | Attachment | Download job | Enrichment job | Kind | Pause state | Final |
|------:|--------:|-----------:|-------------:|---------------:|------|-------------|-------|
| 189 | 422 | 6061 | 192 | 193 | image_ocr | succeeded | succeeded |
| 190 | 434 | 6062 | 194 | 197 | audio_transcription | retry (503, attempt 2) | succeeded |
| 191 | 431 | 6063 | 195 | 198 | audio_transcription | retry (500, attempt 1) | succeeded |
| 192 | 416 | 6064 | 196 | 199 | audio_transcription | retry (500, attempt 1) | succeeded |

Correlation IDs (audio):

- 197 → `e85309b0-0868-4f79-9808-01f246219c4a`
- 198 → `163e4ef9-1040-4b78-90fb-26704004bd29`
- 199 → `6cc5f959-552b-42aa-a5d4-1082c8a997ad`

Sanitized provider failure evidence at pause: HTTP 500/503, `provider_outage`,
no API keys or transcript bodies logged in the recovery report.

## 3. Canary test result

- Selected canary: media **191** / job **198**
- Manual Phase-2 path earlier: HTTP 200, non-empty Arabic transcript (~47 chars)
- Controlled worker canary (`worker.py --once`, lease limit 1): **succeeded**
  - provider `openai`, model `whisper-1`
  - transcript length 47
  - no inbox / Work Item mutation
- Then jobs **197** and **199** processed one-at-a-time: both **succeeded**

## 4. Provider request/response diagnosis (sanitized)

- Outgoing path: worker → ffmpeg normalize → multipart Whisper upload
- Failure body class: upstream 5xx (`provider_outage`), not 429 presented as 500
- Recovery probe: `/v1/models` → 200
- Enrichment worker now records sanitized HTTP status / retry hints on fail

## 5. Retry and circuit-breaker behaviour

Implemented/verified:

- Exponential backoff + jitter; honor `Retry-After` when present
- Provider circuit: latest window (default 20) failure rate > 10% opens circuit
  for cooldown (default 900s)
- While circuit open: Whisper leases skipped; download/OCR remain leaseable
- Max attempts → dead-letter
- Admin recovery ICP:
  `devhub_whatsapp.media_transcription_circuit_force_closed_until`
  (used briefly after confirmed provider health, then cleared)

## 6–8. Inbox mutation root cause, code path, hardening

Exact process (not “unknown concurrent work”):

- Script: `docs/whatsapp_hub_consolidation/work_inbox/admit_whitelist_work_inbox.py`
- Terminal evidence: started ~2026-07-25 09:34:29Z
- Method path:
  `whatsapp.message.search(untriaged)` →
  `TriageMessage.browse(...).action_inbox_add()` →
  `_inbox_set_state("new", event_type="add_to_inbox")`
- Affected messages: **416, 422, 431, 434**
- Before: `untriaged` → temporary: `new` → restored: `untriaged`
- Inbox events existed for the mutation and restore

Why the historical guard failed initially: there was no central non-mutating
context / historical-media skip on operational admission.

Hardening:

- Context key `historical_review_non_mutating`
- Central guard module `dev_whatsapp_historical_guard.py`
- `action_inbox_add` / `action_inbox_restore` skip historical-media messages and
  write `historical_skip` audit events
- Media job lease/complete paths set non-mutating context
- Admit script skips historical media and reports `skipped_historical_media`

## 9. Automated test results

- `/devhub_whatsapp`: **0 failed, 0 error(s) of 103**
- Recovery + Phase2 subset recheck: **0 failed, 0 error(s) of 30**

## 10. TOURZ resumed-job results

All four selected TOURZ media are terminal **succeeded**:

| Media | Type | Enrichment | Provider/model | Text len |
|------:|------|------------|----------------|---------:|
| 189 | image | succeeded | tesseract / tesseract-5-ara+eng | 788 |
| 190 | audio | succeeded | openai / whisper-1 | 271 |
| 191 | audio | succeeded | openai / whisper-1 | 47 |
| 192 | audio | succeeded | openai / whisper-1 | 183 |

No retry storm. No dead-letter on TOURZ. Worker left idle (no loop).

## 11–13. Safety hash / inbox / Work Items

| Check | Before recovery resume | After TOURZ complete |
|-------|------------------------|----------------------|
| Selected-message safety hash | `687cb6cfc9386eb27ef430bbf2878206` | `687cb6cfc9386eb27ef430bbf2878206` |
| TOURZ inbox states | all `untriaged` | all `untriaged` |
| Work Item count | 60 | 60 |
| Selected linked Work Items | 0 | 0 |

## 14. Images independent of Whisper circuit

Yes. Circuit skips only Whisper kinds; OCR/download remain leaseable.
Covered by `test_transcription_circuit_blocks_whisper_not_ocr`.

## 15. Remaining provider risk

OpenAI can still return intermittent 5xx. Circuit + backoff + force-close ICP
mitigate storms. Do not bulk-enqueue Dev Needed audio until a short healthy
window is observed under concurrency=1.

## 16. Recommendation on Dev Needed enqueue

**Do not enqueue Dev Needed yet.**

Recommend only after explicit approval of this recovery report, then a separate
controlled plan:

1. dry-run confirmation of the 33 candidates
2. concurrency audio=1, video=0
3. circuit force-close unused unless provider health reconfirmed
4. stop on first sustained 5xx / circuit open
5. no Operational auto-apply / no OpenProject

## 17. Files changed

Module version: `devhub_whatsapp` **19.0.9.3.2**

Code / tests / data:

- `devhub_whatsapp/models/dev_whatsapp_historical_guard.py` (new)
- `devhub_whatsapp/models/dev_whatsapp_inbox.py`
- `devhub_whatsapp/models/dev_whatsapp_media_job.py`
- `devhub_whatsapp/models/dev_whatsapp_media_backfill.py`
- `devhub_whatsapp/models/__init__.py`
- `devhub_whatsapp/data/ir_config_parameter_media.xml`
- `devhub_whatsapp/tests/test_whatsapp_media_recovery.py` (new)
- `devhub_whatsapp/tests/test_whatsapp_media_phase2.py`
- `devhub_whatsapp/tests/__init__.py`
- `devhub_whatsapp/__manifest__.py`
- `docs/.../admit_whitelist_work_inbox.py`
- `docs/.../MEDIA_7D_RECOVERY_DELIVERY.md` (this file)

Worker (not in project git):

- `/home/sabry/infra/devhub-wa-media-worker/enrichment.py`
- `/home/sabry/infra/devhub-wa-media-worker/worker.py`

## 18. Production and OpenProject

- Test only (`pet_spot_elsahel_test`)
- Production HTTP `:8027` remained healthy; no Production module deploy
- No OpenProject API / package modifications in this recovery
- Full 7-day / Dev Needed backfill **not** resumed
