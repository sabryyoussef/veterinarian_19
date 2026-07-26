# Phase 6 Human-Approved Merge — Controlled Live UAT Report

## Result

**PASS.** Fresh remote preflight matched the approved policy exactly. Dev Hub
executed one irreversible squash merge of PR #2 into `staging`. Remote merge
SHA equals the `staging` tip. Exactly one terminal merge record exists. Replay
is denied. No Dev Hub deployment actions occurred. Auto-merge remained null.

## Fresh preflight (before execution)

| Check | Observed |
| --- | --- |
| Repository | `sabryyoussef/veterinarian_19` only |
| App / installation | `4341059` / `147666583` |
| Permissions | checks:read, contents:write, metadata:read, pull_requests:read, statuses:read |
| PR #2 | open, draft=false, merged=false, mergeable=true, mergeable_state=clean |
| Head SHA | `24c7eef5e169016a94794f8e30b6934e2aabd3b8` |
| Base | `staging` @ `66344b2e09e2049c39942114029253e919bc6709` |
| Auto-merge | null |
| Required check | GitGuardian Security Checks (app `46505`) completed/success |
| Legacy statuses | empty list (allowed) |
| Dev Hub approval | id `1`, unconsumed, requester ≠ approver |
| Credential digest | approval == target |
| `_assert_merge_approval_current` | OK |

## Execution

- Path: `dev.git.merge.execution.wizard.action_merge` → `execute_approved_merge`
- Method: **squash** only
- Workspace: `14`
- Operator: Administrator `admin` (distinct from `devhub-merge-requester`)
- Result state: `merged`
- Workspace state: `merged_reviewed`
- Merge record: `1`
- Merge SHA: `2360b72691112263dceabc1fdd456f25073db623`
- Merged at (Dev Hub): `2026-07-19 21:43:33`
- Merged at (GitHub): `2026-07-19T21:43:30Z`

## Post-execution verification

1. PR #2: `state=closed`, `merged=true`, `auto_merge=null`
2. `merge_commit_sha` = `2360b72691112263dceabc1fdd456f25073db623`
3. `refs/heads/staging` = same SHA (staging tip == merge SHA)
4. Approved head SHA unchanged as PR head identity: `24c7eef5e169016a94794f8e30b6934e2aabd3b8`
5. Terminal merge records: **exactly 1** (`result_state=merged`)
6. Approval event: `consumed` — “Exact squash merge verified remotely.”
7. Replay denial: `AccessError: A current immutable Merge approval is required.`
8. Idempotency key record count: **1**
9. Deployment models (`dev.delivery.action`, `dev.deploy.action`, `dev.deployment`, `dev.service.operation`): **absent / zero**
10. Temporary installation token revoked after post-verify

## Credential handling

- Protected PEM: `/srv/devhub/credentials/github/merge-app-4341059.pem` (`600`)
- Broker / profile references only in Dev Hub
- No private-key contents in evidence

## Remaining notes

- Live UAT complete for this exact squash merge of PR #2.
- Further merges require a new review/approval cycle on a new exact head/base.
