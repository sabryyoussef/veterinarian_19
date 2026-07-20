#!/usr/bin/env bash
# NOT RUN — requires: (1) known_hosts pin, (2) free-space verify, (3) human transfer approval
set -euo pipefail
ALIAS=sabry3-precision-5540-ts
SRC=/home/sabry/odoo_base/base_odoo_19/backups/dell_handoff_pet_spot_elsahel_test_20260720T053201Z
DEST=/home/sabry3/devhub/handoff/pet_spot_elsahel_test_20260720T053201Z
EXPECTED_FP='SHA256:Uq8IW8zlSdAPxWkd7MF+eJwuvjQmUSyvJQBw6oNrtyU'
# Fail closed unless pinned fingerprint matches
FP=$(ssh-keygen -F 100.110.211.53 -l | awk '{print $2}' | head -1)
test "$FP" = "$EXPECTED_FP"
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$ALIAS" \
  "mkdir -p $DEST && df -BG /home/sabry3 | awk 'NR==2{print}' && test -d /home/sabry3/devhub/veterinarian_19"
# Require >= 1GB free (handoff ~73MB)
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$ALIAS" \
  'python3 - <<"PY"
import shutil
free=shutil.disk_usage("/home/sabry3").free
assert free >= 1_000_000_000, free
print("free_bytes", free)
PY'
rsync -a --info=progress2 "$SRC/" "$ALIAS:$DEST/"
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$ALIAS" "cd $DEST/artifacts && sha256sum -c SHA256SUMS.txt"
echo TRANSFER_OK
