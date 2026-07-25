# WhatsApp Media Enrichment — Implementation Plan

**Status:** Plan only — no implementation  
**Date:** 2026-07-25  
**Environment in scope:** `pet_spot_elsahel_test`  
**Repo:** `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel`  
**Out of scope:** Production, OpenProject, bulk historical download  

**Pipeline today:** Odoo → n8n `j3xV5kXRQUu1k0p4` → Dify `dee250c0-7f44-467c-9b0b-86f069bdc17e` (schema v2, prompt `wa_project_aware_v2.2`)

---

## Executive verdict

WhatsApp Hub **does not store real media files**. It stores placeholders (`[image]`, `[audio]`, `[video]`), `media_kind`, and (rarely) thumbnail stubs. Dify therefore cannot “see” media.

**Retrieval is still possible** for nearly all Hub media rows via Evolution  
`POST /chat/getBase64FromMediaMessage/{instance}` using stored `evolution_message_id` + `instance_reference` (`sabry min`) + `group_jid` / `sender_jid`. This pattern is already proven by `/home/sabry/infra/nextcloud/backfill-whatsapp-to-nextcloud.py` and `chatwoot-evolution-bridge/media_bridge.py`.

**Enrichment tooling already exists** in `chatwoot-attachment-preprocessor` (ffmpeg, tesseract, OpenAI Whisper). It is wired to Chatwoot attachments, not Odoo Hub.

**Recommended design:** Option A+C hybrid —

```text
Evolution getBase64 (authenticated)
→ dedicated media worker (lease job)
→ Odoo ir.attachment + dev.whatsapp.media
→ enrichment (reuse preprocessor providers)
→ store enrichment in Odoo
→ analysis job payload includes media_enrichment JSON
→ Dify receives text enrichment only (no binary upload)
→ historical review questionnaire shows media status
```

Do **not** send binaries to Dify in v1 (file upload and vision are disabled on the canonical app). Do **not** bulk-download history until a measured pilot.

---

## 1. Current media ingestion audit

### Path that creates Hub rows

```text
WhatsApp → Evolution → Chatwoot bridge → Chatwoot → n8n
  → POST /whatsapp_hub/ingest
  → whatsapp.message.service_ingest_normalized
```

Evolution’s native webhook (`/bridge/evolution/webhook`) does **not** create Hub media rows or store files; media upserts become text stubs like `[media]`.

### What Odoo stores today (`whatsapp.message`)

| Field | Reality |
|-------|---------|
| `body` | Often `[image]` / `[audio]` / `[video]` |
| `media_kind` | Heuristic classification — **without downloading files** |
| `has_media` | Derived from `media_kind != none` |
| `attachment_references` | Text JSON/string; present on only **49/849** media rows; metadata only |
| `raw_payload` | Normalized ingest JSON — **no** `mediaUrl`, `base64`, `mediaKey`, `data_url` |
| `evolution_message_id` | Present on **100%** of image/audio/video/document media |
| `instance_reference` | Almost always `sabry min` |
| Binary / URL fields | **Do not exist** |

### Attachment reality (Test DB)

| Metric | Count |
|--------|------:|
| Total messages | 3736 |
| `has_media` | 849 |
| `ir.attachment` linked to `whatsapp.message` | **18** (tiny JPEG previews ~0.5–4 KB, not originals) |
| Media with neither refs nor files | **800** |

### Counts by kind (image/audio/video/document)

| Source | image | audio | video | document |
|--------|------:|------:|------:|---------:|
| **Dev Needed** | 244 | 465 | 24 | 0 |
| Torz Trading | 19 | 14 | 4 | 2 |
| Other confirmed groups | ~0 | ~0 | ~0 | ~0 |

Date span: **2026-03-31 → 2026-07-23**.  
Filestore today: **378 MB**. Disk free: **246 GB**.

### Existing fetch capability (outside Hub)

| Component | Capability |
|-----------|------------|
| `media_bridge.fetch_evolution_media` | Evolution getBase64 → bytes + mime + filename |
| Nextcloud backfill script | Same API; group sync of media |
| Chatwoot attachment preprocessor | Download Chatwoot `data_url` → OCR / Whisper / text normalize |
| Hub itself | **No download, no proxy, no preview player** |

**Chatwoot CDN recovery from Hub is not viable today:** among media rows, `data_url` count = 0; only 1 row has `chatwoot_message_id > 0`.

---

## 2. Exact current payload gap

### Odoo → n8n job (`_job_payload`)

Per message today:

```json
{
  "id": 1001,
  "timestamp": "...",
  "sender_jid": "...",
  "body": "[image]",
  "media_kind": "image",
  "inbox_state": "new",
  "context_only": false,
  "linked_work_item_ids": []
}
```

**Missing:** attachment id, URL, mimetype, filename, size, duration, transcript, OCR, description, enrichment status, media error.

### n8n `j3xV5kXRQUu1k0p4`

- 12-node JSON relay only (lease → start → Call Dify → complete/fail)
- **No binary nodes**, no Evolution/Chatwoot credentials in n8n env for media
- Call Dify timeout 180s; Odoo lease 600s
- Payload size default ~16 MB if binaries were added later

### Dify canonical app

- Start input: single `request_json` paragraph (max 120000)
- `file_upload.enabled = false`
- LLM vision: **disabled**
- Prompt v2.2 already treats unavailable media as weak / `unclear` / `media_weak`
- First app in this Dify instance that would need file upload if binaries were chosen

### Downstream effect

`media_weak` conflict penalty fires on media-dominated low-prose segments → false project suppression is correct, but **useful analysis is impossible** because enrichment never existed.

---

## 3. Media availability and retrieval findings

| Question | Finding |
|----------|---------|
| Are originals in Odoo? | **No** (placeholders + 18 thumbnails) |
| Can Evolution still return bytes? | **Likely for recent**; **unknown for Mar–May** — must pilot |
| Reconstructable key? | Yes: `remoteJid=group_jid`, `id=evolution_message_id`, `participant=sender_jid`, `fromMe≈false` |
| Instance? | `sabry min` (847/849 media) |
| URL expiry in Hub? | N/A — Hub never stored URLs |
| Auth required? | Evolution `apikey` header |
| Historical bulk safe? | **No** until pilot measures hit-rate, size, CPU |

**Unresolved decision (must pilot):** WhatsApp/Evolution media retention for messages older than ~30–90 days. Plan assumes a non-trivial fraction of historical media returns `expired` / `unavailable`.

---

## 4. Recommended architecture

### Options compared

| Option | Summary | Verdict |
|--------|---------|---------|
| **A — Odoo downloads** | Odoo HTTP workers fetch Evolution | Reject as primary: overloads Odoo workers, couples timeouts to web |
| **B — n8n downloads** | Enrich inside analysis workflow | Weak: mixes media with business analysis; binary limits; duplicates analysis lease |
| **C — dedicated media worker** | Separate lease jobs for download + enrich | **Preferred core** |
| **D — direct Dify file upload** | Multipart files to Dify | Reject for v1: app has no file inputs; vision off; first-of-kind risk |

### Recommended: A+C hybrid (Odoo source of truth, worker does I/O)

```text
1. whatsapp.message ingested (placeholder + evolution ids)  [today]
2. enqueue media_download job (new) when has_media
3. media worker:
     Evolution getBase64 → validate MIME/size
     → create ir.attachment (res_model=whatsapp.message)
     → create/update dev.whatsapp.media (downloaded)
4. enqueue type-specific enrichment job
5. media worker / adapted preprocessor:
     image → OCR (+ optional OpenAI vision later)
     audio → Whisper (existing OpenAI path)
     video → ffmpeg audio extract + Whisper + sparse keyframes + OCR/vision
6. store enrichment on dev.whatsapp.media
7. analysis _job_payload includes media_enrichment[] / per-message enrichment
8. Dify analyses text evidence only; prompt updated to cite enrichment status
9. Historical review questionnaire shows media + allows correction
```

**Why this wins**

- Odoo remains source of truth for file + enrichment audit
- No public permanent media URLs
- Reuses proven Evolution fetch + preprocessor providers
- Analysis job stays lean; media can fail independently
- Supports historical review non-mutation
- Avoids Dify binary complexity in v1

---

## 5. Odoo model design

### Prefer one model: `dev.whatsapp.media`

One row per media asset on a message (a message may have 0..N). Subtype fields nullable by `media_type`.

**Identity / relationship**

- `whatsapp_message_id` (M2O, required, indexed)
- `attachment_id` (M2O `ir.attachment`)
- `thumbnail_attachment_id` (optional)
- `media_type` (`image|audio|video|document|sticker|unknown`)
- `mime_type`, `filename`, `file_size`, `duration_seconds`
- `source_provider` (`evolution`)
- `source_media_id` (= evolution message id)
- `source_instance` (= instance_reference)
- `source_key_json` (reconstructed Evolution key, no secrets)
- `checksum` (sha256 of bytes)
- `company_id` / project isolation via message → conversation → source

**Retrieval state**

- `retrieval_state`: `pending|downloading|downloaded|unavailable|expired|failed`
- `retrieval_attempts`, `retrieved_at`
- `retrieval_error_code`, `retrieval_error_message`

**Enrichment state**

- `enrichment_state`: `pending|processing|succeeded|partial|failed|manual_review|skipped`
- `enrichment_provider`, `enrichment_model`, `prompt_version`
- `started_at`, `completed_at`, `retry_count`

**Image / audio / video / common result fields** — as specified in the request (description, OCR, transcript, timeline, keyframes, confidence, needs_review, technical_terms, project/work hints, raw/validated JSON, `is_historical_review`, `is_sensitive`, `retention_state`).

**Why not only `ir.attachment`:** attachment stores bytes; enrichment, retrieval lifecycle, and review corrections need first-class fields and ACLs separate from generic attachments.

**Why not separate subtype models in v1:** one table keeps joins/jobs simple; sparse columns are fine at current volumes (~10³ media).

---

## 6. Media job design

### New model: `dev.whatsapp.media.job`

**Separate from** `dev.whatsapp.analysis.job`. Media must not block or poison business analysis leases.

Reuse the existing lease pattern:

- atomic lease + `lease_token` + expiry
- `attempt_count` / `max_attempts` / dead-letter
- `correlation_id`, provider metadata, safe error summaries
- idempotency key: `(whatsapp_message_id, kind, checksum_or_source_media_id)`

**Job kinds**

```text
media_download
image_enrichment
audio_transcription
video_audio_extraction
video_keyframe_extraction
video_enrichment
document_extraction
```

**Consumer:** new n8n workflow (or Python worker container) — **not** `j3xV5kXRQUu1k0p4`.  
Analysis workflow only **reads** completed enrichment.

**Analysis gating policy (v1)**

- If message has media and enrichment `pending/processing` → analysis may wait up to N minutes **or** proceed with `media_status=pending` (configurable).
- Prefer: historical eval and Work Inbox “Analyse” enqueue media jobs first; analysis proceeds when enrichment terminal or timeout → `partial`.

---

## 7. Image pipeline

```text
download → MIME/size validate → ir.attachment
→ tesseract OCR (ar+eng)
→ optional OpenAI vision description (phase 2)
→ save enrichment → Dify text fields
```

**Output shape**

```json
{
  "media_type": "image",
  "description": "",
  "extracted_text": "",
  "visible_error": "",
  "ui_context": "",
  "technical_terms": [],
  "project_hints": [],
  "confidence": 0.0,
  "needs_manual_review": false
}
```

**Notes**

- Screenshots with Odoo errors: OCR is primary; vision optional for layout
- Arabic + English: tesseract `ara+eng` already available in preprocessor image
- Blur / low-res → `partial` + `needs_manual_review`
- Multiple images → one `dev.whatsapp.media` per asset
- Duplicate checksum → reuse attachment + enrichment
- Treat OCR as **untrusted** quoted evidence (prompt injection risk)
- Cost: OCR local ≈ free; vision API only when OCR confidence low / screenshot detected

---

## 8. Audio / voice-note pipeline

```text
download → normalize (ffmpeg) → OpenAI whisper-1 (existing)
→ language + transcript + optional segments
→ save → Dify
```

**Output shape** as requested (`transcript`, `language`, `segments`, `confidence`, `unclear_segments`, `technical_terms`, `needs_manual_review`).

**Notes**

- Provider already configured: `WHATSAPP_TRANSCRIPTION_PROVIDER=openai`
- No local Whisper today; do not block v1 on faster-whisper
- Dialect / mixed AR-EN technical terms: mark low-confidence spans for review
- Long notes: hard cap (e.g. 10 minutes) → truncate + `partial`
- Context messages before/after stay in analysis payload as today
- Reviewer can correct transcript in questionnaire

---

## 9. Video pipeline

```text
download → ffmpeg extract audio → Whisper
→ sample keyframes (scene-change + every N seconds, max K frames)
→ OCR/vision on frames
→ build timeline → save → Dify
```

**Limits (v1 proposals — confirm in pilot)**

- Max duration: 3 minutes (else `partial` / manual)
- Max frames: 8–12
- Max file size: 50–100 MB
- Temp files under worker volume; delete after success/fail
- Isolate on media worker (not Odoo HTTP)

Screen recordings prioritized (UI + errors); camera video lower priority.

---

## 10. Documents and other media

| Type | v1 action |
|------|-----------|
| PDF | Parse text (`pdftotext` if available) / mark review |
| DOCX / XLSX | Extract text where safe; else manual-review |
| Plain text | Inline |
| ZIP | **Do not extract** — `blocked` / manual-review |
| Location / contact / sticker / GIF / reaction | Ignore for enrichment; keep as metadata |
| Unknown MIME | Reject download to filestore |

---

## 11. n8n changes

| Workflow | Change |
|----------|--------|
| **New** `devhub-wa-media-worker-test` | Lease `media.job` → Evolution fetch **or** call media worker HTTP → enrich → complete |
| Existing `j3xV5kXRQUu1k0p4` | **Minimal:** continue JSON-only; optionally wait/poll media readiness flag on analysis payload |
| Credentials | Evolution base URL + apikey for media workflow only (not analysis workflow) |
| Do not | Put multi‑MB base64 into analysis→Dify path |

Prefer a small FastAPI/worker that wraps existing `fetch_evolution_media` + preprocessor providers; n8n orchestrates leases.

---

## 12. Dify changes

**v1 (recommended):** text-only enrichment inside `request_json`.

Prompt additions (`wa_project_aware_v2.3` candidate):

- Use `media_enrichment` as evidence with `evidence_status: inferred`
- Never claim the model saw the original file
- Distinguish user text vs transcript vs OCR
- Failed/expired media → incomplete analysis; media-only failure → no WI create recommendation
- Keep `media_weak` for unenriched placeholders

**v2 (optional later):** enable file_upload + vision — only after text enrichment proves value.

---

## 13. Enriched schema (analysis payload)

```json
{
  "id": 1001,
  "body": "ده الخطأ اللي بيظهر",
  "media_kind": "image",
  "media_status": "succeeded",
  "media_items": [
    {
      "media_id": 55,
      "media_type": "image",
      "mime_type": "image/jpeg",
      "filename": "image.jpg",
      "enrichment": {
        "description": "Odoo form showing AccessError",
        "extracted_text": "AccessError...",
        "visible_error": "Access rights error",
        "confidence": 0.93,
        "needs_manual_review": false
      }
    }
  ]
}
```

Failed:

```json
{
  "media_status": "failed",
  "media_error": "source_expired",
  "needs_manual_review": true,
  "media_items": []
}
```

Also add top-level `segment_media_summary` for Dify instructions.

---

## 14. Historical review integration

Applies to:

- Confirmed single-project historical review
- **Dev Needed Multi-Project Historical Review** (majority of media)

Rules:

- Evaluation analyses remain non-mutating (no WI create/attach, no inbox ignore)
- Media download/enrichment **allowed** and stored on `dev.whatsapp.media` with `is_historical_review=true`
- Analysis may complete with `media_status=unavailable|failed|partial`
- Questionnaire displays enrichment + status
- Reviewer corrections write to media record / review fields — still no WI mutation
- **No full historical backfill** until pilot metrics

Pilot recommendation: Dev Needed + one confirmed group, last 14 days, capped counts (see §16).

---

## 15. Questionnaire changes

Extend Historical Review tab / `dev.whatsapp.analysis` review fields:

### Image

- Image description correct? (yes/partial/no)
- Extracted text correct?
- Image related to the task?
- Important error visible?
- Image sufficient or needs explanation?
- Corrected OCR / description

### Audio

- Transcript correct?
- Unclear words present?
- Summary reflects speaker request?
- Needs manual listen?
- Technical terms correct?
- Corrected transcript

### Video

- Transcript correct?
- Timeline correct?
- AI understood on-screen content?
- Reproduction steps correct?
- Multiple problems in video?
- Missed important moment / timestamp?
- Corrected timeline notes

### Common

- Media usefulness (1–5)
- Media analysis final status (`accepted|corrected|insufficient|unavailable`)
- Media needs reprocess? (boolean → requeue enrichment)

---

## 16. Security controls

| Control | Requirement |
|---------|-------------|
| Retrieval | Authenticated Evolution API only; no public permanent links |
| Storage | `ir.attachment` with ACLs (Dev Hub managers / company rules) |
| Validation | Allowlist MIME; max size; reject ZIP execution |
| Malware | ClamAV optional phase 2; at minimum MIME sniff ≠ extension |
| Injection | OCR/transcript treated as untrusted quoted data in Dify prompt |
| Temp files | Worker tmpfs/volume; delete always |
| Secrets | Evolution/OpenAI keys in worker env / vault — not in job JSON |
| Retention | `retention_state` + configurable TTL for historical media |
| Isolation | Message → source → project; no cross-company attachment browse |
| Audit | Job attempts, error codes, provider, model, checksum |
| Sensitive | Flag screenshots with credentials; redact in questionnaire exports |

---

## 17. Storage / capacity estimate

### Observed inventory (Test)

| Kind | Count | Notes |
|------|------:|-------|
| Image | 263 | ~244 Dev Needed |
| Audio | 479 | ~465 Dev Needed |
| Video | 28 | ~24 Dev Needed |
| Document | 2 | Torz |

Exact byte sizes unknown (not stored). From `attachment_references.fileLength` samples, images claim ~100 KB–5 MB; videos multi‑MB.

### Scenarios (order-of-magnitude)

| Scenario | Assumption | Rough store |
|----------|------------|-------------|
| Pilot (10+10+5) | avg image 500KB, audio 200KB, video 8MB | **~50–80 MB** + temp |
| Dev Needed full (if recoverable) | 244×0.5MB + 465×0.2MB + 24×8MB | **~350–450 MB** |
| All confirmed + Dev Needed | similar | **<1 GB** originals |
| Enrichment JSON | negligible | |
| Temp during video | 2–3× largest video | plan **≥5 GB** worker free |

CPU: Whisper API offloads audio; local ffmpeg keyframes OK on 24-core host. No GPU. Avoid concurrent heavy video jobs (queue concurrency 1–2).

Costs: unknown without measuring Whisper minutes + optional vision calls — pilot must log provider usage.

---

## 18. Failure and retry policy

| Failure | Behaviour |
|---------|-----------|
| Evolution 404 / empty base64 | `expired` or `unavailable`; no retry storm |
| Auth failure | fail job; alert; dead-letter |
| Unsupported MIME / too large | `failed` + code; no enrich |
| Corrupt file | `failed` |
| OCR/transcript failure | enrichment `partial`/`failed`; keep attachment if downloaded |
| Low-confidence transcript | `succeeded` + `needs_manual_review` |
| Video timeout | `partial`; store whatever audio/frames completed |
| Duplicate checksum | reuse; skip re-download |
| Provider outage | retry with backoff; dead-letter after max |

**Analysis coupling**

```text
Text + failed media
→ analyse available text
→ mark analysis incomplete / media_status=failed

Media-only + failed media
→ no actionable Work Item proposal
→ manual review required
→ WI decision none/unclear per existing v2.2 rules
```

Never claim media was analysed when `media_status != succeeded|partial`.

---

## 19. Test strategy

Automated (Test DB / unit):

- Metadata ingest creates `dev.whatsapp.media` pending
- Secure download mock → attachment + checksum
- Duplicate checksum idempotency
- Expired / auth / invalid MIME / oversized
- Image/audio/video enrichment schema validation
- Media job lease/retry/dead-letter
- `_job_payload` includes enrichment / failed status
- Historical evaluation mutation blocks unchanged
- Questionnaire correction fields persist
- ACL: unauthorized user cannot read attachment
- Production/OpenProject untouched (existing safety tests)

Manual UAT: §16 pilot checklist.

---

## 20. Pilot UAT plan (Test only)

**Sample**

- 10 screenshots (AR/EN, including Odoo errors)
- 10 voice notes (AR + mixed technical)
- 5 short videos (≤60–90s screen recordings)
- Mix of text+media and media-only
- ≥1 confirmed-single group sample if any media exists (else Torz)
- ≥5 Dev Needed multi-project samples

**Verify per sample**

1. File in Odoo (`ir.attachment` + `dev.whatsapp.media`)
2. Authorized user can open file
3. Enrichment stored
4. Dify `request_json` contains enrichment (inspect job payload / raw)
5. Questionnaire shows media block
6. Reviewer correction saves
7. No WI create/attach; inbox unchanged
8. Provider metadata visible
9. Failures auditable (force one expired id)

**Exit criteria:** ≥80% download success on last-14-days media; enrichment usable on ≥70% downloaded; zero mutation incidents.

---

## 21. Exact files / models / workflows expected to change

### Odoo (`devhub_whatsapp` / possibly `whatsapp_hub`)

- New: `models/dev_whatsapp_media.py`, `models/dev_whatsapp_media_job.py`
- New: security ACL CSV rows, views for media on message/analysis
- Update: `dev_whatsapp_analysis.py` `_job_payload`
- Update: historical review questionnaire fields + views
- Update: candidates `media_weak` to consider enrichment success
- Optional Hub: helper to build Evolution key from message fields

### Infra

- New or adapted worker using `media_bridge.fetch_evolution_media`
- Adapt `chatwoot-attachment-preprocessor` to accept raw bytes / Odoo attachment URL (authenticated) **or** duplicate provider calls in worker
- New n8n workflow for media jobs
- Prompt file `devhub-wa-project-resolver-v2.3.txt` (text enrichment rules)
- Dify workflow prompt update (text only)

### Docs

- This plan; pilot report template; security notes

### Explicitly unchanged in v1

- Production Odoo
- OpenProject
- Canonical analysis workflow binary behaviour
- Dev Needed mapping (`ambiguous`, triage off)

---

## 22. Risks and unresolved decisions

| Risk / decision | Notes |
|-----------------|-------|
| Historical Evolution hit-rate | **Must measure** before backfill |
| Evolution key `fromMe` / participant edge cases | Validate against live getBase64 |
| Video CPU / concurrency | Cap workers |
| Whisper cost | Log minutes in pilot |
| Optional OpenAI vision | Defer until OCR insufficient |
| Whether analysis waits for media | Default: soft-wait with timeout → partial |
| ClamAV | Phase 2 |
| NotebookLM | Optional human QA only — **not** runtime |
| Dual storage (Chatwoot + Odoo) | Prefer Odoo as analysis SoT; do not depend on Chatwoot CDN for Hub rows |

---

## 23. Phased implementation plan

### Phase 0 — Pilot measurement (1–2 days)

- Scripted getBase64 success rate on 30 recent Dev Needed media ids (read-only probe; no Odoo module upgrade required if run from infra script)
- Measure sizes / durations
- Decide caps

### Phase 1 — Download + store (Test)

- `dev.whatsapp.media` + `media_download` job + worker
- Attach to message; UI open file
- No Dify change yet

### Phase 2 — Enrichment text path

- Image OCR + audio Whisper + short video audio+keyframes
- Enrichment on media model
- Payload → analysis → Dify prompt v2.3
- Failure policy

### Phase 3 — Historical review UX

- Questionnaire media questions
- Corrections + reprocess
- Multi-project + confirmed dashboards show media status

### Phase 4 — Hardening

- Retries, retention, optional vision, document types, malware scan
- Only then consider limited historical backfill windows

---

## 24. Rollback plan

1. Disable media job consumer (n8n inactive / ICP flag `media_enrichment_enabled=False`)
2. Analysis falls back to placeholders + existing `media_weak` behaviour
3. Keep downloaded attachments (or delete via retention job if required)
4. Revert prompt to v2.2
5. No Production/OpenProject changes to roll back

---

## NotebookLM assessment (optional)

| Aspect | Assessment |
|--------|------------|
| Role | Human QA of **sanitized** transcripts/OCR exports |
| Not suitable as | Runtime dependency / API orchestration |
| Privacy | Export only redacted text; never raw patient/clinic media without policy |
| Effort | Manual notebook per project — helpful for spot checks, not ops |
| Verdict | **Optional QA aid only**; do not block implementation |

---

## Success criteria checklist (plan acceptance)

| Criterion | Covered |
|-----------|---------|
| How real file becomes available | Evolution getBase64 via stored ids |
| Where original is stored | `ir.attachment` + `dev.whatsapp.media` |
| How images analysed | OCR (+ optional vision later) |
| How audio transcribed | Existing OpenAI Whisper path |
| How video handled | ffmpeg audio + keyframes + OCR/ASR |
| How enrichment reaches Dify | Text fields in `request_json` |
| How media appears in Odoo | Attachment + media form/chatter |
| How failures represented | retrieval/enrichment states + payload `media_status` |
| Historical non-mutating | Evaluation guards preserved; media flagged |
| Security/storage controlled | Auth fetch, ACL, caps, retention |
| No false “saw the file” claims | Prompt + evidence_status rules |

---

## Stop

This document is analysis and planning only. No modules upgraded, no Dify/n8n changes, no bulk media download, no Production or OpenProject impact.
