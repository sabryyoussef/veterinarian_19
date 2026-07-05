# Integration Bridge Core - Module Documentation

## 1. Module Description
- Technical module name: integration_bridge_core
- Functional name: Integration Bridge Core
- Category: Tools
- Version: 19.0.1.0.5
- Summary: Universal integration layer for Evolution WhatsApp, Chatwoot, n8n, Dify to Odoo 19
- Main dependencies: base, web, mail, crm, contacts

Business value:
This module is the integration backbone for external platforms, providing secure token-based endpoints, routing, logs, and outbound queue control.

## 2. User Guide
### Prerequisites
1. Odoo base dependencies installed.
2. Network access from external systems to Odoo bridge endpoints.
3. Integration tokens and optional IP whitelist policy defined.

### Basic setup steps
1. Install the module.
2. Configure master token, per-platform tokens, and whitelist in settings.
3. Validate /bridge/health endpoint.
4. Send a sample inbound request and review bridge logs.

### Daily usage
1. External systems call /bridge/inbound with platform token.
2. Module validates access and routes request.
3. Records are created/updated and outbound queue entries generated if needed.
4. Cron processes queue with retry logic.

## 3. Use Case Example
Scenario:
A company integrates Chatwoot and n8n with Odoo CRM.

Example flow:
1. Chatwoot message arrives and n8n enriches payload.
2. n8n posts to Odoo bridge endpoint.
3. Module authenticates token and stores request logs.
4. CRM lead and partner are created/updated.
5. Optional outbound message is queued and retried on failure.

Expected result:
- Secure and auditable integration operations.
- Reduced custom glue code across projects.

## 4. Improvement Plan
### Short term (1-2 sprints)
1. Add structured error codes for all endpoint responses.
2. Add retry policy tuning per platform.
3. Add admin action for replaying failed requests.

### Mid term (1-2 months)
1. Add per-platform throughput dashboards.
2. Add dead-letter queue handling and recovery workflow.
3. Add secret rotation helper for token management.

### Long term (quarterly)
1. Add event-driven architecture option alongside cron queue.
2. Add distributed tracing integration.
3. Add contract tests for third-party payload compatibility.
