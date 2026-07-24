# WhatsApp Work Inbox — Test Delivery Report

**Date:** 2026-07-24  
**Branch:** `feature/wa-work-inbox`  
**Branch tip SHA:** `4c1fc00555a3ede2ccf7582fdb87af6082a29195`  
**Working tree:** Work Inbox changes are present on disk (not committed unless/until authorized)  
**Scope:** Plan correction + Phase 1–2 implementation on **Test only**  
**Production:** Not upgraded, not restarted, not written

---

## 1. Corrected plan path

[`docs/whatsapp_hub_consolidation/work_inbox/CORRECTED_WORK_INBOX_PLAN.md`](CORRECTED_WORK_INBOX_PLAN.md)

Corrections A–G applied (untriaged historical default; separate Work linkage; `dev.work.source.message` SoT; before/after context; multi-select in context; restore-to-previous; media in hub).

---

## 2. Test environment identifiers

| Item | Value |
|------|-------|
| Project path | `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel` |
| Test database | `pet_spot_elsahel_test` |
| Test service | `pet_spot_elsahel_test.service` (**user** systemd) |
| Test URL / port | `http://127.0.0.1:8028` (`http_port=8028`) |
| Test config | `/home/sabry/odoo_base/base_odoo_19/config/projects/pet_spot_elsahel_test.conf` |
| Active repo / branch | same tree / `feature/wa-work-inbox` |

### Installed versions (Test) — after upgrade

| Module | Before | After |
|--------|--------|-------|
| `whatsapp_hub` | 19.0.1.12.0 | **19.0.1.13.0** |
| `devhub_whatsapp` | 19.0.9.1.9 | **19.0.9.2.0** |
| `devhub_work` | 19.0.9.1.1 | **19.0.9.1.2** |
| `devhub_analysis` | 19.0.9.1.1 | 19.0.9.1.1 (unchanged) |

---

## 3. Production exclusion verification

| Item | Value |
|------|-------|
| Production database | `pet_spot_elsahel` |
| Production service | `pet_spot_elsahel.service` (**user** systemd; system unit is failed/unused) |
| Production port | **8027** |
| Production PID throughout | **3700925** (unchanged across Test stop/upgrade/restart) |
| Production module versions | still Hub `19.0.1.12.0`, DH WhatsApp `19.0.9.1.9`, Work `19.0.9.1.1` |

Evidence: `env_before.txt`, `env_after.txt` in this folder.

**Note:** Test and Production share the same addons filesystem. Production process was **not** restarted, so it continues running pre–Work-Inbox code in memory. Do **not** restart Production until a separate Production rollout is explicitly approved (new columns would otherwise be missing in the Prod DB).

---

## 4. Branch and commit SHA

- Branch: `feature/wa-work-inbox`
- Tip: `4c1fc00555a3ede2ccf7582fdb87af6082a29195`
- No push / no merge performed
- No git commit created in this delivery (awaiting authorization; repo also contains unrelated dirty modularization changes)

---

## 5. Exact files added / changed (Work Inbox scope)

### Docs
- `docs/whatsapp_hub_consolidation/work_inbox/CORRECTED_WORK_INBOX_PLAN.md`
- `docs/whatsapp_hub_consolidation/work_inbox/*` (this report + evidence logs/dump)

### `whatsapp_hub`
- `whatsapp_hub/__manifest__.py` → 19.0.1.13.0
- `whatsapp_hub/models/whatsapp_message.py` — `media_kind`, `has_media`, classification
- `whatsapp_hub/models/whatsapp_hub_dashboard.py` — Work Inbox tile / quick action
- `whatsapp_hub/migrations/19.0.1.13.0/post-migrate.py` — media backfill only
- `whatsapp_hub/tests/test_whatsapp_media_kind.py`
- `whatsapp_hub/tests/__init__.py`

### `devhub_work`
- `devhub_work/__manifest__.py` → 19.0.9.1.2
- `devhub_work/models/dev_work.py` — `whatsapp_message_id` on `dev.work.source.message`

### `devhub_whatsapp`
- `devhub_whatsapp/__manifest__.py` → 19.0.9.2.0 (+ assets/data)
- `devhub_whatsapp/models/dev_whatsapp_inbox.py` — inbox state, events, RPCs
- `devhub_whatsapp/models/dev_whatsapp_hub_message.py` — source FK stamping
- `devhub_whatsapp/models/__init__.py`
- `devhub_whatsapp/wizards/dev_whatsapp_create_work_wizard.py`
- `devhub_whatsapp/wizards/__init__.py`
- `devhub_whatsapp/views/dev_whatsapp_work_inbox_views.xml`
- `devhub_whatsapp/views/dev_whatsapp_menus.xml`
- `devhub_whatsapp/security/ir.model.access.csv`
- `devhub_whatsapp/static/src/work_inbox/work_inbox.{js,xml,css}`
- `devhub_whatsapp/tests/test_work_inbox.py`
- `devhub_whatsapp/tests/__init__.py`

---

## 6. Module versions before / after

See tables in §§2–3. Production unchanged.

---

## 7. Database migration performed (Test)

1. Backup: `pet_spot_elsahel_test_pre_work_inbox_20260724T145701Z.dump` (this folder)
2. `-u whatsapp_hub,devhub_work,devhub_whatsapp` on `pet_spot_elsahel_test` only (`--http-port=8128`)
3. Columns added: `whatsapp_message.inbox_state`, `previous_inbox_state`, `media_kind`, `has_media`; `dev_work_source_message.whatsapp_message_id`
4. Model added: `dev.whatsapp.inbox.event`
5. Client action tag: `devhub_whatsapp_work_inbox`

Post-migration counts:

- All **3731** historical messages → `inbox_state=untriaged`
- Media backfill applied (e.g. image/audio/video/none…)

---

## 8. Historical-message activation policy

**Locked preferred policy (implemented):**

1. Existing rows → `untriaged`
2. New successful ingest creates → `new` (`whatsapp_inbox_admit_new` context; never on dedupe)
3. Historical enter Inbox only via **Add to Work Inbox** / triage actions
4. **No** date-cutoff bulk admit (d30≈1182 would flood)
5. Backfill only `media_kind` / `has_media` (no `raw_payload` mutation)

---

## 9. Final data-model design

### Hub (`whatsapp.message`)
- `media_kind`: none|image|video|audio|document|sticker|reaction|unknown
- `has_media`: boolean

### Dev Hub WhatsApp inherit
- `inbox_state`: untriaged|new|pending|ignored|actioned (default untriaged)
- `previous_inbox_state`
- computed: `has_work_item`, `work_item_count`, `primary_work_item_id`, `work_item_ids`, `primary_work_phase`
- `dev.whatsapp.inbox.event` audit transitions

---

## 10. Final Work Item relation design

- Source of truth: `dev.work.source.message` M2M to `dev.work.item`
- Additive FK: `whatsapp_message_id` (nullable, indexed, ondelete=set null)
- Convenience computes on Hub message from source links (not SoT)
- After create: default Inbox **`actioned`**; wizard may keep **`pending`**
- Duplicate create blocked; additional Work requires manager + explicit flag
- Bi-nav: Open Work from message / Open WhatsApp Context from Work Item with `focus_message_id` + `highlight_message_ids`

---

## 11. Security groups and ACL behavior

| Capability | Groups |
|------------|--------|
| Work Inbox triage + RPCs | **Dev Hub User / Manager only** (Chatwoot whitelist / Hub messages — no WhatsApp Hub User group required) |
| Create Work | Dev Hub User (+ project read without sudo) |
| Additional Work | Dev Hub Manager |
| Hub message / conversation / group read for DH | additive ACLs in `devhub_whatsapp` (`access_whatsapp_*_dh_*`) |

Message searches use normal Hub message ACLs granted to Dev Hub users. No project-access bypass via sudo on Work create/open.

---

## 12. Automated test results

Command: `--test-tags=/devhub_whatsapp:TestWhatsappWorkInbox,/whatsapp_hub:TestWhatsappMediaKind`

**Result: 0 failed, 0 errors of 10 tests** (`automated_tests_2.log`)

Covers: untriaged default, ingest→new, dedupe preserve, ignore/restore, context before/after + load older/newer, inbox domain, mixed-conversation reject, multi-message Work + duplicate + additional manager path, media_kind.

---

## 13. OWL / API UAT results (Test)

Shell UAT (`uat_shell.txt`): **37/37 PASS** including triage, context window, multi-select rules, Create Work, bi-nav highlight, ingest smoke, historical not flooded, Campaign/Discuss/outbound models present.

Browser OWL click-through screenshots: not captured in this run (API/client-action contract validated; UI assets registered). Manual path below.

---

## 14. Screenshot / evidence paths

Folder: `docs/whatsapp_hub_consolidation/work_inbox/`

- `CORRECTED_WORK_INBOX_PLAN.md`
- `env_before.txt` / `env_after.txt`
- `upgrade_test.log` / `upgrade_test_2.log` / `upgrade_test_3.log`
- `automated_tests.log` / `automated_tests_2.log`
- `uat_shell.txt` / `uat_shell_stderr.txt`
- `pet_spot_elsahel_test_pre_work_inbox_20260724T145701Z.dump`

---

## 15. Ingest smoke-test result

PASS — new Chatwoot-normalized ingest created Hub message with `inbox_state=new`; re-ingest duplicate preserved `pending` triage (`uat_shell` 31/32).

---

## 16. Campaign / Discuss / outbound regression

PASS at smoke level — models present; no Campaign/Discuss/outbound code paths modified in this delivery. No Campaign flags flipped.

---

## 17. Test URL and navigation path

1. Open `http://127.0.0.1:8028/web`
2. Log in as a user with **Dev Hub User** (same people who already use DH WhatsApp / whitelist intake)
3. **WhatsApp → DH WhatsApp → Work Inbox**  
   (also: General Dashboard → Work Inbox tile; message form **Open Chat Context**; conversation **Open in Work Inbox**; Work Item **WhatsApp Context**)
4. Client action tag / path: `devhub_whatsapp_work_inbox` / `wa-work-inbox`

---

## 18. Known limitations

- Phase 1 media = chips/labels only (no Evolution download / preview players)
- Selecting context messages does not auto-change Inbox state
- Shared addons path: Production restart without Prod upgrade is unsafe until rollout
- Repo working tree remains dirty with unrelated modularization files; Work Inbox not isolated into a commit yet
- OWL browser screenshot pack not attached (shell UAT covers behaviors)
- Restricted-user project denial covered by automated AccessError paths / create checks; full UI ACL matrix for every role not screenshot-documented

---

## 19. Rollback steps (Test)

1. `systemctl --user stop pet_spot_elsahel_test.service`
2. Restore dump:  
   `pg_restore -h localhost -U odoo -d pet_spot_elsahel_test --clean --if-exists <dump>`  
   (or drop/recreate DB then restore)
3. Optionally check out prior module versions / revert Work Inbox files
4. `systemctl --user start pet_spot_elsahel_test.service`
5. Confirm Production still on pre-upgrade versions / PID

---

## 20. Explicit confirmation — Production not changed

- No Production `-u`
- No Production restart
- No Production DB writes from this delivery
- Production module versions unchanged
- Production PID `3700925` unchanged throughout

**Stop condition honored:** Test implementation + Test UAT + this report complete. Awaiting explicit human approval before any Production preparation.
