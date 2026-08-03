# Direct ATS Discovery Activation

**Verdict:** `ATS_DISCOVERY_LIVE_WAITING_FOR_SAFE_CANARY`

## Deployed
- Module: `19.0.2.13.0`
- n8n Hunter: `caweLvPrZEBjBfku` **active** (every 6h Africa/Cairo)
- n8n Submit orchestrator: `5X4dygwEwzNPalNc` **inactive**
- Odoo cron: Direct ATS Discovery (6h) **active**
- Kill switch: ON · live_submit: False · worker submit: False

## First discovery run
- Sources checked: 11
- New jobs: 0
- Safe canary: 0
- Ineligible: 22
- Account id=1 apps: 0

## Operating mode
Discovery continues automatically. No submission until a CAPTCHA-free Egypt/UAE/Remote (or sponsored) direct-ATS candidate passes all gates; then the prior one-shot canary authorization applies.

## UI
LinkedIn → Jobs → ATS Sources / Safe Canary Candidates / Application Policy KPIs
