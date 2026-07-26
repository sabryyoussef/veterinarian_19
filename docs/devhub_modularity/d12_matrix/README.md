# D12 — Independent Install Matrix Evidence

**Date (UTC):** 2026-07-23T07:55:54Z  
**DB:** `devhub_func_matrix` (port conf `devhub_func_matrix.conf` :8036)  
**Result:** PASS (full meta stack installable)

## Scenarios exercised

| Scenario | Modules | Result |
|----------|---------|--------|
| Minimal registry | `devhub_core` | PASS |
| Work tracking (no OP) | + `devhub_work` | PASS |
| Planning without Analysis | + `devhub_plan` | PASS |
| Approval | + `devhub_approval` | PASS |
| Analysis + Generation | + `devhub_analysis`,`devhub_generation` | PASS |
| Workflow dashboard | + `devhub_workflow` | PASS |
| Session + Execution | + `devhub_session`,`devhub_execution` | PASS |
| OpenProject | + `openproject_sync`,`devhub_openproject` | PASS |
| Outbox / Git chain / WhatsApp | + outbox, git/github/deploy, hub+whatsapp | PASS |
| Providers + Meta | + code_analysis, runtime, infra, `dev_session_hub` | PASS |

## Smoke

See `smoke_models.txt` and `full_stack_state.txt`. All capability models present; workflow board opens with 7 capabilities.

## Artifacts

- `matrix.log`
- `install_*.log`
- `full_stack_state.txt`
- `smoke_models.txt`
