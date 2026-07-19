# Phase 5 Human-Approved Git Push UAT Report

Date: 2026-07-19

## Result

Human-Approved Git Push is safely validated for one normal non-force Push of
one reviewed Dev Hub branch to one registered, worker-owned, non-production
bare Git remote. Execution stopped at `pushed_reviewed`.

## Required final report

1. **Work Item:** DW-7, “Add human-approved Push contract test”.
2. **Workspace:** ID 11; final state `pushed_reviewed`.
3. **Local branch:** `devhub/DW-7-add-human-approved-push-contract-test`.
4. **Local commit SHA:** `876b55ba6f1f934b079bedc1829aa1683d6230b1`;
   parent `5a7f1e1404dbbc1efeacc1a1bcaea3021d7cd7ae`.
5. **Approved remote:** registered remote `devhub-uat`, resolving only from
   repository configuration to
   `/srv/devhub-uat/remotes/petspot-human-push-uat.git`.
6. **Remote target branch:** the exact same dedicated Dev Hub branch,
   `devhub/DW-7-add-human-approved-push-contract-test`.
7. **Push approval record:** ID 1; immutable binding hash
   `ccb6694aeedd82bef1daf9f582bbc37c8c405cd6e21fbab14f7044ec905d6fdc`;
   mode `normal`; approved at `2026-07-19 14:07:03 UTC`.
8. **Approver:** Administrator (`admin`). Git author remains
   `Dev Worker <devworker@devhub.invalid>`.
9. **Pre-Push remote HEAD:** absent; the approved remote had no refs.
10. **Post-Push remote HEAD:** `876b55ba6f1f934b079bedc1829aa1683d6230b1`.
11. **Fast-forward validation:** passed. Creation of an absent remote branch
    was allowed; non-fast-forward and changed-remote controls fail closed.
12. **Push result:** success at `2026-07-19 14:07:12 UTC`; Push record ID 1,
    audit hash
    `994fb343cf35de828e60b03baf18d3435e882dd5d4495476b3756f7d0d9a63f4`.
13. **Main-worktree verification:** branch `main`, HEAD
    `5a7f1e1404dbbc1efeacc1a1bcaea3021d7cd7ae`, clean and unchanged.
14. **Remote branch verification:** exactly one ref exists, the approved
    branch at the approved commit. Other heads and all tags remained unchanged.
15. **Playwright result:** 1/1 passed in 1.2 minutes; seven required
    screenshots captured.
16. **Automated test result:** full module 85/85 passed; worker Test contract
    targeted 2/2 and regression 2/2 passed; security/regression 20/20 passed.
17. **Negative tests:** denial coverage passed for missing approval, wrong
    state, HEAD/commit/branch/policy/contract drift, remote drift,
    unapproved/unregistered/arbitrary remote, target drift, protected
    `main`/`master`/Production/release targets, dirty worktree, active lease
    and concurrent writer, Production environment, remote advance,
    non-fast-forward state, force Push, Push-all, and tag Push.
18. **PR creation:** none. The local bare UAT remote has no PR capability and
    no PR command/API action exists in this flow.
19. **Merge:** none. No merge command or merge lifecycle transition occurred.
20. **Deployment:** none. No deployment, Production access, service control,
    Docker control, cleanup, branch deletion, or tag mutation occurred.
21. **Remaining blockers:** none for this bounded capability. It does not
    authorize automatic Push, PR creation, merge, deployment, or Production.

## Evidence

- `UAT_SCENARIO.md`
- `push_metadata.txt`
- `sanitized_git_remote_before_after.txt`
- `playwright_tests.txt`
- `test_results.txt`
- `screenshots/01_committed_reviewed.png` through
  `screenshots/07_pushed_reviewed_final.png`
- `tests/playwright/phase5_human_push.spec.ts`

## Decision

Is Human-Approved Git Push safely validated: YES

Recommended next capability: `Human-approved PR creation`
