#!/usr/bin/env bash
# Sync WhatsApp-related Odoo modules from github.com/sabryyoussef/resume
set -euo pipefail

REPO="${RESUME_REPO:-https://github.com/sabryyoussef/resume.git}"
DEST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

clone_sparse() {
  local module="$1"
  git clone --depth 1 --filter=blob:none --sparse "$REPO" "$TMP/repo"
  cd "$TMP/repo"
  git sparse-checkout set "$module"
  rsync -a --delete --no-owner --no-group --exclude '__pycache__' --exclude '*.pyc' \
    "$TMP/repo/$module/" "$DEST/$module/"
  rm -rf "$TMP/repo"
  echo "Synced $module → $DEST/$module"
}

for mod in integration_bridge_core evolution_whatsapp_chat; do
  clone_sparse "$mod"
done

echo "Done. Restart Odoo and upgrade modules if manifests changed:"
echo "  sudo systemctl restart pet_spot_elsahel"
echo "  Apps → Upgrade integration_bridge_core, evolution_whatsapp_chat"
