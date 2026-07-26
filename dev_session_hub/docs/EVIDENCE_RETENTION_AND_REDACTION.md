# Evidence Retention and Secret Redaction

## Directory convention

```
dev_session_hub/docs/uat/<phase>_<capability>_<YYYYMMDD>/
```

Required artifacts per gate UAT:

- `UAT_SCENARIO.md` — exact policy under test
- `UAT_REPORT.md` — pass/fail with binding hashes (no secrets)
- Sanitized remote/git verification text
- Playwright stop-gate screenshots (approval UI only)
- Automated test result logs

## Retention

- Keep UAT packs indefinitely for irreversible gates (PR, merge, deploy, rollback, production).
- Retain terminal Odoo audit rows (`*.record`, `*.approval`, `*.event`) without unlink.
- Rotate ephemeral runner logs after 90 days once copied into sanitized evidence.

## Redaction policy

Never store in git, Odoo chatter, evidence, or screenshots:

- PEM private keys or key material
- Installation tokens, classic PATs, fine-grained PAT secrets
- Database passwords, SSH private keys
- Full `.env` contents

Allowed:

- Absolute path references under `/srv/devhub/credentials/` and `/srv/devhub/runners/`
- App IDs, installation IDs, repository names, SHAs, PR numbers
- Permission summaries as `scope:access` lines

## Roles

| Role | Group | Irreversible gates |
|---|---|---|
| User | `group_dev_hub_user` | None |
| Approver | `group_dev_hub_approver` | Plan/communication |
| Deploy approver | `group_dev_hub_deploy_approver` | Staging deploy / rollback request review |
| Production approver | `group_dev_hub_production_approver` | Production promotion |
| Manager | `group_dev_hub_manager` | Registry + all supervisory access |

Requester and approver must be distinct users for merge, deploy, rollback, and production gates.
