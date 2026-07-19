# Phase 5 Human-Approved Pull Request UAT

## Authorized flow

`pushed_reviewed` → human PR review → immutable approval → final human
confirmation → create one open PR → verify identity/state → stop.

The scenario never authorizes merge, auto-merge, deployment, Production access,
branch deletion, worktree cleanup, or Work Item closure.

## Required safe fixture

- New Test-only Work Item and isolated workspace.
- Reviewed commit pushed to a dedicated `devhub/*` branch.
- Registered GitHub repository and safe `staging` target branch.
- GitHub App or fine-grained credential profile limited to repository metadata,
  branch read, Pull Request read, and Pull Request write.
- No classic broad `repo`, administration, deployment, or branch-protection
  permission.

## UAT status

Passed with new Test-only Work Item DW-10 and workspace 14. The source branch
was created from the exact `staging` SHA, changed one sanitized documentation
marker, received separate human Commit and Push approvals, and reached
`pushed_reviewed`.

GitHub App `sabry-uat-agent` was installed only on
`sabryyoussef/veterinarian_19` with Contents read, Metadata read, and Pull
requests read/write. The UI scenario approved and created PR #2 to `staging`,
verified it open/unmerged with auto-merge disabled, and stopped at
`pr_created_reviewed`. A repeated operation was denied with one remote PR and
one audit record remaining.
