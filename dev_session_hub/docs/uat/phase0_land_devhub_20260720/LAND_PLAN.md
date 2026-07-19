# DH-P0 — Land Dev Hub Implementation

Date: 2026-07-20

## Objective

Land the validated human-approved PR/Merge Dev Hub implementation (plus
completion roadmap capabilities P1–P6) onto `staging` for
`sabryyoussef/veterinarian_19` without contaminating unrelated dirty-tree
files and without destructive git operations.

## Allowlist (only these paths enter the land commit)

- `dev_session_hub/**`

## Explicitly excluded (preserve on disk / index)

All other staged and unstaged paths in the PetSpot worktree remain untouched,
including but not limited to:

- `chatwoot_evolution_error_bridge/**`
- `developer_hub/**`
- `evolution_whatsapp_chat/**`
- `docs/ops-audits/**`
- `.petspot-backend-proxy/**`
- Unrelated `.gitignore` and `evolution-api` edits

## Secret review

- No `.pem`, `.env`, credential dumps, or database backups under allowlist.
- Matches for `PRIVATE KEY` markers are denial-pattern strings in code/tests only.
- Brokers and UAT evidence reference path-only credential locations under
  `/srv/devhub/credentials/github/` — never embed PEM or token contents.

## Recursion mitigation

- Land uses a dedicated branch cut from `staging`.
- Frozen allowlist: only `dev_session_hub/**`.
- Do not approve concurrent Dev Hub self-mutation work items while the land
  PR is open.
- First land is human-supervised; subsequent changes use normal gates.

## Git safety

- No `git reset --hard`, `git clean`, force-push, or history rewrite.
- Unrelated index/worktree state is preserved via a separate worktree for the
  land commit.
- Rollback after merge: new revert PR only (no force).

## Definition of done

1. Allowlisted commit exists on a `devhub/DH-P0-land-*` branch.
2. PR opened against `staging`.
3. Squash merge completed under human-approved controls (or PR awaiting merge
   approval with evidence pack complete).
4. Pre-land porcelain snapshot proves unrelated files were not part of the PR.
5. Module tests recorded in this evidence directory.
