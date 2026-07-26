# Dev Hub Operational Baseline (Frozen)

**Frozen at:** 2026-07-23  
**Verdict context:** Governed merge + Test deploy PASS (WI 3324)  
**Evidence:** `docs/devhub_modularity/operational_rollout_stabilization/baseline/`

This document is the authoritative operational pin for Live Test Dev Hub. Do not install Dev Hub on Production.

---

## Git

| Item | Value |
|------|--------|
| Branch | `feature/devhub-modularization-whatsapp` |
| HEAD SHA | `4c1fc00555a3ede2ccf7582fdb87af6082a29195` |
| Subject | `fix(devhub_approval): import DevWorkPlan for exact-hash approval` |
| Proven Test deploy merge SHA | `0b516d5af4ae24ab0d1575e3eff3b2682a5bb439` |
| Proven PR head commit | `22c3cdc0d3bf82b418a6b70c7a0d698e09ca8786` |
| Working tree | **dirty** (~106 porcelain entries) — modular `devhub_*` trees are largely untracked relative to this pin; WhatsApp/OP/unrelated edits also present |
| Unrelated dirty | Preserve — do not discard developer work |

**Operational note:** Runtime Dev Hub code is loaded from the Live Test `addons_path` project root. The git pin marks the last committed stabilization fix; modular modules may still be untracked pending a separate commit/PR of the modular tree.

---

## Odoo — Live Test

| Item | Value |
|------|--------|
| DB | `pet_spot_elsahel_test` |
| Port | `8028` |
| Service | `pet_spot_elsahel_test.service` |
| Config | `config/projects/pet_spot_elsahel_test.conf` |
| Runtime | Canonical addons only (`odoo/addons` + `enterprise` + `projects/pet_spot_elsahel`) |
| Meta module | `dev_session_hub` **19.0.9.1.0** installed |

### Installed Dev Hub module versions

| Module | Installed version |
|--------|-------------------|
| devhub_core | 19.0.9.0.1 |
| devhub_work | 19.0.9.1.0 |
| devhub_analysis | 19.0.9.1.0 |
| devhub_plan | 19.0.9.1.0 |
| devhub_approval | 19.0.9.1.0 |
| devhub_generation | 19.0.9.1.0 |
| devhub_session | 19.0.9.0.0 |
| devhub_execution | 19.0.9.1.0 |
| devhub_git | 19.0.9.0.0 |
| devhub_github | 19.0.9.0.0 |
| devhub_deploy | 19.0.9.0.0 |
| devhub_outbox | 19.0.9.0.0 |
| devhub_openproject | 19.0.9.1.0 |
| devhub_whatsapp | 19.0.9.0.2 |
| devhub_workflow | 19.0.9.1.0 |
| devhub_code_analysis | 19.0.9.1.0 |
| devhub_odoo_runtime | 19.0.9.0.0 |
| devhub_infrastructure | 19.0.9.0.0 |
| dev_session_hub | 19.0.9.1.0 |

---

## GitHub App

| Role | App slug | App ID | Installation ID |
|------|----------|--------|-----------------|
| PR | `sabry-uat-agent` | `4340040` | `147639376` |
| Merge | `sabry-uat-merge-agent` | `4341059` | `147666583` |

| Item | Path / config |
|------|----------------|
| Credential root | `/srv/devhub/credentials/github/` |
| PR PEM | `app-4340040.pem` (mode 600, owner `devworker`) |
| Merge PEM | `merge-app-4341059.pem` (mode 600, owner `devworker`) |
| PR broker | `mint-devhub-pr-token` (mode 700) |
| Merge broker | `mint-devhub-merge-token` (mode 700) |
| PR profile | `gh-profile/` |
| Merge profile | `merge-gh-profile/` |
| PR target | `dev.git.pr.target` **735** |
| Merge target | `dev.git.merge.target` **105** |
| Token method | Short-lived GitHub App installation token via broker mint; host `hosts.yml` written under profile; secrets never returned to Odoo RPC |

---

## Worker infrastructure

| Item | Value |
|------|--------|
| Worker OS user | `devworker` uid **1100** |
| Bare mirror | `/srv/devhub/repos/petspot.git` |
| Worktree root | `/srv/devhub/worktrees` (layout `…/petspot/DW-<id>`) |
| Main snapshot | `/srv/devhub/main-snapshots/petspot` |
| Registry working_directory | main snapshot (not developer dirty checkout) |
| Remote | `git@github.com:sabryyoussef/veterinarian_19.git` |
| Default branch | `staging` |
| Execution class | `safe_for_isolated_worktree` + `agent_execution_allowed` |
| Physical git ops | Require effective uid **1100** |
| `safe.directory` | Passed per-invocation for worker-owned worktrees read by Odoo service user |

---

## Deploy

| Item | Value |
|------|--------|
| Target ID | **4** |
| Name | PetSpot Test Staging Deploy |
| Kind | staging / `non_production=true` |
| Database | `pet_spot_elsahel_test` |
| Branch | `staging` |
| Runner | `/srv/devhub/runners/staging` |
| Allowlisted live DB | `pet_spot_elsahel_test` only |
| Verbs used | `preflight` → `deploy_code` → `healthcheck` → `smoke` (+ optional `upgrade_modules` opt-in) |
| Policy | PetSpot Test MVP (`production_access_policy=denied`; `deploy_permission` false except during deploy gate) |
| Proven deploy record | id **1**, merge SHA `0b516d5a…`, `succeeded` |

---

## Proven delivery trace (do not erase)

```text
WI 3324 → Analysis 2695 → Plan 2478 → Approval 2276
→ Session 950 → Workspace 1849 → Checkpoints 2142–2144
→ Commit 22c3cdc0… → GitHub App PR #16
→ Merge Approval 57 → Merge Record 35 → Merge SHA 0b516d5a…
→ Deploy 1 → Target 4 → succeeded
```
