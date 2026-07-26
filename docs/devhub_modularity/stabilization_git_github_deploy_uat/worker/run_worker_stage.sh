#!/usr/bin/env bash
# Launch odoo-bin shell as OS user `devworker` (uid 1100) for physical Git stages.
set -euo pipefail
STAGE="${1:?stage required}"
WORKSPACE_ID="${2:?workspace id required}"
MARKER="${3:-}"
COMMIT_MESSAGE="${4:-}"

ROOT=/home/sabry/odoo_base/base_odoo_19
CONF="$ROOT/config/projects/pet_spot_elsahel_test.conf"
DB=pet_spot_elsahel_test
SCRIPT=/srv/devhub/uat/stabilization/worker_stages.py
OUTDIR=/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/docs/devhub_modularity/stabilization_git_github_deploy_uat/logs
mkdir -p "$OUTDIR"
LOG="$OUTDIR/worker_${STAGE}.log"

INNER=$(cat <<EOF
cd '$ROOT'
export HOME=/srv/devhub/home/devworker
export STAB_STAGE='$STAGE'
export STAB_WORKSPACE_ID='$WORKSPACE_ID'
export STAB_MARKER='$MARKER'
export STAB_COMMIT_MESSAGE='$COMMIT_MESSAGE'
export STAB_STATE_FILE=/srv/devhub/uat/stabilization/state.json
export PATH=/usr/bin:/bin:$ROOT/venv19/bin
'$ROOT/venv19/bin/python3' '$ROOT/odoo19/odoo19/odoo-bin' shell \
  -c '$CONF' -d '$DB' --no-http --log-level=error < '$SCRIPT'
EOF
)

echo "[launcher] stage=$STAGE workspace=$WORKSPACE_ID" | tee -a "$LOG"
set +e
docker run --rm --privileged --network host --pid=host -v /:/host alpine \
  chroot /host /usr/bin/setpriv --reuid=1100 --regid=1000 --init-groups -- \
  /bin/bash -lc "$INNER" 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
set -e
exit "$RC"
