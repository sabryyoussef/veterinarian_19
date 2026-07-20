#!/usr/bin/env bash
# NOT RUN — pin ED25519 host key after human approval
set -euo pipefail
IP=100.110.211.53
EXPECTED='SHA256:Uq8IW8zlSdAPxWkd7MF+eJwuvjQmUSyvJQBw6oNrtyU'
TMP=$(mktemp)
ssh-keyscan -t ed25519 "$IP" 2>/dev/null > "$TMP"
FP=$(ssh-keygen -lf "$TMP" | awk '{print $2}')
test "$FP" = "$EXPECTED"
# Append only if absent
if ! ssh-keygen -F "$IP" >/dev/null 2>&1; then
  cat "$TMP" >> ~/.ssh/known_hosts
fi
ssh-keygen -F "$IP" -l
rm -f "$TMP"
