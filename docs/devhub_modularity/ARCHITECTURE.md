# Dev Hub Architecture

**Status:** Authoritative for Live Test operational control plane (2026-07-23)  
**Runtime:** `pet_spot_elsahel_test` :8028 — canonical addons only  
**Production:** Dev Hub modular stack **not installed**

---

## Layer map

```text
INTAKE
  Manual Dev Hub work item
  OpenProject-linked work          (optional: devhub_openproject)
  WhatsApp Hub → Dev Hub intake    (optional: whatsapp_hub → devhub_whatsapp)
  Future API intake                (deferred)

CORE
  devhub_core
    → devhub_work                  (independent of OpenProject)

CAPABILITIES
  Analysis          devhub_analysis
  Plan              devhub_plan
  Approval          devhub_approval
  Session           devhub_session
  Execution         devhub_execution
  Generation        devhub_generation   (optional drafts)

PROVIDERS
  Git               devhub_git
  GitHub            devhub_github       (GitHub App broker canonical)
  Deploy            devhub_deploy       (Test/Staging only today)
  Odoo Runtime      devhub_odoo_runtime
  Infrastructure    devhub_infrastructure
  Code Analysis     devhub_code_analysis

INTEGRATIONS (consumers — not owners of Work)
  OpenProject       devhub_openproject  (depends openproject_sync)
  WhatsApp Hub      devhub_whatsapp     (depends whatsapp_hub)

ORCHESTRATION
  devhub_workflow                   (board only — no business ownership)

META / COMPATIBILITY
  dev_session_hub                   (meta depends; menus/compat; 19.0.9.1.0)
```

### Optional dependencies

| Dependency | Required for core delivery? |
|------------|-----------------------------|
| OpenProject | No — `devhub_work` stands alone |
| WhatsApp Hub | No — intake consumer only |
| Generation | No — Analysis/Plan can be manual |
| Code analysis / Odoo runtime / Infrastructure | Capability providers; not required for every WI |
| Deploy | Required only when promoting a merged SHA to Test |

---

## Delivery flow

```text
Work
 → Analysis          (optional if Manual Plan path)
 → Plan
 → Exact-hash Approval
 → Session / Execution workspace
 → Git commit + push
 → GitHub App PR
 → Merge Approval (requester ≠ approver)
 → Governed Merge → merge record → merged_reviewed
 → Test Deploy (target 4)
 → Completion
```

Orchestration surface: **Workflow Board** (`dev.workflow.board`) discovers installed capabilities and KPIs. It does **not** own Analysis/Plan/Approval/Execution records.

---

## Ownership rules (non-negotiable)

1. `devhub_work` owns `dev.work.item` independently of OpenProject.
2. `devhub_whatsapp` is a **WhatsApp Hub consumer** only (`whatsapp_hub → devhub_whatsapp → dev.work.item`).
3. `devhub_workflow` is **orchestration only**.
4. Physical Git/PR/merge require the worker identity and registered roots.
5. Production deploy remains separately gated and **disabled** on this control plane.

---

## Security groups (Live Test)

| Group | Role |
|-------|------|
| Dev Hub User | Day-to-day read / limited write |
| Dev Hub Manager | Operational control |
| Plan and Communication Approver | Plan exact-hash approval |
| Deploy Approver | Non-production deploy approval |
| Production Approver | Future Production only (unused) |
| Scoped service groups | Outbox / Generation / WhatsApp intake services |

---

## Related docs

- Baseline pin: `OPERATIONAL_BASELINE.md`
- Runbook: `OPERATIONAL_RUNBOOK.md`
- Stabilization report: `DEV_HUB_OPERATIONAL_ROLLOUT_AND_STABILIZATION_REPORT.md`
- Proven UAT: `GITHUB_APP_GOVERNED_MERGE_TEST_DEPLOY_REPORT.md`
