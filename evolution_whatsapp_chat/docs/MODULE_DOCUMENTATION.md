# WhatsApp Chat - Module Documentation

## 1. Module Description
- Technical module name: evolution_whatsapp_chat
- Functional name: WhatsApp Chat
- Category: Productivity
- Version: 19.0.1.7.0
- Summary: Send and receive WhatsApp from CRM leads and contacts via Evolution API plus Campaigns
- Main dependencies: base, mail, crm, contacts, integration_bridge_core

Business value:
This module enables WhatsApp messaging directly from Odoo CRM and Contacts, improving response speed and campaign execution from a single business system.

## 2. User Guide
### Prerequisites
1. Install integration_bridge_core and configure Evolution API connectivity.
2. Ensure CRM, Contacts, and Discuss are available.
3. Confirm API tokens and endpoint parameters are set.

### Basic setup steps
1. Install the module.
2. Configure WhatsApp templates and bridge settings.
3. Open contact or lead form and test Send WhatsApp action.
4. Verify incoming messages appear in Discuss and chatter.

### Daily usage
1. Open a lead/contact record.
2. Use quick-send wizard or campaign tools.
3. Track delivery/read statuses in campaign lines.
4. Review analytics dashboard for performance.

## 3. Use Case Example
Scenario:
Recruitment team sends outreach and follow-up messages at scale.

Example flow:
1. Team creates a campaign with selected leads.
2. System sends messages through Evolution API.
3. Incoming responses are logged to discussion channels.
4. Team updates lead stages based on responses.

Expected result:
- Faster lead engagement.
- Better visibility of message outcomes.
- Centralized communication history in CRM.

## 4. Improvement Plan
### Short term (1-2 sprints)
1. Add template variable previews before sending.
2. Add clearer per-recipient failure reasons.
3. Add guardrails for duplicate manual sends.

### Mid term (1-2 months)
1. Add queue throttling by channel/provider limits.
2. Add campaign A/B template testing.
3. Add SLA alerts for unanswered inbound messages.

### Long term (quarterly)
1. Add multi-provider failover strategy.
2. Add conversation sentiment tagging for prioritization.
3. Add end-to-end tests for inbound and outbound lifecycle.
