# Evolution API — PetSpot WhatsApp Gateway

Runs [Evolution API](https://github.com/EvolutionAPI/evolution-api) locally for the Odoo **WhatsApp Chat** module (`evolution_whatsapp_chat`).

## Stack

```
WhatsApp phone  ↔  Evolution API (:8099)  ↔  Odoo (:8027)
                         │                        │
                         │  POST sendText         │  evolution_whatsapp_chat
                         │  webhooks inbound      │  integration_bridge_core
                         └────────────────────────┘
                              /bridge/evolution/webhook
```

## Odoo modules (already in this project)

| Module | Role |
|--------|------|
| `integration_bridge_core` | Webhooks, outbound queue, Evolution settings |
| `evolution_whatsapp_chat` | Send wizard, campaigns, delivery tracking |

Optional (only if you use Chatwoot legacy routes): `chatwoot_evolution_error_bridge`

## Quick start

```bash
cd projects/pet_spot_elsahel/evolution-api
cp .env.example .env
# Edit AUTHENTICATION_API_KEY in .env
docker compose up -d
# Or install as systemd service (auto-start on boot):
sudo ../../scripts/system/install_petspot_evolution_service.sh
```

**Manager UI (create instances + scan QR):** http://127.0.0.1:8099/manager

API key header for manager/API calls: value of `AUTHENTICATION_API_KEY` in `.env`

1. Open http://127.0.0.1:8099/manager (Evolution Manager UI, if available) or use Swagger.
2. Create instance **`petspot`** and scan QR with clinic WhatsApp.
3. In Odoo → **Integration Bridge → Configuration → Settings** set:
   - Evolution API URL: `http://127.0.0.1:8099`
   - Evolution API Key: same as `AUTHENTICATION_API_KEY` in `.env`
   - Evolution Instance: `petspot`
4. Send a test from **Contacts → WhatsApp** button.

## Webhook (auto-configured in `.env.example`)

Evolution posts to Odoo:

```
http://host.docker.internal:8027/bridge/evolution/webhook
```

Events: `MESSAGES_UPDATE`, `MESSAGES_UPSERT`, `CONNECTION_UPDATE`

## Commands

```bash
docker compose ps
docker compose logs -f evolution-api
docker compose down
curl -s http://127.0.0.1:8099/ | head
```

## Sync Odoo modules from resume repo

```bash
./scripts/sync_resume_whatsapp_modules.sh
# Then upgrade in Odoo Apps or:
# cd website && python3 -c "..."  # or Apps → Upgrade
```

Source: https://github.com/sabryyoussef/resume
