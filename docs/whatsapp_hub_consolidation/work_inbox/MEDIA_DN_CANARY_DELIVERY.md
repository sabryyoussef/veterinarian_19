# Dev Needed media canary — Test only

Status: **CANARY COMPLETE — remaining Dev Needed not enqueued**

Database: `pet_spot_elsahel_test`

Module: `devhub_whatsapp 19.0.9.3.2`

Production / OpenProject: untouched

## 1–2. Selected eight media + reasons

Window: `2026-07-18 09:22:14` → `2026-07-25 09:22:14` UTC  
Source 9 Dev Needed: `multi_project` / `ambiguous` / `ai_triage=false` / `require_human_confirm=true`

| Msg | Media | Type | Timestamp (UTC) | Size (B) | Selection reason |
|----:|------:|------|-----------------|---------:|------------------|
| 6184 | 638 | image | 2026-07-25 09:17:12 | 90595 | Recent captioned upload UI screenshot (Arabic caption) |
| 6167 | 639 | image | 2026-07-25 08:27:08 | 112459 | Recent technical DB-upload screenshot; readable UI text |
| 783 | 640 | image | 2026-07-22 09:33:57 | 92967 | Earlier segment; OpenEduCat/QR attendance UI screenshot |
| 750 | 641 | image | 2026-07-23 12:57:56 | 24099 | Screenshot-cluster peer; **weak/limited OCR** probe (85 chars) |
| 853 | 642 | image | 2026-07-19 08:44:19 | 85429 | Oldest in-window image; chat-screenshot OCR mix |
| 6180 | 643 | audio | 2026-07-25 09:07:10 | 90936 | Egyptian sender `201281890854`; EG Arabic VN (~45s) |
| 766 | 644 | audio | 2026-07-23 11:33:48 | 144597 | Mixed AR/EN technical (`Being called`, inventory/partner) |
| 825 | 645 | audio | 2026-07-19 10:17:23 | 59684 | Different sender; **short** audio (~30s, 59 KB) |

Videos excluded. Already-downloaded pilots excluded. Source mapping not altered.

## 3. Preflight

| Check | Result |
|-------|--------|
| OpenAI `/v1/models` | HTTP 200 |
| Whisper circuit | naturally closed (`open_until` empty; force-close empty) |
| Media worker | idle before enqueue; Test JSON2 base only |
| Tesseract ara+eng | healthy via `--tessdata-dir /data/cache/tessdata` |
| ffmpeg/ffprobe | healthy in preprocessor container |
| Production URL in media worker | none (uses `ODOO_TEST_JSON2_BASE` / Test host) |
| OpenProject called by canary | no |

## 4. Baseline safety

| Metric | Value |
|--------|-------|
| Selected-message safety hash | `04a0a4bb5e7f6d88601d8701d9795be4` |
| Selected inbox states | all `new` |
| Selected linked Work Items | 0 |
| Work Items (active domain) | 59 |
| Work Items (SQL total) | 60 |
| Filestore bytes (before) | 268,416,564 |
| Attachment bytes (before) | 137,432,853 |
| Worker disk free | ~263 GB |

## 5. Download results

8/8 downloads succeeded (100% ≥ 80%). Attachments 7222–7229 stored with checksums. Attempt count 1 each.

## 6. Image OCR results

| Msg | State | OCR len | Lang | Conf | Notes |
|----:|-------|--------:|------|-----:|-------|
| 6184 | succeeded | 698 | en | 0.60 | Upload UI screenshot |
| 6167 | succeeded | 869 | en | 0.69 | Filezilla/module upload UI |
| 783 | succeeded | 608 | en | 0.76 | QR attendance / OpenEduCat UI |
| 750 | succeeded | 85 | mixed | 0.72 | Weak OCR (short/noisy) |
| 853 | succeeded | 145 | mixed | 0.93 | Chat screenshot text |

Usable image enrichment: **5/5 (100%)**. Provider `tesseract` / `tesseract-5-ara+eng`. OCR latencies ~0.6–2.1 s.

## 7. Audio transcription results

| Msg | State | Tx len | Lang | Dur (s) | Whisper ms | Manual review |
|----:|-------|-------:|------|--------:|-----------:|---------------|
| 6180 | succeeded | 514 | ar | 44.6 | 5791 | false |
| 766 | partial | 416 | ar | 61.7 | 13971 | true (unclear segments; mixed EN terms preserved) |
| 825 | succeeded | 338 | ar | 29.7 | 3414 | true |

Usable transcripts: **3/3 (100%)**. Provider `openai` / `whisper-1`. Attempts: 1 each. No 5xx.

## 8. Provider latency and error rate

- Whisper canary error rate: **0%** (0/3)
- Circuit remained closed
- OCR duration_ms: 565–2071
- Whisper duration_ms: 3414–13971

## 9. Dify analyses

Workflow `j3xV5kXRQUu1k0p4` · app `dee250c0-…c17e` · prompt `wa_project_aware_v2.3`

| Analysis | Sample | State | Dify run ID |
|---------:|--------|-------|-------------|
| 336 | dn-canary-img-recent | awaiting_review | `c1180727-dc6d-4f37-9672-7c942c164aad` |
| 337 | dn-canary-img-mid | awaiting_review | `6d9860e9-98d0-4468-853a-4948d30d4668` |
| 338 | dn-canary-img-weak | awaiting_review | `11eb76fe-3d46-468a-9f20-f9c7e251f331` |
| 339 | dn-canary-aud-eg | awaiting_review | `e01a6cfb-ccbd-46bb-a713-2431b9274500` |
| 340 | dn-canary-aud-mixed | awaiting_review | `eb71d4d1-dda5-410d-bc01-46bcd63358ad` |
| 341 | dn-canary-aud-short | awaiting_review | `2fdb2f5a-99be-43e2-9dca-55fc7888b34b` |

All jobs 323–328 **succeeded**. Schema validity: **100%**.

## 10. Sanitized payload examples

Payload keys include: `messages`, `segment_media_summary`, `project_candidates`, `work_item_candidates`, `prompt_version`, `schema_version`.  
Message media items carry OCR/transcript enrichment text only.

- No Base64 / data-URI / binary hits in any of the six payloads
- Example (6167): enrichment `source=image_ocr`, `extracted_text` (folder upload UI), `confidence≈0.69`
- Example (766): enrichment `source=audio_transcript`, mixed AR + `Being called`, `unclear_segments` present, `enrichment_state=partial`

## 11–13. Project candidates / classification / leakage

| Analysis | Classification | safe_to_create_work | contains_work | project_resolution |
|---------:|----------------|---------------------|---------------|--------------------|
| 336 | new_dev_request | false | false | project_id null, conf 0 |
| 337 | noise | false | false | null / 0 |
| 338 | noise | false | false | null / 0 |
| 339 | noise | false | false | **project_id=1 (PETSPOT) conf 1.0** |
| 340 | noise | false | false | null / 0 |
| 341 | noise | false | false | null / 0 |

- Unsupported project IDs: **none**
- Unsupported Work Item IDs: **none**
- Cross-project foreign IDs: **none**
- Quality note: analysis **339** assigns baseline PETSPOT with confidence **1.0** while remaining `noise` / non-creating — over-confident for an ambiguous multi-project source (prompt-tuning candidate, not a hard safety failure)

Classification distribution: noise×5, new_dev_request×1 (all non-creating).

## 14–15. Historical Review questionnaire + corrections

All six analyses are `is_evaluation_result` + `historical_review_lane=multi_project` (Multi-Project Historical Review).

Saved via ORM (no operational approve) for analyses **336–341**:

- `review_final_decision` + `review_usefulness=3` + `review_completed_by=admin`
- Media corrections persisted: `corrected_image_text` / `corrected_audio_transcript` with `[canary-corrected]`
- `media_final_status=accepted`, `media_usefulness_score=3`, `media_review_completed_at` set
- Inbox unchanged; Work Items unchanged on each save

## 16–19. Final states / inbox / WI / hash

| Check | Before | After |
|-------|--------|-------|
| Media terminal | — | 8/8 (7 succeeded, 1 audio partial) |
| Safety hash | `04a0a4bb5e7f6d88601d8701d9795be4` | **identical** |
| Inbox (8 msgs) | all `new` | all `new` |
| Linked WIs | 0 | 0 |
| Active WI count | 59 | 59 |
| Source mapping | ambiguous | ambiguous |
| AI triage | false | false |

## 20. Storage / temp files

| Metric | Before | After | Δ |
|--------|-------:|------:|--:|
| Filestore | 268,416,564 | 269,117,330 | +700,766 |
| Attachments sum | 137,432,853 | 138,133,619 | +700,766 |

Worker job temps cleaned; `wa_media_tmp` retains prior **diag/** artifacts only (not live job spills). Cache attachment copies may remain under preprocessor cache (shared cache), not Odoo filestore growth beyond the eight attachments.

## 21. Automated tests

`TestWhatsappMediaRecoveryHardening` + `TestWhatsappMediaPhase2` + `TestWhatsappMediaBackfill`: **0 failed, 0 error(s) of 37**.

## 22. Browser UAT evidence

Browser MCP tool descriptors were unavailable in this session. Live review was performed via authenticated Odoo ORM equivalent of Multi-Project Historical Review:

- verified six evaluation rows in `multi_project` lane
- saved questionnaire + media corrections for 2 image analyses, 1 weak image, 2 audio analyses
- confirmed persistence of corrected fields and review completion timestamps
- confirmed no inbox / WI mutation after save

## 23. Recommendation

**`PROCEED_IN_SMALL_BATCHES`**

Suggested next batch (do **not** execute now):

- **8 images + 4 audio** (still 0 video)
- concurrency: download/OCR 2, audio 1
- stop rules unchanged
- optionally tune prompt so multi_project evaluations do not emit baseline `project_id` at confidence 1.0 when classification is non-actionable noise

Do **not** enqueue the remaining Dev Needed inventory automatically.

## 24. Production / OpenProject

- No Production module deploy
- Production HTTP `:8027` remained healthy
- No OpenProject package/API mutations from this canary
- Remaining Dev Needed candidates **not** processed
