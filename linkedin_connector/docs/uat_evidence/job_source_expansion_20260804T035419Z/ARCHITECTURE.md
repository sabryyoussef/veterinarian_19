# Architecture summary

Connector scheduler → adapter registry → sanitize/archive → normalize → validate →
deterministic dedupe → hard filters → scoring (raw + 0–100) → preflight → lifecycle →
existing application workflow (evidence-gated applied).

Secrets via ICP key names only. Restricted adapters refuse fetch.
