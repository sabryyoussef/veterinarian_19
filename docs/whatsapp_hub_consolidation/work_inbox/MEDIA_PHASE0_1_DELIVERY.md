# WhatsApp Media Phase 0–1 Delivery Report

**Date:** 2026-07-25  
**Environment:** `pet_spot_elsahel_test` only  
**Module:** `devhub_whatsapp` **19.0.9.2.27 → 19.0.9.2.28**  
**Production:** `devhub_whatsapp` remains **19.0.9.1.9** (untouched)  
**Dify / analysis n8n `j3xV5kXRQUu1k0p4`:** untouched (`updatedAt` still 2026-07-24)  
**OpenProject:** untouched  

---

## 1. Retrieval probe sample (Phase 0)

Probe script: `docs/.../work_inbox/media_phase0_probe.py`  
Results: `docs/.../work_inbox/media_phase0_results/probe_latest.json`

| Metric | Value |
|--------|------:|
| Sample size | 31 |
| Recent recovered_original | **18 / 19 = 94.7%** |
| Older recovered_original | **0 / 12 = 0%** |
| Image / audio / video / document originals recovered | yes / yes / yes / yes (recent) |

Failures on older media return HTTP 400 from Evolution with  
`Failed to fetch stream from https://mmg.whatsapp.net/...` → classified as **expired** (WhatsApp CDN retention), not bad keys.

Hub has **0 outbound** media rows → no live `fromMe=true` samples; primary key uses `fromMe=false` + `participant` for `@g.us`.

### Exit criteria

| Criterion | Result |
|-----------|--------|
| Recent ≥ 80% | **PASS (94.7%)** |
| ≥1 image, audio, video | **PASS** |
| MIME sniff OK | **PASS** |
| Keys understood | **PASS** |
| No credentials in logs | **PASS** |
| Temp files removed | **PASS** |
| Old-media rate documented | **PASS (0%)** |

---

## 2. Success rate by media type and age

| Kind | Recent success | Older success |
|------|---------------:|--------------:|
| image | 7/7 in recent strata | 0/4 |
| audio | 6/6 | 0/4 |
| video | 3/4 (1 CDN fail) | 0/3 |
| document | 1/1 recent | 0/1 |

---

## 3. Confirmed Evolution key structure

```json
{
  "remoteJid": "<group_jid>",
  "id": "<evolution_message_id>",
  "fromMe": false,
  "participant": "<sender_jid>"
}
```

- Instance: `sabry min` (URL-encoded in path)
- Endpoint: `POST /chat/getBase64FromMediaMessage/{instance}`
- Auth: `apikey` header
- Success HTTP status: **201** (not only 200)
- `fromMe` derived from `whatsapp.message.direction == 'out'`

---

## 4. Phase 1 architecture

```text
Queue Media Download (Odoo UI / shell)
→ dev.whatsapp.media (pending)
→ dev.whatsapp.media.job (media_download)
→ worker: Evolution getBase64
→ Odoo service_complete (base64 → ir.attachment)
→ media.retrieval_state = downloaded | expired | failed
```

Separate from `dev.whatsapp.analysis.job`. No Dify. No analysis workflow binary path.

---

## 5. Exact files changed

### Odoo (`devhub_whatsapp`)

- `models/dev_whatsapp_media_utils.py` (new)
- `models/dev_whatsapp_media.py` (new)
- `models/dev_whatsapp_media_job.py` (new)
- `models/__init__.py`
- `security/devhub_whatsapp_security.xml`
- `security/ir.model.access.csv`
- `data/ir_config_parameter_media.xml` (new)
- `views/dev_whatsapp_media_views.xml` (new)
- `views/dev_whatsapp_menus.xml`
- `__manifest__.py` → 19.0.9.2.28
- `tests/test_whatsapp_media_phase1.py` (new)
- `tests/__init__.py`

### Infra

- `/home/sabry/infra/devhub-wa-media-worker/worker.py` (new)

### Docs / probe

- `docs/.../MEDIA_ENRICHMENT_PLAN.md` (prior)
- `docs/.../media_phase0_probe.py`
- `docs/.../media_phase0_results/*`
- this report

---

## 6. Module versions

| DB | Before | After |
|----|--------|-------|
| `pet_spot_elsahel_test` | 19.0.9.2.27 | **19.0.9.2.28** |
| `pet_spot_elsahel` (Prod) | 19.0.9.1.9 | **19.0.9.1.9** |

---

## 7. Media / job model details

### `dev.whatsapp.media`

Identity unique: `(source_provider, source_instance, source_media_id, media_asset_index)`  
SHA-256 stored in `checksum` (attachment reuse by checksum across messages).  
Retrieval states: pending/downloading/downloaded/unavailable/expired/failed.  
Enrichment placeholders present but unused.  
`is_historical_review` supported.

### `dev.whatsapp.media.job`

Kind: `media_download` only.  
Lease/token/retry/dead_letter pattern mirrored from analysis jobs.  
Service group: `group_dev_hub_wa_media_service` (also granted to `svc-dev-hub-wa-analysis-test` for pilot).

Limits (ICP): image 15MB, audio 25MB, video 100MB, document 25MB.

---

## 8. Worker

- Path: `/home/sabry/infra/devhub-wa-media-worker/worker.py`
- JSON-2: `service_lease` / `service_start` / `service_complete` / `service_fail`
- Evolution fetch outside Odoo HTTP workers
- MIME sniff; ZIP blocked; temp file write+delete
- Does not modify `j3xV5kXRQUu1k0p4`

---

## 9. Test results

```text
TestWhatsappMediaPhase1: 0 failed, 0 error(s) of 14 tests
```

Covers: key reconstruction, fromMe, MIME/size, expired classification, attachment store, checksum reuse, lease/complete, dead-letter, ACL, no inbox mutation, no OpenProject outbox growth.

---

## 10. Pilot record IDs

**Messages enqueued (21):**  
716, 734, 736, 738, 411, 415, 418, 4022, 4054, 724, 751, 756, 762, 408, 414, 4118, 4123, 718, 500, 3965, 439  

**Media rows:** 32–52  
**Jobs:** 11–31  
**Attachments created:** 5720–5734 (15 files)

Groups: Dev Needed (14) + Torz Trading (7).

---

## 11. Attachment counts and storage

| Outcome | Count | Bytes |
|---------|------:|------:|
| downloaded image | 7 | 803,150 |
| downloaded audio | 6 | 452,421 |
| downloaded video | 2 | 40,174,470 |
| expired | 5 | 0 |
| failed (DOCX/ZIP container blocked) | 1 | 0 |
| **Pilot attachment total** | **15** | **~41.4 MB** |

---

## 12. UAT evidence

Browser MCP was unavailable in this session. Evidence instead:

1. **Odoo MCP `search_records`** on `dev.whatsapp.media` — 21 pilot rows with states/attachments (see §10).
2. **Filestore files present** for att 5720 (jpeg), 5727 (oga), 5733/5734 (mp4).
3. **Sample image exported:** `media_phase0_results/uat_sample_image_att5721.jpg`
4. UI wired: Media section on `whatsapp.message` + actions Queue/Retry/Open; menus Media Assets / Media Jobs.
5. Inbox snapshot: **0 changes** across pilot message IDs.
6. No Work Items created from media path (latest WI ids remain from 2026-07-24).
7. Analysis n8n workflow still last updated 2026-07-24; Dify prompt v2.2 not modified.

Manual browser check recommended: open message 716 → Media → Open Attachment.

---

## 13. Failure distribution (pilot)

| Code / state | Count | Notes |
|--------------|------:|-------|
| downloaded | 15 | image/audio/video |
| expired | 5 | older CDN streams |
| mime_rejected | 1 | DOCX is ZIP (`PK…`); Phase-1 blocks ZIP containers |

---

## 14. Remaining risk — old media retention

Older WhatsApp media (**pre ~2026-07-01** in this sample) is **not recoverable** via Evolution getBase64 once `mmg.whatsapp.net` streams fail.  
Do **not** schedule full historical backfill. Limit future backfill to recent windows after a fresh hit-rate probe.

---

## 15. Recommendation on Phase 2

**Proceed with Phase 2 enrichment** for **recent downloaded media only**, with:

1. OCR on images already in `ir.attachment`
2. Whisper on audio attachments (existing OpenAI path)
3. Short-video audio extract + sparse keyframes later
4. Still no bulk historical download
5. DOCX/PDF parsing as a controlled Phase-2b (ZIP/Office needs safe extract policy)

Phase 1 retrieval/storage is proven for recent media.

---

## 16. Confirmation — untouched systems

| System | Status |
|--------|--------|
| Dify canonical app / prompt | Untouched |
| n8n analysis workflow `j3xV5kXRQUu1k0p4` | Untouched |
| Production DB / module | Untouched (19.0.9.1.9) |
| OpenProject | Untouched |

---

## Stop

Phase 0 and Phase 1 complete. No OCR, transcription, keyframe extraction, or Dify payload enrichment implemented in this phase.
