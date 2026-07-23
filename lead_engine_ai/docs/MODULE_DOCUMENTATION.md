# Lead Engine AI - Module Documentation

## 1. Module Description
- Technical module name: lead_engine_ai
- Functional name: Lead Engine AI
- Category: Sales/CRM
- Version: 19.0.1.1.0
- Summary: AI-drafted email replies for incoming CRM lead messages
- Main dependencies: crm, mail

Business value:
This module accelerates lead response handling by drafting reply suggestions using configured LLM providers while preserving human approval before sending.

## 2. User Guide
### Prerequisites
1. Configure API credentials for selected LLM provider.
2. Ensure incoming lead emails are routed to CRM.
3. Grant user access to AI draft menus and lead smart buttons.

### Basic setup steps
1. Install the module.
2. Configure provider, model, and prompt settings in module configuration.
3. Send a test inbound email to a CRM lead.
4. Open lead and confirm AI draft count smart button appears.

### Daily usage
1. Open lead with incoming email.
2. Review generated AI draft.
3. Launch compose window pre-filled with draft.
4. Edit if needed and send.

## 3. Use Case Example
Scenario:
Sales team receives high inbound message volume and needs faster first replies.

Example flow:
1. New inbound lead email arrives.
2. Background process generates AI reply draft.
3. Sales rep reviews and adjusts tone/details.
4. Rep sends response from Odoo compose.

Expected result:
- Faster response time.
- Higher consistency of first-contact messaging.
- Human-controlled quality before send.

## 4. Improvement Plan
### Short term (1-2 sprints)
1. Add prompt versioning and rollback.
2. Add confidence indicators for generated drafts.
3. Add fail-safe fallback message when provider errors occur.

### Mid term (1-2 months)
1. Add per-team response style templates.
2. Add auto-summarization of long email threads.
3. Add token usage and cost analytics dashboard.

### Long term (quarterly)
1. Add retrieval-augmented context from CRM history.
2. Add quality evaluation loop from user feedback.
3. Add model routing by language and intent.
