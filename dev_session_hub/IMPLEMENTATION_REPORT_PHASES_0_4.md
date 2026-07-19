# Development Work Lifecycle Hub — Phase 0–4 Implementation Report

Date: 2026-07-18
Module: `dev_session_hub`
Version: `19.0.2.0.0`
Scope: Phase 0 through Phase 4 only. No autonomous development worker was added.

## 1. Implementation summary

`dev_session_hub` now provides the canonical Odoo development-lifecycle and
artifact layer around OpenProject-backed work. The implemented flow is:

`Sanitized source reference → Work Item → accepted analysis → exact approved
plan → manual Dev Session → immutable checkpoints/resume brief → completion
report → reviewed Chatwoot outbox intent`

The implementation does not execute arbitrary repository instructions, create
branches, commit, push, deploy, call WhatsApp directly, or send HTTP requests.

## 2. Models created or extended

Created:

- `dev.work.item`
- `dev.work.source.message`
- `dev.work.external.link`
- `dev.work.lifecycle.event`
- `dev.work.analysis`
- `dev.work.plan`
- `dev.work.plan.step`
- `dev.work.approval`
- `dev.work.checkpoint`
- `dev.completion.report`
- `dev.work.communication`
- `dev.external.outbox`
- `dev.resume.brief.wizard`

Extended:

- `dev.session`: direct `work_item_id`, richer read-only Git snapshot,
  Work Item approval gate, automatic pause/review checkpoints, machine/client
  switch checkpoint, resume brief before the existing launcher.
- `dev.task.link`: retained as a deprecated compatibility model. It is no
  longer the primary lifecycle identity.

## 3. Migration

`migrations/19.0.2.0.0/post-migrate.py` preserves existing records. It links
legacy sessions only where a legacy OpenProject package ID resolves to exactly
one OP-backed `project.task`. Ambiguous or unmatched legacy links are left
unchanged for manual review; no external identity is invented.

Normal Odoo module upgrade creates the new tables and `dev.session.work_item_id`.

## 4. Views and menus

The Work Item form uses normal Odoo views with:

1. Source Request
2. Analysis
3. Plan and steps
4. Current Checkpoint
5. Development sessions
6. Tests
7. Completion
8. Communication
9. Audit

It includes OpenProject, Odoo task, and source-conversation smart buttons.
Recent Work menus include Active, Paused, Blocked, Awaiting Plan Approval, and
Ready for Review. Managers also receive lifecycle-audit and external-outbox
views. No custom OWL cockpit was added.

## 5. Lifecycle/state machine

Implemented states:

`received → triage → registered → analyzing → planning →
awaiting_plan_approval → approved → implementing → paused/blocked → testing →
ready_for_review → completed → reported`

`cancelled` is terminal. Invalid transitions and direct writes to the canonical
phase are rejected. Every valid transition appends an immutable lifecycle
event. Registration requires an OP-backed Odoo task whose backend and Work
Package ID agree with the Work Item.

## 6. Analysis and plan revisions

Analysis revisions are hashed and versioned. Only an analysis in the
`analyzing` phase can be accepted. Accepted and superseded analyses are
immutable.

Plans include structural plan-step content in the exact hash. Submission is
allowed only during `planning`. Approved and superseded plans are immutable.
Creating a replacement revision supersedes the prior plan and requires a new
approval gate. Active or closed execution cannot silently replace its plan.

Strict authenticated RPC import methods accept bounded allowlisted analysis
and plan draft schemas. They do not accept commands, credentials, raw payloads,
environment dumps, diffs, or transcripts, and they never start implementation.

## 7. Exact approval

`dev.work.approval` is append-only and records the Work Item, plan revision,
exact current plan hash, decision, approver, date, comment, and policy version.
Only Dev Hub approvers can approve or reject. Implementation requires a
currently approved plan and non-production registered repository/environment.

## 8. Checkpoints

`dev.work.checkpoint` is append-only. Pause creates a checkpoint automatically;
machine/client switch, agent handoff, major milestone, and ready-for-review are
supported triggers. Snapshots contain bounded structured state, plan progress,
Git branch/full HEAD/dirty summary/digest, ahead/behind when available, relative
files touched, environment/machine/client, task references, and sanitized notes.

No file content, full diff, unrestricted command history, raw environment dump,
credential, or full Cursor transcript is stored.

## 9. Resume brief example

```text
# Development Resume Brief
Work item: Shopify order status mismatch
Lifecycle: paused
OpenProject: https://…/work_packages/123
Odoo task: Shopify order status mismatch

## Accepted analysis
Order update webhook is accepted but the status mapping is incomplete.

## Approved plan
Revision 2, hash <exact SHA-256>, progress 3 / 5

## Latest checkpoint
Next: P4 — Run isolated order synchronization tests
Blockers: none
Git baseline: fix/shopify-order-update @ <full HEAD> (staged=0; …)

## Guardrails
- No production access or deployment.
- No automatic branch switch, commit, push, service restart, or Docker action.
```

The brief is bounded to 16,000 characters and reconstructed from canonical Odoo
records plus Git snapshots. Cursor thread history is optional metadata, not a
continuity dependency.

## 10. OpenProject behavior

OpenProject remains canonical for task-level delivery identity. The Dev Hub
does not mirror every internal phase. It prepares only idempotent sanitized
outbox intents for:

- analysis/plan ready;
- externally relevant material blocker;
- approved completion summary.

No OpenProject HTTP call is made from model `write()` or lifecycle actions.
Work Package creation remains on the existing canonical n8n/OpenProject path.

## 11. WhatsApp/Chatwoot behavior

Source records store normalized Evolution/Chatwoot identifiers and a sanitized
text snapshot, never a raw webhook payload. Completion communication requires:

- completed Work Item;
- approved completion report;
- original source message;
- matching original Chatwoot conversation when known;
- review;
- separate approver authorization.

Approval does not send or queue. An explicit human Queue action creates one
idempotent `chatwoot/public_message` outbox intent. Dev Hub has no direct
Evolution send and no HTTP transport implementation.

## 12. Security changes completed

- Test/non-production enforcement for implementation sessions.
- Exact plan-hash approval and approver group.
- Company/project membership record rules and model ACLs.
- Immutable lifecycle events, approvals, checkpoints, and approved artifacts.
- Bounded text/JSON schemas, secret-pattern rejection, forbidden payload keys,
  maximum nesting/item/byte limits.
- Guarded internal creation for lifecycle events, approvals, and outbox intents.
- No direct HTTP client in `dev_session_hub`.
- Single outbound intent route: Dev Hub → outbox/n8n → Chatwoot → Evolution.
- Git snapshot commands remain fixed and read-only.
- `.env` patterns are ignored and no `.env`, key, or PEM file is tracked.
- No secret value is included in this report.

## 13. Remaining security/integration blockers

- The existing Cursor remote launcher remains intentionally fail-closed until a
  managed helper can enforce the pinned SSH host key end to end.
- No deployed n8n consumer/callback was enabled in this change. Outbox records
  therefore remain intents until an independently authenticated consumer is
  configured.
- Real Chatwoot/Evolution delivery receipts were not exercised; doing so would
  be an external mutation.
- Automatic Dify/n8n analysis/plan generation was not enabled. Strict
  authenticated RPC draft-import methods are ready for a scoped service user.
- Existing ignored local environment files may contain operational credentials.
  Their values were not read or reported. Rotation/history review is an
  operations task and was not attempted against production-like services.
- The module directory is inside the Git repository but remains uncommitted.
  A reviewed commit is required for durable Git provenance.

## 14. Automated test results

Test database: `pet_spot_lifecycle_ci_20260718`
Mode: isolated Odoo 19 Test-only module upgrade, no external HTTP
Result: **PASS**

- 32 post-test methods
- Odoo statistics: 36 tests
- 0 failures
- 0 errors

Coverage includes dedupe, OP/Odoo identity constraints, lifecycle transitions,
artifact immutability, exact hash approval, approval invalidation, plan
progress, checkpoint immutability, pause checkpoint, resume sanitation/drift,
completion lifecycle, communication approval/no-auto-send, production denial,
and the complete Phase 1–4 UAT flow.

## 15. End-to-end UAT result

The automated non-production UAT passed:

1. Sanitized source linked.
2. OP-backed Odoo task and Work Item registered.
3. Analysis revision accepted.
4. Plan revision 1 superseded by revision 2.
5. Exact revision-2 hash approved.
6. Manual Dev Session started through the guarded launcher test double.
7. Three of five steps completed.
8. Pause created an immutable Git checkpoint.
9. Client switch created a handoff checkpoint.
10. Resume brief reconstructed revision 2 and progress 3/5.
11. Remaining steps completed.
12. Completion report submitted and approved after ready-for-review.
13. Arabic Chatwoot completion draft reviewed and approved.
14. Approval produced no automatic outbox/send.
15. Explicit Queue produced one Chatwoot outbox intent.
16. Work reached `reported`.

No production mutation, deployment, Git write, WhatsApp send, or OpenProject
write occurred.

## 16. File summary

Primary implementation files:

- `models/dev_work.py`
- `models/dev_session.py`
- `models/dev_registry.py`
- `wizards/dev_resume_brief_wizard.py`
- `views/dev_work_views.xml`
- `views/dev_session_views.xml`
- `views/dev_resume_brief_wizard_views.xml`
- `views/dev_session_hub_menus.xml`
- `security/dev_session_hub_security.xml`
- `security/ir.model.access.csv`
- `migrations/19.0.2.0.0/post-migrate.py`
- `tests/test_dev_work_lifecycle.py`
- manifest and package initializers

Because `dev_session_hub/` was already untracked at the start, Git cannot
separate the pre-existing MVP lines from these Phase 0–4 edits until the module
is reviewed and added to a commit.

## 17. Known limitations

- No autonomous agent worker.
- No live n8n outbox consumer or delivery callback.
- No live Dify generation trigger.
- No OpenProject Work Package creation from Odoo.
- No automatic commit, push, PR, deployment, or production verification.
- Legacy task links without one unambiguous OP-backed `project.task` require
  manual reconciliation.
- Compatibility alias fields generate non-blocking duplicate-label warnings
  during registry loading; they preserve migration/test API compatibility.

## 18. Phase 5 recommendation

Implement Phase 5 as a separate least-privileged pull worker, not inside Odoo
request handlers or n8n arbitrary command nodes. The worker should:

1. Poll signed, expiring execution requests for an exact approved plan hash.
2. Accept only registered repository/worktree/environment IDs.
3. Revalidate non-production policy and Git baseline before every run.
4. Execute in a constrained OS account/container with no production secrets.
5. Post structured progress events and immutable checkpoints.
6. Stop on drift, policy mismatch, approval change, or context revision change.
7. Never commit, push, deploy, or message externally without separate human
   approvals.
8. Use idempotent callbacks and retain a complete bounded audit trail.

Phase 5 should begin only after the launcher helper, n8n outbox consumer,
service-user scopes, callback authentication, and operational credential review
are complete and explicitly approved.
