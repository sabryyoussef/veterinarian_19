# Evidence allowlist — phase17 Dell Start & Launch MVP

## Included in this Git pack

- `UAT_REPORT.md` — final verdict and checklist
- `sanitized_human_terminal_verification.txt` — Remote-SSH terminal checks
- `sanitized_safety_invariants.txt` — safety / non-action confirmations
- `ALLOWLIST.md` — this file

## Related pathway evidence (separate dirs in same PR)

- `../phase13_dell_handoff_prep_20260720/`
- `../phase14_dell_transfer_restore_20260720/`
- `../phase15_blocker_remediation_20260720/`
- `../phase16_dell_repin_b6e8a5d_20260720/`

## Explicitly excluded from Git

- Database dumps / filestore archives
- Credentials, `.env`, Odoo conf passwords
- Private/public key material (beyond approved fingerprint references)
- `known_hosts` / SSH config backups
- Runtime service units, overlays, caches
- Raw unsanitized subprocess logs with environment secrets
- Master Class-C / unrelated dirty paths
- Dell legacy 914-path checkout
- Session 890 database mutation artifacts (runtime only)
