# Human-Approved Git Push Hardening UAT

This disposable non-production UAT uses two new workspaces:

- DW-8: clean registered URL, human-approved commit, and one exact normal Push.
- DW-9: human-approved commit and Push approval followed by a controlled
  transport failure test double. Real remote inspection must prove the branch
  absent and produce `push_failed_review`.

The UAT also verifies that credential-bearing HTTPS and SSH URL forms fail
before persistence, force variants fail before subprocess execution, no
credential appears in UI/audit evidence, and retry remains blocked until a
human reconciles the failed remote state.

PR creation, merge, deployment, Production access, force Push, tags, protected
branches, automatic retry, branch deletion, and worktree cleanup are excluded.
