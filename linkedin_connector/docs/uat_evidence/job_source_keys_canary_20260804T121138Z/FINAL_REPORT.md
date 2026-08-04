# Job Source Keys Canary ? Adzuna install

**Stamp:** `20260804T121138Z`  
**Verdict:** `ADZUNA_ACTIVE_JOOBLE_STILL_BLOCKED`

## Credentials (presence only)

| Key | Status |
|-----|--------|
| Adzuna app_id / app_key | PRESENT + VALID (HTTP 200) ? ICP TEST+PROD |
| Jooble | MISSING in private env ? still BLOCKED |
| JSearch | PRESENT in `/etc/petspot/linkedin_jsearch.env` ? connector canary timed out again |

## Canaries

TEST + PROD: arbeitnow/remotive/lever/adzuna completed with apps/applied delta 0, `live_submit=False`.  
JSearch: adapter read-timeout. Jooble: skipped.

## PROD enabled after this run

`arbeitnow`, `remotive`, `lever`, `adzuna` (+ prior `remoteok`/`workable` if still enabled)

## Safety

- No live submit
- Applied count unchanged during canaries (10)
- Secrets not printed / not committed as values
