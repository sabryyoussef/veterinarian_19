# Deployment — Test/Staging vs Production

## Separation

| | Test/Staging | Production |
|---|---|---|
| Target kind | `staging` | `production` |
| Environment types | `test`, `staging` | `production` only |
| Prerequisite | Workspace `merged_reviewed` + merge record SHA | Staging deploy evidence + soak |
| Approver group | Deploy approver | Production approver |
| Auto-promote | Forbidden | Forbidden |
| Runner allowlist | Non-prod hosts only | Prod hosts only (separate profiles) |

## Staging deploy binding

Every approval freezes: repository, environment, server, database, module
allowlist, merge SHA, requester, approver, plan/policy/contract hashes, and
idempotency key. Free-form branch, commit, path, host, database, or command
input is rejected.

## Rollback

Separate human approval. Code rollback and database/filestore rollback are
distinct verbs. Uncertain outcomes require reconciliation before retry.
Destructive rollback never auto-executes from a failed deploy.

## Production promotion

Requires:

1. Successful staging deploy terminal record for the exact SHA
2. Soak period satisfied
3. Explicit production approval and maintenance window confirmation
4. Fresh backup validation
5. Post-deploy health, business smoke, and rollback readiness

No direct deployment from a development branch.
