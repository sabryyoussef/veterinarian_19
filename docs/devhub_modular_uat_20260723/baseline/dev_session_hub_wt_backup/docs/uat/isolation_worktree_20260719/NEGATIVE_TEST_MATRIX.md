# Isolation UAT Negative-Test Matrix

| # | Negative case | Evidence | Result |
|---|---|---|---|
| 1 | No approved plan | `test_execution_workspace_requires_exact_current_approval` | PASS — denied |
| 2 | Superseded approval | Same test supersedes the approved plan and revalidates | PASS — denied |
| 3 | Production environment | `test_execution_workspace_denies_production_environment_and_target` | PASS — denied |
| 4 | Production-bearing target | Same test marks the target machine production-bearing | PASS — denied |
| 5 | Unsafe/path-escape root | `test_execution_repository_rejects_main_and_sensitive_roots` and bounded-path test | PASS — denied |
| 6 | Existing branch collision | `test_execution_workspace_branch_and_path_collisions_fail_closed` | PASS — review required, no overwrite |
| 7 | Existing worktree/path collision | Same collision test plus physical preflight collision observed during fixture recovery | PASS — denied, no overwrite |
| 8 | Concurrent writer | Playwright screenshot `17_concurrent_writer_rejected.png`; lease test | PASS — denied |
| 9 | Stale lease | `test_execution_workspace_concurrency_and_stale_lease_are_fenced` | PASS — fenced |
| 10 | Policy hash mismatch | Playwright screenshot `18a_policy_drift_rejected.png`; policy-hash test | PASS — denied |
| 11 | Execution-contract mismatch | Playwright screenshot `18_policy_contract_drift_rejected.png`; contract-hash test | PASS — denied |
| 12 | Missing worktree on Resume | `test_missing_or_dirty_workspace_fails_closed` | PASS — denied |
| 13 | Dirty cleanup | Playwright screenshot `22_cleanup_dirty_blocked.png`; dirty-workspace test | PASS — denied |
| 14 | Automatic commit | Git delta and allowlist test | PASS — none; command denied |
| 15 | Automatic push | Git evidence and allowlist test | PASS — none; command denied |
| 16 | Automatic merge | Git evidence and allowlist test | PASS — none; command denied |
| 17 | Deployment | Policy, event history, and no-side-effect evidence | PASS — none |

Automated evidence:

- Full module suite: 52 tests, 0 failures, 0 errors.
- Dedicated isolation/security suite: 11 tests, 0 failures, 0 errors.
- Playwright UAT: 1 scenario, passed.
