# GitHub Credential Scaling

## Recommended model

Two shared GitHub Apps with **Selected repositories only**:

| Role | App | Permissions (do not broaden) |
|---|---|---|
| PR creation | `sabry-uat-agent` | contents:read, metadata:read, pull_requests:write |
| Merge | `sabry-uat-merge-agent` | checks:read, contents:write, metadata:read, pull_requests:read, statuses:read |

Scale by adding repositories to both installations’ selected-repo lists and
registering `dev.github.repository.allowlist` rows with installation repository
IDs. Dev Hub stores broker/profile path references only.

## Rejected models

- `All repositories` on either App
- Broad classic PATs
- One App combining PR write and merge contents:write
- Per-project Apps for every Sabry Odoo repo (ops explosion)

## Trust boundaries

Use separate Apps (or separate installations) when the GitHub organization is a
different client/legal trust boundary. Shared Apps are appropriate for
repositories under the same operator trust zone (e.g. `sabryyoussef/*`).

## Token minting

Brokers mint short-lived installation tokens only for the Workspace-bound
repository. Cross-repo mint requests fail closed. Tokens are revoked after use.

## SSH deploy keys

Remain push-transport only. They never replace the Merge App for squash merge
and never authorize deployment runners.

## Rotation

1. Install new PEM at a new protected path (`600`).
2. Point broker at new PEM; re-validate targets; refresh validation digests.
3. Supersede approvals that freeze the old digest.
4. Revoke old installation credentials; audit mint/revoke events.
