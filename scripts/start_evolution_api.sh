#!/usr/bin/env bash
# Start Evolution API docker stack for PetSpot WhatsApp
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../evolution-api" && pwd)"
cd "$DIR"

if [[ ! -f .env ]]; then
  cp .env.example .env
  KEY="$(openssl rand -hex 16 2>/dev/null || echo 'petspot-change-me-key')"
  sed -i "s/CHANGE_ME_PETSPOT_EVOLUTION_KEY/${KEY}/" .env
  echo "Created .env with generated AUTHENTICATION_API_KEY"
  echo "Save this key for Odoo Integration Bridge settings:"
  grep AUTHENTICATION_API_KEY .env
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker not installed. Install docker.io then re-run."
  exit 1
fi

docker compose up -d
echo "Waiting for Evolution API..."
for i in $(seq 1 30); do
  if curl -sf -o /dev/null "http://127.0.0.1:8099/" 2>/dev/null; then
    echo "Evolution API is up at http://127.0.0.1:8099"
    docker compose ps
    exit 0
  fi
  sleep 2
done
echo "Evolution API starting (check: docker compose logs -f evolution-api)"
docker compose ps
