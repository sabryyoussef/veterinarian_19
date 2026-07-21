#!/usr/bin/env bash
# Wire the idempotent Dev Hub Test-posture provisioner into the Test
# activation/redeploy flow. Run this AFTER `odoo-bin -u dev_session_hub` on the
# Test database, before the first Merge & Improve request.
#
# It is deliberately hard-scoped: the Python step refuses to write anything
# unless the connected database is the pet_spot_elsahel_test Test target.
#
#   Usage:
#     dev_session_hub/deploy/provision_test_posture.sh
#     DEVHUB_PROVISION_APPLY=0 dev_session_hub/deploy/provision_test_posture.sh   # dry run
#
#   Overridable env vars (defaults target the Test box):
#     DEVHUB_REPO_ROOT   repo root that holds odoo19/ and venv19/
#     DEVHUB_TEST_CONFIG odoo config for the Test service
#     DEVHUB_TEST_DB     Test database name
set -euo pipefail

REPO_ROOT="${DEVHUB_REPO_ROOT:-/home/sabry/odoo_base/base_odoo_19}"
PY="${DEVHUB_PY:-$REPO_ROOT/venv19/bin/python3}"
ODOO_BIN="${DEVHUB_ODOO_BIN:-$REPO_ROOT/odoo19/odoo19/odoo-bin}"
CONFIG="${DEVHUB_TEST_CONFIG:-$REPO_ROOT/config/projects/pet_spot_elsahel_test_activation_staging.conf}"
DB="${DEVHUB_TEST_DB:-pet_spot_elsahel_test}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$DB" != "pet_spot_elsahel_test" ]; then
  echo "refusing: DEVHUB_TEST_DB=$DB is not the Test database" >&2
  exit 2
fi

exec "$PY" "$ODOO_BIN" shell -c "$CONFIG" -d "$DB" --no-http \
  < "$SCRIPT_DIR/provision_test_posture.py"
