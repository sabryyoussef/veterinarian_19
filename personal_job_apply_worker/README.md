# Personal Job Apply Worker — Dry-Run Phase

Offline Playwright + FastAPI worker that drafts applications against **local HTML
fixtures only**. Real submission is hard-disabled. LinkedIn URLs are rejected.
No real credentials or CV are used.

## Paths

| Role | Path |
| --- | --- |
| Project (source of truth) | `/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/personal_job_apply_worker/` |
| Infra compose entry | `/home/sabry/infra/personal-job-apply-worker/` → symlink to project |
| Artifacts (not in git) | `/home/sabry/private/job_apply_worker/artifacts/` (mode `0700`) |

Do **not** reuse the `firefox-whatsapp` container or profile.

## API contract

Base URL (local / Docker): `http://127.0.0.1:8095`

OpenAPI docs: `GET /docs` (FastAPI auto). Schema: `GET /openapi.json`.

### `GET /health`

```json
{
  "status": "ok",
  "service": "personal-job-apply-worker",
  "dry_run_only": true,
  "submit_enabled": false,
  "version": "0.1.0"
}
```

### `POST /v1/apply/draft`

**Required:** `dry_run: true`. Rejected if `dry_run` is false.

**URL rules (this phase):**
- Must resolve to a file under `fixtures/` (e.g. `bebee_like.html` or `file://…/fixtures/bebee_like.html`)
- Any URL containing `linkedin.com` → stopped with `stop_reason: linkedin_blocked`
- External HTTP(S) ATS URLs are rejected (offline only)

Request:

```json
{
  "url": "bebee_like.html",
  "dry_run": true,
  "adapter": "bebee_like",
  "applicant": {
    "full_name": "Alex Example",
    "email": "alex.example@example.test",
    "phone": "+10000000000",
    "cover_letter": "Fictional dry-run cover letter.",
    "cv_filename": "test.pdf"
  },
  "metadata": {"job_id": 10}
}
```

Response (`ApplyAttemptResponse`):

```json
{
  "attempt_id": "uuid",
  "state": "drafted",
  "stop_reason": "none",
  "dry_run": true,
  "final_url": "file:///…/fixtures/bebee_like.html",
  "screenshot_paths": ["/home/sabry/private/job_apply_worker/artifacts/<id>/01_loaded.png"],
  "adapter_used": "bebee_like",
  "filled_fields": ["full_name", "email", "cover_letter", "cv"],
  "message": "…",
  "created_at": "…",
  "updated_at": "…",
  "metadata": {}
}
```

**States:** `pending` | `running` | `drafted` | `stopped` | `failed` | `submit_disabled`

**Stop reasons:** `captcha` | `otp` | `login_wall` | `consent` | `unknown_question` | `linkedin_blocked` | `submit_disabled` | `dry_run_required` | `invalid_url` | `none`

### `POST /v1/apply/submit`

**Always returns HTTP 403** with `stop_reason: submit_disabled` in this phase.

```json
{
  "attempt_id": "uuid",
  "dry_run": true,
  "confirm": true
}
```

### `GET /v1/apply/{attempt_id}`

Returns the stored attempt JSON (404 if unknown).

## Offline fixtures

| File | Purpose |
| --- | --- |
| `fixtures/bebee_like.html` | Simple name/email/cover/file form |
| `fixtures/greenhouse_like.html` | First/last/email/phone/resume form |
| `fixtures/unknown_question.html` | Custom weird field → stop |
| `fixtures/captcha.html` | CAPTCHA → stop |
| `fixtures/otp.html` | OTP → stop |
| `fixtures/test.pdf` | Fictional CV placeholder |

## Adapters

- `app/adapters/base.py` — `BaseApplyAdapter` interface
- `app/adapters/bebee_like.py` — BeBee-like stub
- `app/adapters/greenhouse_like.py` — Greenhouse-like stub

Adapters fill fields only; they never click submit.

## Run locally

```bash
cd /home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/personal_job_apply_worker
# Prefer uv if python3-venv is unavailable on the host:
uv venv .venv && source .venv/bin/activate
uv pip install -r requirements.txt
python -m playwright install chromium
mkdir -p -m 0700 /home/sabry/private/job_apply_worker/artifacts
uvicorn app.main:app --host 127.0.0.1 --port 8095
```

## Run with Docker (via infra symlink)

```bash
cd /home/sabry/infra/personal-job-apply-worker
docker compose up -d --build
curl -s http://127.0.0.1:8095/health
```

Or from the project directory:

```bash
cd /home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/personal_job_apply_worker
docker compose up -d --build
```

## Tests

```bash
cd /home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/personal_job_apply_worker
source .venv/bin/activate
python -m playwright install chromium   # needed for draft E2E tests
pytest -q
# Expected: 18 passed
```

Or without Playwright browsers (unit/API-only subset):

```bash
pytest -q tests/test_fixtures.py tests/test_api.py -k "not playwright"
```

## Security notes

- No secrets in this repo or compose file
- CV is always `fixtures/test.pdf` (fictional)
- Artifacts path is gitignored and mode `0700`
- Submit endpoint is permanently 403 until a future gated phase
