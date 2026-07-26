# wa_project_aware_v2.4 — Shadow Evaluation Delivery

Date: 2026-07-25 · Database: `pet_spot_elsahel_test` only.  
**Decision: `ACCEPT_V2_4_FOR_TEST`**  
Live Test analysis path remains **`wa_project_aware_v2.3`** (not activated).

## 1. v2.3 backup location and hashes

Directory:

`docs/whatsapp_hub_consolidation/work_inbox/workflows_prompt_backup_20260725_v24_prechange/`

Dify table: `workflows_prompt_backup_20260725_v24_prechange` (canonical app `dee250c0-7f44-467c-9b0b-86f069bdc17e`).

| Artifact | SHA-256 |
|---|---|
| Prompt v2.3 (`devhub-wa-project-resolver-v2.3.txt`) | `9baf353ccce0fa437ddd827fa50207d32105135ab1fa9c25e77eac09473aef44` |
| Published + draft workflow graphs (identical) | `cd005c4709a32f48210b950c11ce8d8ed978d132337c14a0cb5d1ed7f123847d` |
| Fourteen frozen job payloads | see `meta/frozen_input_hashes.json` |

Also preserved per analysis: raw outputs, validated JSON, meta (Dify run IDs, classification, candidates, WI decision, safety flags).

## 2. New v2.4 prompt file and hash

| Path | SHA-256 |
|---|---|
| `/home/sabry/infra/dify/prompts/devhub-wa-project-resolver-v2.4.txt` | `d11cf47f6c9452bc68c0c3c40298c105a7188fd9f06c4a555f8d1ed8b0c7cd52` |
| Project copy: `docs/.../work_inbox/devhub-wa-project-resolver-v2.4.txt` | same |

Key rules added: `information` classification; technical media ≠ blanket `noise`; empty `project_candidates` ⇒ `project_id=null` / conf `0`; overconfidence restriction; media channels untrusted; Dev Needed baseline project forbidden.

## 3. Shadow workflow / app / run details

| Item | Value |
|---|---|
| Shadow app | `0621c1db-cc51-40ee-844d-37b6a03f5ade` — *Dev Hub WA Project Resolver [SHADOW v2.4 — do not use live]* |
| Published workflow | `c9efdffb-6cd7-4b69-9575-e5c7fb68f50a` |
| Draft workflow | `f41b9097-6124-4f89-bd8e-d53f842b4973` |
| Canonical live app (untouched) | `dee250c0-7f44-467c-9b0b-86f069bdc17e` marked `wa_project_aware_v2.3` |
| Endpoint | `http://127.0.0.1:8090/v1/workflows/run` |
| Meta | `docs/.../work_inbox/shadow_v24_meta.json` |
| Runs dir | `docs/.../work_inbox/shadow_v24_runs/` |

## 4. Frozen input hashes

`workflows_prompt_backup_20260725_v24_prechange/meta/frozen_input_hashes.json` — 42 hashes (payload/raw/validated × 14).  
Payloads are exact `dev_whatsapp_analysis_job.payload_json` bytes; shadow calls used those bytes unchanged (including `prompt_version=wa_project_aware_v2.3` inside the frozen request).

## 5. Fourteen shadow runs

| analysis | sample | shadow_run_id | v2.4 class | proj | conf | wi | safe |
|---|---|---|---|---|---|---|---|
| 336 | dn-canary-* | `3b6e4b81…` | unclear | null | 0 | none | false |
| 337 | | `3406f4b5…` | noise | null | 0 | none | false |
| 338 | | `97fdda9c…` | noise | null | 0 | none | false |
| 339 | dn-canary-aud-eg | `4f11c645…` | information | null | 0 | none | false |
| 340 | | `903a80de…` | information | null | 0 | none | false |
| 341 | | `1ff547be…` | noise | null | 0 | none | false |
| 348 | dn-b2-img-recent | `e20592ec…` | information | null | 0 | none | false |
| 349 | | `59a2b3c8…` | information | null | 0 | none | false |
| 350 | | `c600fea1…` | information | null | 0 | none | false |
| 351 | dn-b2-img-jul19 | `ee5f516e…` | information | null | 0 | none | false |
| 352 | dn-b2-aud-trgulf | `d36b7e41…` | information | null | 0 | none | false |
| 353 | | `7232facc…` | information | null | 0 | none | false |
| 354 | | `ca7d95f4…` | information | null | 0 | none | false |
| 355 | | `e569dc68…` | information | null | 0 | none | false |

Full IDs + outputs: `shadow_v24_runs/analysis_*_shadow.json`, `all_runs.json`.

## 6. Side-by-side comparison (summary)

| id | v2.3 class | v2.4 class | v2.3 proj/conf | v2.4 proj/conf | regression |
|---|---|---|---|---|---|
| 336 | new_task | unclear | null/0 | null/0 | conservative demotion (no false-work inflation) |
| 337 | noise | noise | null/0 | null/0 | — |
| 338 | noise | noise | null/0 | null/0 | — |
| **339** | noise | **information** | **1 / 1.0** | **null / 0** | **overconfidence fixed** |
| 340 | noise | information | null/0 | null/0 | semantic upgrade |
| 341 | noise | noise | null/0 | null/0 | — |
| **348** | noise | **information** | null/0 | null/0 | **anchor PASS** |
| 349–350 | noise | information | null/0 | null/0 | semantic upgrade |
| **351** | noise | **information** | null/0 | null/0 | **anchor PASS** |
| **352** | noise | **information** | null/0 | null/0 | **anchor PASS** (justified non-noise; unclear preferred) |
| 353–355 | noise | information | null/0 | null/0 | semantic upgrade |

Detail: `shadow_v24_runs/comparison_rows.json`, `human_review_table.json`.

## 7. Anchor analysis results

| Anchor | Expected | Result |
|---|---|---|
| **339** | project null, conf 0 | PASS — information, proj null, conf 0 (was PetSpot conf 1.0) |
| **348** | information (or justified unclear) | PASS — information, safe=false |
| **351** | information (or justified unclear) | PASS — information, safe=false |
| **352** | unclear or justified non-noise | PASS — information (TR Gulf, empty candidates ⇒ no invented project) |

## 8. Classification distribution

| | v2.3 | v2.4 |
|---|---|---|
| noise | 13 | 3 |
| new_task | 1 | 0 |
| information | 0 | 10 |
| unclear | 0 | 1 |

## 9. Technical-media noise rate

All 14 segments had usable technical enrichment.

| | Rate |
|---|---|
| v2.3 | **92.9%** (13/14) |
| v2.4 | **21.4%** (3/14) |

Material decrease achieved without converting media into actionable Work Items.

## 10. Project overconfidence count

| | Count (`conf≥0.8` on noise/information/unclear or safe=false) |
|---|---|
| v2.3 | **1** (analysis 339) |
| v2.4 | **0** |

## 11. Safe-to-create-work distribution

| | true | false |
|---|---|---|
| v2.3 | 0 | 14 |
| v2.4 | **0** | **14** |

## 12. Unsupported-ID and leakage audit

- Unsupported project IDs in shadow outputs: **0**
- Unsupported Work Item IDs: **0**
- Cross-project leakage: **0** (all payloads had empty candidate lists; no invented IDs retained after validation)
- Odoo validator now strips baseline `project_id` when candidate list is empty and zeroes overconfident project confidence for non-actionable labels

## 13. Schema validation results

- Schema validity: **14/14 (100%)**
- Parse failures: **0**
- `information` added to `CLASSIFICATIONS_V2` with v1 mapping `information→information` (no longer collapsed to `unclear`)

## 14. Human-review comparison

See `shadow_v24_runs/human_review_table.json`. Anchors 339/348/351/352 all **PASS**. No prior reviewer questionnaire answers overwritten.

## 15. Automated test results

- New: `devhub_whatsapp/tests/test_whatsapp_prompt_v24_shadow.py` (14 cases) — **0 failed**
- Full `/devhub_whatsapp` suite after import wiring: **0 failed, 0 errors of 119 tests** (module stats 141 incl. setup)
- Covers OCR/transcript→information, ambiguous→unclear, overconfidence clamp, injection untrusted, unsupported IDs, schema, shadow contract

## 16. Original-analysis immutability proof

`shadow_v24_runs/immutability_proof.json`:

- raw/validated/meta for analyses **336–341, 348–355**: **mismatches NONE**
- Original Dify run IDs, classifications, review fields unchanged
- Shadow outputs stored only under `shadow_v24_runs/` (separate namespace)

## 17. Inbox and Work Item safety hashes

| Check | Value |
|---|---|
| Inbox hash (20 canary+batch2 msgs) | `47e327d93d386fbf0eb26f9eb4d8c7c2` |
| Source-9 hash (lane/mapping/triage/confirm) | `fdb5f094fba302706b7514de45e03b4c` |
| Dev Needed | `multi_project` / `ambiguous` / `ai_triage_enabled=false` |
| Linked WIs for selected msgs | unchanged (no create/attach this task) |

## 18. Exact files changed (this task)

**In-repo (intended):**

- `devhub_whatsapp/__manifest__.py` → `19.0.9.3.3`
- `devhub_whatsapp/models/dev_whatsapp_analysis_utils.py` — `information` in v2 schema; empty-candidate strip; overconfidence clamp
- `devhub_whatsapp/tests/test_whatsapp_resolution_policy.py` — taxonomy expectation
- `devhub_whatsapp/tests/__init__.py` — import new tests
- `devhub_whatsapp/tests/test_whatsapp_prompt_v24_shadow.py` — new
- `docs/whatsapp_hub_consolidation/work_inbox/devhub-wa-project-resolver-v2.4.txt`
- `docs/.../workflows_prompt_backup_20260725_v24_prechange/**`
- `docs/.../shadow_v24_meta.json`
- `docs/.../shadow_v24_runs/**`
- `docs/.../MEDIA_DN_V24_SHADOW_DELIVERY.md` (this file)

**Outside project git (infra):**

- `/home/sabry/infra/dify/prompts/devhub-wa-project-resolver-v2.4.txt`
- Dify DB: shadow app + workflows; backup table `workflows_prompt_backup_20260725_v24_prechange`

## 19. Git commit hashes and working-tree status

- HEAD tip at evaluation: `fae7119` (Batch 2 delivery) — **no commit created for this shadow task** (not requested).
- Working tree contains many unrelated dirty paths; v2.4-relevant paths listed in §18.

## 20. Final decision

**`ACCEPT_V2_4_FOR_TEST`**

Acceptance gates met: schema 100%, unsupported IDs 0, originals immutable, noise rate materially down, anchors pass, no `safe_to_create_work=true`, no new false actionable classifications.

Note: analysis **336** demoted `new_task→unclear` (conservative). Analysis **352** is `information` rather than `unclear` — accepted as justified non-noise with null project.

## 21. Recommended next step

1. Separate activation PR/task: point Test n8n/Dify live path to v2.4 (or promote shadow app carefully), bump `DEFAULT_PROMPT_VERSION` / source prompt version.
2. Post-activation canary: 4–6 Dev Needed media segments (include OCR + TR-Gulf-like audio + weak-evidence noise).
3. Optional prompt polish: bias ambiguous project-name-only transcripts toward `unclear` instead of `information`.
4. Do **not** enable AI triage on Dev Needed yet.

## 22. No further media enqueued

Confirmed: this task did not enqueue Dev Needed (or any) media download/enrichment jobs.

## 23. Production and OpenProject untouched

Confirmed: only `pet_spot_elsahel_test` + local Dify shadow clone. Production Odoo and OpenProject not modified. Canonical live Dify app remains `wa_project_aware_v2.3`.
