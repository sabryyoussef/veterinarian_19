# Dev Hub roadmap decisions (locked 2026-07-20)

Approved after Dell MVP PASS. **Item 6 not started** at documentation trim time.

## 1. Managed helper architecture

- One cross-platform user-level agent/helper where practical.
- Outbound signed-job polling to the central Dev Hub.
- Linux local IPC: Unix domain socket.
- Windows local IPC: named pipe.
- Do not use localhost HTTPS unless a documented platform constraint makes it necessary.
- No inbound arbitrary shell.
- No arbitrary argv.
- Cursor launch uses a fixed allowlisted URI/argument builder.

## 2. Tailscale verification expiry

- Default TTL: **168 hours**.
- Fail closed after expiry.
- Immediate invalidation on identity-critical field changes.
- Reverification required before launch after expiry.
- Policy may choose a shorter TTL but may **not** silently disable expiry for sensitive environments.

## 3. Session ownership

- Exactly one active client.
- Explicit audited handoff.
- Current client releases ownership or a bounded lease expires.
- No silent stealing and no dual writers.
- Git SHA/dirty-state revalidation before the new client claims the session.

## 4. Dell-local Odoo retirement

- Keep Dell Test Odoo until central agent/helper parity passes.
- Require shadow-mode evidence, rollback, and separate human approval before decommissioning it.

## 5. Approved implementation order

1. Item 6 — track `project_public_task_update`
2. Item 7 — portable seed/onboarding data
3. Item 9 — architecture design only
4. Item 8 — verification expiry
5. Item 3 — SSH/pin distribution
6. Item 1 — managed helper
7. Item 2 — additional clients
8. Item 4 — lifecycle UAT
9. Item 5 — cross-device continuity
10. Item 9 — implementation
11. Item 10 — full UAT and Production gates
