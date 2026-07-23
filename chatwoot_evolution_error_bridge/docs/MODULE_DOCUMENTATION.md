# Chatwoot Evolution Error Bridge - Module Documentation

## 1. Module Description
- Technical module name: chatwoot_evolution_error_bridge
- Functional name: Chatwoot Evolution Error Bridge
- Category: Tools
- Version: 19.0.1.0.1
- Summary: Chatwoot/Evolution WhatsApp -> Odoo 19 CRM bridge (error_reporter_16-free)
- Main dependencies: base, web, mail, crm, integration_bridge_core

Business value:
This module provides backward-compatible webhook routing from Chatwoot and Evolution WhatsApp into Odoo CRM, so existing automations keep working after migration to Odoo 19.

## 2. User Guide
### Prerequisites
1. Install integration_bridge_core first.
2. Ensure CRM and Mail apps are installed.
3. Prepare webhook token and endpoint details used by Chatwoot/n8n flows.

### Basic setup steps
1. Install the module from Apps.
2. Open Settings and configure bridge parameters exposed by this module.
3. Verify that the legacy endpoint /bridge/error_reports is reachable.
4. Run one test payload from Chatwoot or automation flow.

### Daily usage
1. Receive inbound webhook from Chatwoot/Evolution.
2. Module maps payload fields to crm.lead and partner context.
3. Review created/updated lead records and bridge logs.
4. Follow standard CRM pipeline handling.

## 3. Use Case Example
Scenario:
A support team still uses a legacy n8n flow posting to /bridge/error_reports.

Example flow:
1. Customer sends a WhatsApp message.
2. Chatwoot automation forwards payload to Odoo legacy endpoint.
3. Module converts message context to CRM lead data.
4. Sales/support team tracks conversation from Odoo lead form.

Expected result:
- No interruption after migrating from old error.report model.
- Unified CRM tracking for chat-originated interactions.

## 4. Improvement Plan
### Short term (1-2 sprints)
1. Add stricter payload schema validation and clearer 4xx error messages.
2. Add a troubleshooting wizard for failed webhook requests.
3. Add demo webhook examples for quick QA.

### Mid term (1-2 months)
1. Add correlation ID tracing across bridge logs and CRM leads.
2. Add per-platform rate-limit controls and retries.
3. Add richer mapping settings for custom payload fields.

### Long term (quarterly)
1. Add integration test suite with replayable webhook fixtures.
2. Add observability dashboards and alert hooks.
3. Add migration assistant for future endpoint deprecations.
