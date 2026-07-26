# Human-Approved Git Push Hardening Report

Date: 2026-07-19

1. **Remote URL root cause:** validation relied on selected substrings and only
   checked parsed passwords. Other userinfo, arbitrary query parameters, and
   fragments could reach `dev.git.remote` and immutable approval references.
2. **URL validation implementation:** HTTPS and SSH URLs now use structured
   parsing; SCP-style SSH uses a strict normalized grammar. Existing records
   are revalidated before every Push review/approval and fail closed without
   silently stripping data.
3. **Allowed formats:** credential-free
   `https://github.com/org/repo.git`,
   `ssh://git@github.com/org/repo.git`, and policy-approved
   `git@github.com:org/repo.git`; registered file remotes remain constrained
   to the approved real-path root.
4. **Denied formats:** all HTTPS userinfo/username/password, all query strings
   and fragments, SSH query/fragment/password, unapproved SSH users, malformed
   URLs, protocol mismatch, and credential-bearing legacy records.
5. **Force guard:** a Push command is accepted only in canonical internal form:
   `push --porcelain <registered-name>
   refs/heads/<source>:refs/heads/<target>`. Generic Push arguments are not
   accepted.
6. **Force variants tested:** `-f`, `--force`, `--force=true`,
   `--force=false`, `--force-with-lease`,
   `--force-with-lease=<value>`, `--force-if-includes`, `--all`, `--tags`,
   `+refs/...`, `+branch`, and mixed safe/force arguments. Each was rejected
   before `subprocess.run`.
7. **Failed Push state model:** audit records now distinguish `pushed`,
   `reconciled_success`, `push_failed_review`, and
   `uncertain_remote_state`. Workspaces stop at explicit failed/uncertain
   states until human reconciliation.
8. **Reconciliation logic:** every attempt independently snapshots remote
   heads/tags. A failed subprocess with the exact expected refs becomes
   `reconciled_success`; an observed absent/mismatched commit becomes
   `push_failed_review`; an unavailable snapshot becomes
   `uncertain_remote_state`. No automatic retry occurs.
9. **UAT:** DW-8/workspace 12 pushed commit
   `965a51ea0752f58191adccf103a45a33bc38c972` to only its dedicated branch.
   DW-9/workspace 13 used one controlled transport failure; expected commit
   `9e09c7656b349c2813a703b8d2af5baa9a5a4ef1` remained absent remotely,
   produced Push record 3 with `push_failed_review`, and required human
   reconciliation before returning to `committed_reviewed`. No retry occurred.
10. **Security tests:** 20/20 passed.
11. **Module tests:** 88/88 passed, including URL persistence, force, success,
    mismatch, unknown state, evidence, and retry controls.
12. **Playwright:** 1/1 passed in 48.5 seconds; seven success/failure/review
    screenshots captured. No credential-bearing URL appeared in UI evidence.
13. **Files changed:** manifest, Push/execution models, Push/execution views,
    lifecycle regression tests, hardening Playwright test, and hardening UAT
    evidence/scripts.
14. **Candidate commit files:**
    - `dev_session_hub/__manifest__.py`
    - `dev_session_hub/models/dev_execution.py`
    - `dev_session_hub/models/dev_git_push.py`
    - `dev_session_hub/views/dev_execution_views.xml`
    - `dev_session_hub/views/dev_git_push_views.xml`
    - `dev_session_hub/tests/test_dev_work_lifecycle.py`
    - `dev_session_hub/docs/uat/phase5_human_push_hardening_20260719/`
    - `tests/playwright/phase5_human_push_hardening.spec.ts`
15. **Repository hygiene:** no `git add`, commit, reset, checkout, or index
    mutation was performed. Unrelated staged files outside this candidate list
    remain untouched.
16. **Remaining blockers:** none for broader controlled use within the same
    human approval, non-production, dedicated-branch, normal-Push boundary.
    PR creation, merge, deployment, Production, and automatic Push remain
    unavailable.

No PR was created, no merge occurred, no deployment occurred, and no
Production system was accessed.

Recommended next capability: `Human-approved PR creation`

Is Human-Approved Git Push hardened and safe for broader controlled use: YES
