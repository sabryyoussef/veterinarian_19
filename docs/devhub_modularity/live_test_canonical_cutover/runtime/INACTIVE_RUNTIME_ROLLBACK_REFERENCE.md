# INACTIVE_RUNTIME / ROLLBACK_REFERENCE

Status as of Live Test Canonical Cutover 2026-07-23:

- Live Test `pet_spot_elsahel_test :8028` no longer uses this overlay on `addons_path`.
- Runtime config is `pet_spot_elsahel_test.conf` (canonical projects/pet_spot_elsahel only).
- This directory is retained as rollback/reference archive. Do not delete.
- Staging conf retained: `config/projects/pet_spot_elsahel_test_activation_staging.conf`.
- Systemd staging drop-in disabled as: `activation-staging-0960fcc.conf.disabled_cutover_20260723`.
