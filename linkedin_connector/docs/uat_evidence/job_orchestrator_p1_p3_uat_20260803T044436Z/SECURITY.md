# Security review — UAT foundation

## Controls verified
- HMAC signature + 5-minute timestamp skew on orchestrator API
- Empty/missing webhook secret ⇒ requests unauthorized (except public health)
- Company account / id=1 operations rejected (model constraints + API 403)
- Unauthorized pack state transitions fail closed (409)
- `invented_facts` in pack ⇒ 422
- Attempt API forces `dry_run=true`; live `submitted`/`succeeded` ⇒ 403
- Policy kill_switch default True; browser/email submit flags default False
- Candidate profile omits unset sensitive fields from sanitized JSON
- Worker: submit 403; LinkedIn blocked; artifacts outside Git with 0700
- No WhatsApp/email nodes in n8n UAT export
- Ephemeral E2E secret removed from `/tmp` after run; only TEST ICP retains secret (fingerprint recorded)

## Residual risks / next canary
- Dify Studio app not yet imported — until then, packs validated via fixture simulator
- n8n workflow not imported to instance (export-only; N8N_API_KEY absent for automated import)
- Signed API uses `auth=public` + HMAC; rotate TEST secret before any broader use
- Do not reuse TEST secret on Production

## Secrets policy
Never commit: webhook secrets, Dify app keys, n8n credentials, cookies, CV binaries, passwords.
