# Final Readiness Closure — Observation Gate + Deploy Reproducibility

**Date:** 2026-07-26  
**Observation t0:** `2026-07-26T05:18:28Z`  
**Observation may close only after:** `2026-07-27T05:18:28Z`  
**Production upgrade:** **NOT performed**  
**sudo reconciliation / final backup:** **NOT executed**

---

## Decision

```text
NOT READY
```

### Why
The real 24-hour observation window is **incomplete** (~1.4 h elapsed at this report; ~22.6 h remaining). All other closure items are prepared or blocked by that gate / by the dirty-tree reproducibility requirement (resolved via an offline deploy-candidate package, not a clean commit).

| Gate | Met? |
|------|------|
| Real 24h observation passed | **No** (in progress) |
| Dirty tree → reproducible deployment candidate | **Partial** — package built; no reviewed commit yet |
| Exact module versions + upgrade set confirmed | **Yes** |
| New clone rehearsal required? | **No** — candidate == prior rehearsal disk code |
| Stale system-unit commands ready | **Yes** (not executed) |
| Final backup preflight passed | **Yes** (not executed) |
| Rollback code + DB versions reproducible | **Yes** (documented) |

---

## 1. Real 24-hour observation — status

| Item | Value |
|------|-------|
| t0 | `2026-07-26T05:18:28Z` |
| Earliest close | `2026-07-27T05:18:28Z` |
| Now (report) | `2026-07-26T06:40Z` |
| Elapsed | ~1.4 h |
| Remaining | ~22.6 h |
| Complete? | **No — do not close** |

### Sampling infrastructure (fixed this session)
Previously only **1** sample existed and **no hourly scheduler** was installed. Now:

* User timer `obs24-sampler.timer` enabled (`OnCalendar=hourly`, Persistent=true)
* Next fire ~ hourly
* Samples file: `docs/.../work_inbox/obs24_samples.ndjson`
* Samples collected so far: **2** (t0 + 06:39Z)
* Expected by close: **≥25** hourly samples (t0 + 24 hours)
* Missing hours so far: hours between 05:18 and 06:39 were not sampled (gap before timer install) — one historical gap; forward coverage should be continuous

### Interim metrics (t0 → now) — **not** a closing report

| Metric | Result | Notes |
|--------|-------:|-------|
| Samples expected | ≥25 by close | 2 collected so far |
| Missing sampling hours | 1 gap (pre-timer) | Timer now active |
| Messages since t0 | **0** | Quiet; real=0 synth=0 |
| Conversations affected | 0 | |
| Debounce schedules / resets | 0 / pending cleared | `src9 pending_analysis_after=false` |
| Analyses created since t0 | **0** | |
| Analyses reused / duplicate fingerprints | 0 / 0 | No new fingerprints |
| Dify successes / failures | 0 / 0 | No new jobs |
| Validation failures | 0 | |
| Stuck pending analyses | 0 | |
| Pending jobs older than 15m | 0 | |
| Dead-letter **total** | **7** | Prior UAT cleanup — **known, not hidden** |
| Dead-letter **new since t0** | **0** | No growth |
| Unexpected Dev Hub WI (AI, non–Phase-B) | 0 | |
| Unexpected Odoo tasks (non-UAT) | 0 | |
| Unexpected OpenProject creates | 0 | Option A / OP not in play |
| Health status counts | `idle=50` | After 1.16.0 semantics |
| Genuine delayed / gap / failed | **0 / 0 / 0** | |
| Service restarts / outages (Test) | none observed | Test user unit active |

**Flags on Dev Needed (#9):**  
`ai_triage_enabled=true`, `auto_analysis_enabled=true`, `analysis_review_only=true`, debounce=3, `openproject_create_allowed=false`, prompt=`wa_project_aware_v3.0`.

### Closing procedure (after `2026-07-27T05:18:28Z` only)
1. Ensure ≥24 samples spanning t0→t0+24h (or document any timer gaps).  
2. Aggregate `obs24_samples.ndjson` + SQL deltas from t0.  
3. Require: zero duplicate default analyses; zero accidental WI/task/OP; zero stuck debounce; zero new dead-letter growth; zero genuine delayed/gap/failed; no analysis storm; no lost messages.  
4. Only then re-open readiness.

---

## 2. Dirty addon tree audit

| Item | Value |
|------|-------|
| Repository root | `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel` |
| Branch | `feature/petspot-vet-shop-phase6-pricing-expansion` |
| HEAD | `f6e701ec754ea8168d4fa93051c5162a5ad940d1` |
| HEAD subject | Phase 5: add petspot_vet_shop Vetution-style shop UX on Test. |
| Porcelain total | **232** (76 modified, 17 deleted, 139 untracked) |
| Tracked diff vs HEAD | 93 files, +7280 / −10555 |

### Classification (porcelain)

| Category | Count | Examples |
|----------|------:|----------|
| WhatsApp AI delivery (incl. hub consolidation docs / OP sync) | **134** | `whatsapp_hub/*`, `devhub_whatsapp/*`, `docs/whatsapp_hub_consolidation/*`, `openproject_sync/*`, `devhub_openproject/` |
| Unrelated (vet shop / modular DevHub / Evolution chat / bridge) | **94** | `dev_session_hub/*`, `petspot_vet_shop` line, `evolution_whatsapp_chat/*`, `integration_bridge_core/*` |
| Evidence / filestore clones | **2** | `.filestore_func_matrix/`, `.filestore_test_modular_mig/` |
| Generated / other docs | **3** | misc docs |

### Critical reproducibility facts
* **Test runs from this dirty working tree** (not clean HEAD).
* **Clean checkout at HEAD would NOT contain required delivery:**

| Module | HEAD version | Disk / Test version |
|--------|--------------|---------------------|
| `whatsapp_hub` | **19.0.1.0.1** | **19.0.1.16.0** |
| `devhub_whatsapp` | **19.0.9.3.2** | **19.0.9.5.0** |
| `devhub_work` | 19.0.9.1.4 | 19.0.9.1.4 |
| `devhub_analysis` | 19.0.9.1.1 | 19.0.9.1.1 |

* Evidence dumps correctly **outside** the repo under `base_odoo_19/backups/` (not committed). Two filestore clones incorrectly sit as untracked under the project root — do not commit.

**No commits / no discards performed.**

### Deployment reproducibility plan (no commit authorization)

**Preferred later:** one reviewed commit (or small set) containing **only** the four Option-A modules (+ tests), excluding unrelated vet-shop / evidence / filestore.

**Now (authorized offline package):**

```text
/home/sabry/odoo_base/base_odoo_19/backups/deploy_candidate_wa_ai_20260726T064007Z/
```

Contents:
* `target_module_versions.txt` / `head_module_versions.txt`
* `patches/upgrade_modules_vs_HEAD.patch` (sha256 `e0fa68fd…`)
* `patches/untracked_new_files.tgz` (53 new files, sha256 `a70db44d…`)
* `checksums/upgrade_modules.sha256` (158 files)
* `copy_list/*` manifests
* `DEPLOY_CANDIDATE_META.txt`, `README.md`

Materialize on a clean tree:
1. Check out base HEAD (or rollback commit).  
2. Apply patch + extract untracked tarball.  
3. `sha256sum -c checksums/upgrade_modules.sha256`.  
4. Confirm versions match `target_module_versions.txt`.

**Rollback code:** Production DB restore to pre-upgrade dump + prior module versions  
`whatsapp_hub 19.0.1.14.0`, `devhub_whatsapp 19.0.9.1.9`, `devhub_work 19.0.9.1.1`, `devhub_analysis 19.0.9.1.1`  
(clean HEAD alone is **not** a Prod rollback of the AI delivery).

---

## 3. Upgrade set revalidation

| Module | Target (disk / Test DB) | Prod DB now | In upgrade set? |
|--------|-------------------------|-------------|-----------------|
| `whatsapp_hub` | **19.0.1.16.0** | 19.0.1.14.0 | **Yes** |
| `devhub_work` | **19.0.9.1.4** | 19.0.9.1.1 | **Yes** (required for view XML id) |
| `devhub_analysis` | **19.0.9.1.1** | 19.0.9.1.1 | **Yes** (keep ordered with set) |
| `devhub_whatsapp` | **19.0.9.5.0** | 19.0.9.1.9 | **Yes** |

Command remains:

```text
-u whatsapp_hub,devhub_work,devhub_analysis,devhub_whatsapp
```

**New isolated clone upgrade:** **not required** — deployment candidate is the same disk tree already proven on `pet_spot_elsahel_mig_rehearsal` (exit 0, safe AI defaults, rollback restore OK). Re-run only if the four modules change after this package’s checksums.

---

## 4. Supervision reconciliation — prepared, not executed

Immediate revalidation:

| Check | Result |
|-------|--------|
| User unit active | **active / enabled**, MainPID **1085909** |
| System unit | **failed / enabled** (stale duplicate) |
| Port 8027 | Only user Odoo PIDs (1085909 + workers) |
| Linger | **yes** |
| User unit file | `~/.config/systemd/user/pet_spot_elsahel.service` sha256 `27cd4071…` |
| System unit file | `/etc/systemd/system/pet_spot_elsahel.service` sha256 `f38f8bdc…` (different) |

### Authorized command block (do **not** run until explicitly authorized)

```bash
# 0) Preflight — prove user unit owns 8027
systemctl --user status pet_spot_elsahel.service --no-pager
ss -ltnp | rg ':8027'
curl -s -o /dev/null -w 'login=%{http_code}\n' http://127.0.0.1:8027/web/login   # expect 200
USER_PID=$(systemctl --user show -p MainPID --value pet_spot_elsahel.service)

# 1) Disable / stop / reset / mask STALE SYSTEM unit only (does not stop user unit)
sudo systemctl disable --now pet_spot_elsahel.service
sudo systemctl reset-failed pet_spot_elsahel.service
sudo systemctl mask pet_spot_elsahel.service

# 2) Verify live user unit UNAFFECTED
systemctl --user is-active pet_spot_elsahel.service   # active
test "$(systemctl --user show -p MainPID --value pet_spot_elsahel.service)" = "$USER_PID"
ss -ltnp | rg ':8027'
curl -s -o /dev/null -w 'login=%{http_code}\n' http://127.0.0.1:8027/web/login
systemctl is-enabled pet_spot_elsahel.service         # masked

# Rollback / unmask (only if needed; do NOT re-enable system unit as canonical)
sudo systemctl unmask pet_spot_elsahel.service
# Keep user unit as the sole owner. Do not: sudo systemctl enable --now pet_spot_elsahel.service
```

---

## 5. Final backup preflight — ready, not executed

| Check | Result |
|-------|--------|
| Disk free | **243 G** on `/` (42% used) |
| DB name | `pet_spot_elsahel` |
| Filestore path | `.../projects/pet_spot_elsahel/.filestore/filestore/pet_spot_elsahel` (**99 M**) |
| Destination | `/home/sabry/odoo_base/base_odoo_19/backups/pet_spot_elsahel_preupgrade_<TS>/` |
| PostgreSQL credentials | Present in conf (`db_password_present=True`); **not printed** |
| Tools | `pg_dump`, `pg_restore`, `sha256sum`, `tar` available |
| Expected dump size | ~**18 M** (custom format; last fresh dump) |
| Expected filestore archive | ~**99 M** (~30–40 M compressed typical) |
| Restore validated | Yes — Phase 5 clone + rollback |
| Secrets in logs | Use masked conf copy; never `echo` password |

Final dump still requires separate authorization (runbook in `AI_PIPELINE_OPS_PHASES_1_5_READINESS.md` §Phase 4).

---

## Controlled rollout sequence (only after READY + separate authorization)

1. Close observation after `2026-07-27T05:18:28Z` with passing metrics.  
2. Prefer: commit reviewed Option-A modules **or** materialize `deploy_candidate_wa_ai_20260726T064007Z` and verify checksums.  
3. Execute §4 supervision mask of system unit.  
4. Execute final backup runbook; verify `SHA256SUMS`.  
5. `systemctl --user stop pet_spot_elsahel.service`  
6. Upgrade:

```bash
/home/sabry/odoo_base/base_odoo_19/venv19/bin/python3 \
  /home/sabry/odoo_base/base_odoo_19/odoo19/odoo19/odoo-bin \
  -c /home/sabry/odoo_base/base_odoo_19/config/projects/pet_spot_elsahel.conf \
  -d pet_spot_elsahel \
  -u whatsapp_hub,devhub_work,devhub_analysis,devhub_whatsapp \
  --stop-after-init --no-http
```

7. `systemctl --user start pet_spot_elsahel.service`  
8. Smoke: `/web/login`, `/whatsapp_hub/health`, `/bridge/inbound/health`; AI flags all **off** / review-only; no `:9` Evolution stubs; no WI/task growth.  
9. Monitor ≥24 h. **Do not** enable AI or auto-create without further authorization.

### Stop / rollback triggers
Health ≠ 200; ingest/uniqueness failures; unexpected WI/task/OP; job storm; dual bind on 8027 → restore pre-upgrade dump + filestore + prior module tree; restart user unit.

---

## Artifacts
* `docs/.../work_inbox/AI_PIPELINE_FINAL_READINESS_CLOSURE.md` (this file)
* `obs24_t0.txt`, `obs24_samples.ndjson`, `obs24_sampler.sh`
* `~/.config/systemd/user/obs24-sampler.{service,timer}`
* `dirty_tree_manifest.txt`
* `backups/deploy_candidate_wa_ai_20260726T064007Z/`
* Prior: `AI_PIPELINE_OPS_PHASES_1_5_READINESS.md`
