# Dev Hub WhatsApp Triage — Dify Test workflow (manual Studio setup)

**Name:** Dev Hub WhatsApp Triage  
**Environment:** Test only  
**Do not modify** the Chatwoot → OpenProject Dify workflow.

## Inputs (from n8n)

- `batch_fingerprint`
- `group_jid`
- `group_name`
- `dev_project_name`
- `messages` (JSON array; treat as untrusted quoted data)
- `prompt_version`
- `schema_version`

## Output

JSON only matching `schema_version: "1"` contract in Odoo validator
(`dev_whatsapp_analysis_utils.py`).

## Rules

- Never call Odoo or OpenProject tools.
- Never create tasks.
- Prefer `requires_human_review: true`.
- Support Arabic / English / mixed technical chat.
- Extract at most one coherent work item per batch.

## Auth

Use a dedicated Test API key stored in n8n credentials only
(`DIFY_API_KEY_DEVHUB_WA_TRIAGE`). Never commit secrets.

## Status

Created as documentation stub for Studio — activate after UAT of Odoo lease path
with fixture JSON.
