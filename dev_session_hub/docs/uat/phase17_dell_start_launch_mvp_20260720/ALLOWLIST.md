# Evidence allowlist — trimmed Dell MVP pack

## Retained in Git (audit-sufficient)

### Phase 17 (final)
- `UAT_REPORT.md`
- `sanitized_human_terminal_verification.txt`
- `sanitized_safety_invariants.txt`
- `ALLOWLIST.md`
- `ROADMAP_DECISIONS.md`
- `HUMAN_REVIEW_PREP.md`

### Phase 13
- `HANDOFF_REPORT.md`, `M2_PORTABILITY_CLASSIFICATION.md`, `M5_DELL_POST_RESTORE_PLAN.md`
- `final_invariants.txt`, `m3_artifact_listing.txt`, `m4_keyscan_fingerprints.txt`

### Phase 14
- `GATE12_FINAL_REPORT.md`, `T1_SSH_PIN_SUMMARY.txt`, `t1_live_fingerprint.txt`
- `t2_pretransfer_hashes.txt`, `final_master_evidence.txt` (fingerprint-only)

### Phase 15
- `BLOCKER_REMEDIATION_REPORT.md`, `a_openproject_pin.txt`, `TEST_TOTALS_SUMMARY.txt`

### Phase 16
- `PHASE16_REPORT.md`, `module_versions.txt`, `overlay_retirement.txt`
- `path_consistency.txt`, `r7_smoke.txt`

## Explicitly excluded from Git

- Raw command transcripts and multi-run test logs
- `known_hosts` / SSH config backups or proposed full configs
- Public/private key material (beyond approved fingerprint references)
- Database dumps, filestore archives, `.env`, Odoo conf passwords
- Runtime service units, overlays, caches, browser download metadata
- Master Class-C / unrelated dirty paths; Dell legacy 914-path checkout
