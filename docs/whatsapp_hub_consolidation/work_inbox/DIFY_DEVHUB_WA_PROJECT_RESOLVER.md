# Dev Hub WhatsApp Project Resolver — Dify (Test)

**Canonical app name:** Dev Hub WhatsApp Project Resolver `[CANONICAL TEST]`  
**Canonical app ID:** `dee250c0-7f44-467c-9b0b-86f069bdc17e`  
**Published workflow ID:** `5f747cb0-4b84-4fc5-99d5-48d30e1b3c15`  
**Prompt version:** `wa_project_aware_v3.0` (native multi-item schema v3)  
**Status:** `normal`, `enable_api=true`  
**Model:** `openai` / `gpt-4o-mini` (Start → LLM Resolve → End)  
**Key env:** `DIFY_API_KEY_DEVHUB_WA_RESOLVER` (n8n only; never commit)  
**Consumer:** n8n workflow `j3xV5kXRQUu1k0p4`  

**Obsolete duplicate (do not use):** `8dfa0b80-d66a-4018-b205-daf78a5eea7d` — API/site disabled; retained for audit.  
**Shadow v2.4 (do not use live):** `0621c1db-cc51-40ee-844d-37b6a03f5ade`

Do not modify Chatwoot triage / OP production apps.

## Input

`request_json` — full Odoo job payload including `messages[]`, `technical_evidence`, candidates, `selection_policy`.

## Output

JSON `schema_version: "3"` with native `items[]`, validated by `dev_whatsapp_analysis_utils.py` (`result` key from End node).

Prompt source of truth: `/home/sabry/infra/dify/prompts/devhub-wa-project-resolver-v3.0.txt`

## Verified run (Kafaat native v3)

| Run ID | Notes |
|--------|-------|
| `a99b5f68-03ac-45a6-a138-c7a259fa9573` | 2 items (RPC paths + Batch Intake); project 11 |
