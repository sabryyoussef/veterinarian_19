# D13 — `devhub_modular_fresh` Migration Evidence

**Date (UTC):** 2026-07-23  
**DB:** `devhub_modular_fresh` (:8032 acceptance baseline)  
**Result:** PASS after retry (code_analysis view inherit fix)

## Actions

1. Installed new modules: `devhub_analysis`, `devhub_plan`, `devhub_approval`, `devhub_workflow`
2. Upgraded: `devhub_work`, `devhub_openproject`, `devhub_execution`, `devhub_generation`, `devhub_code_analysis`, `devhub_session`, `dev_session_hub`, `devhub_workflow`
3. Preserved existing work/analysis/plan rows (counts unchanged after upgrade)

## After state (selected)

See `after_state.txt` — all `devhub_*` at 19.0.9.1.0 where versioned for this wave; meta `dev_session_hub` **19.0.9.1.0**.

## Smoke

See `smoke_after.txt`:

- Models: analysis / plan / approval / checkpoint / workflow board present
- Existing data: `wi_count=1`, `analysis_count=1`, `plan_count=1`
- OP fields still available via `devhub_openproject` inherit

## Notes

- First upgrade attempt failed on stale code_analysis view inherit of work form; fixed by inheriting `devhub_analysis.view_dev_work_item_form_analysis`.
- Live Production DB untouched.
