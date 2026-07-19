# Phase 6 Human-Approved Merge Stop-Gate

## Boundary

- Repository: `sabryyoussef/veterinarian_19`
- Pull Request: `#2`
- Required base: `staging`
- Required method: `squash`
- Credential: separate `sabry-uat-merge-agent`, installed on this repository only
- Requester: dedicated non-Administrator Dev Hub service user
- Approver: distinct Dev Hub Administrator
- Live remote merge: forbidden during this readiness run
- Auto-merge, deployment, Odoo upgrade, service restart, branch deletion: forbidden

## Stop-Gate flow

1. Start from the existing verified `pr_created_reviewed` workspace and open PR #2.
2. Validate repository, PR URL/number, open/unmerged/non-draft state, exact source branch and current remote head SHA.
3. Validate base is exactly `staging`, capture its current SHA, and reject any later drift.
4. Verify repository rules, mergeability, GitGuardian required check identity and success, and commit statuses.
5. Verify the separate Merge App identity, exact repository installation, and exact permissions.
6. Record the dedicated requester and require approval by a different Administrator.
7. Bind the immutable approval to all reviewed values and `squash`.
8. Open the separate irreversible execution confirmation without checking it.
9. Cancel the execution wizard.
10. Verify workspace remains `merge_approved`, no terminal Merge record exists, PR #2 remains open, and no remote merge/deployment occurred.

## Live authorization after readiness

A later live UAT requires a fresh Administrator confirmation issued after a new remote preflight. The execution confirmation is not reusable if the PR head, staging base, checks, rules, credential attestation, policy, Plan, or contract changes.
