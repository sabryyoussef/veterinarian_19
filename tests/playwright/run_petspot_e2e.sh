#!/usr/bin/env bash
# Start PetSpot services (if needed) and run Playwright clinic workflow tests.
set -euo pipefail

ROOT="/home/sabry/odoo_base/base_odoo_19"
PET="$ROOT/projects/pet_spot_elsahel"
PW="$PET/tests/playwright"
BRIDGE="/home/sabry/infra/chatwoot-evolution-bridge"
CONF="$ROOT/config/projects/pet_spot_elsahel.conf"
LOG="$PET/odoo.log"

# Prefer explicit PETSPOT_* vars; default to local clinic stack (ignore SaaS ODOO_URL).
export ODOO_URL="${PETSPOT_ODOO_URL:-http://127.0.0.1:8027}"
export ODOO_DB="${PETSPOT_ODOO_DB:-pet_spot_elsahel}"
export ODOO_LOGIN="${PETSPOT_ODOO_LOGIN:-admin}"
export ODOO_PASSWORD="${PETSPOT_ODOO_PASSWORD:-admin}"
export BRIDGE_URL="${PETSPOT_BRIDGE_URL:-http://127.0.0.1:3010}"
export CHATWOOT_URL="${PETSPOT_CHATWOOT_URL:-http://127.0.0.1:3000}"

if [[ -f "$BRIDGE/.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  # Load only keys we need (avoid breaking on odd values)
  BRIDGE_SHARED_SECRET="$(grep -E '^BRIDGE_SHARED_SECRET=' "$BRIDGE/.env" | cut -d= -f2- || true)"
  PETSPOT_BRIDGE_TOKEN="$(grep -E '^PETSPOT_BRIDGE_TOKEN=' "$BRIDGE/.env" | cut -d= -f2- || true)"
  INTEGRATION_BRIDGE_MASTER_TOKEN="$(grep -E '^INTEGRATION_BRIDGE_MASTER_TOKEN=' "$BRIDGE/.env" | cut -d= -f2- || true)"
  CHATWOOT_API_TOKEN="$(grep -E '^CHATWOOT_API_TOKEN=' "$BRIDGE/.env" | cut -d= -f2- || true)"
  export BRIDGE_SHARED_SECRET PETSPOT_BRIDGE_TOKEN INTEGRATION_BRIDGE_MASTER_TOKEN CHATWOOT_API_TOKEN
  set +a
fi
export PETSPOT_BRIDGE_TOKEN="${PETSPOT_BRIDGE_TOKEN:-${INTEGRATION_BRIDGE_MASTER_TOKEN:-ib_cw_fzm_7xK9mN2pQ4rT6vY8zA1bD3eF5g}}"

echo "== PetSpot E2E =="
echo "ODOO_URL=$ODOO_URL DB=$ODOO_DB BRIDGE_URL=$BRIDGE_URL"

# Start Odoo if down
if ! curl -sf "$ODOO_URL/petspot/portal/health" >/dev/null 2>&1; then
  echo "Starting Odoo..."
  pkill -f "odoo-bin -c $CONF" 2>/dev/null || true
  sleep 1
  nohup "$ROOT/venv19/bin/python3" "$ROOT/odoo19/odoo19/odoo-bin" \
    -c "$CONF" -d "$ODOO_DB" >>"$LOG" 2>&1 &
  for i in $(seq 1 30); do
    if curl -sf "$ODOO_URL/petspot/portal/health" >/dev/null 2>&1; then
      echo "Odoo up"
      break
    fi
    sleep 2
  done
fi

# Start bridge if down
if ! curl -sf "$BRIDGE_URL/health" >/dev/null 2>&1; then
  echo "Starting bridge..."
  (cd "$BRIDGE" && docker compose up -d bridge) || true
  for i in $(seq 1 20); do
    if curl -sf "$BRIDGE_URL/health" >/dev/null 2>&1; then
      echo "Bridge up"
      break
    fi
    sleep 2
  done
fi

cd "$PW"
if [[ ! -d node_modules ]]; then
  npm install
fi

# Ubuntu 26 may not have Playwright browser builds — use Chrome for Testing locally.
CHROME_BIN="$(find "$PW/browsers/chrome" -type f -path '*/chrome-linux64/chrome' 2>/dev/null | head -1 || true)"
if [[ -z "$CHROME_BIN" ]]; then
  echo "Installing Chrome for Testing (user-space)..."
  npm install @puppeteer/browsers --no-save
  npx @puppeteer/browsers install chrome@stable --path ./browsers
  CHROME_BIN="$(find "$PW/browsers/chrome" -type f -path '*/chrome-linux64/chrome' 2>/dev/null | head -1 || true)"
fi
export PLAYWRIGHT_CHROME_PATH="$CHROME_BIN"
echo "Chrome: $PLAYWRIGHT_CHROME_PATH"

npm run test:petspot
npm run copy:petspot || true

echo ""
echo "Screenshots: $PW/screenshots/petspot_clinic/"
echo "Report:      $PW/screenshots/petspot_clinic/RESULTS.md"
ls -la "$PW/screenshots/petspot_clinic/" | head -40
