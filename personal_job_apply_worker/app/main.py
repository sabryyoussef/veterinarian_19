"""FastAPI entrypoint for personal-job-apply-worker.

Default fail-closed: dry-run draft only; submit disabled unless
PERSONAL_JOB_APPLY_SUBMIT_ENABLED=true. CAPTCHA is never auto-solved.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from app import __version__
from app.detectors import is_linkedin_url
from app.models import (
    ApplyAttemptResponse,
    ApplyDraftRequest,
    ApplyState,
    ApplySubmitRequest,
    HealthResponse,
    StopReason,
)
from app.store import store
from app.worker import ensure_artifacts_dir, run_draft

app = FastAPI(
    title="Personal Job Apply Worker",
    description=(
        "Playwright worker for ATS draft/fill. "
        "Submit stays disabled unless PERSONAL_JOB_APPLY_SUBMIT_ENABLED=true. "
        "LinkedIn URLs are rejected. CAPTCHA is never auto-solved."
    ),
    version=__version__,
)


def _submit_enabled() -> bool:
    return os.environ.get("PERSONAL_JOB_APPLY_SUBMIT_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


@app.on_event("startup")
def _startup() -> None:
    ensure_artifacts_dir()


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    enabled = _submit_enabled()
    return HealthResponse(
        version=__version__,
        dry_run_only=not enabled,
        submit_enabled=enabled,
    )


@app.post("/v1/apply/draft", response_model=ApplyAttemptResponse)
async def apply_draft(body: ApplyDraftRequest) -> ApplyAttemptResponse:
    # Pydantic already enforces dry_run=true; belt-and-suspenders:
    if body.dry_run is not True:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "dry_run_required",
                "message": "dry_run=true is mandatory in this phase",
                "stop_reason": StopReason.dry_run_required.value,
            },
        )

    if is_linkedin_url(body.url):
        attempt = store.create(
            metadata=body.metadata,
            state=ApplyState.stopped,
            stop_reason=StopReason.linkedin_blocked,
            message="LinkedIn URLs are blocked",
        )
        return store.update(attempt.attempt_id, final_url=body.url)  # type: ignore[return-value]

    meta = dict(body.metadata or {})
    meta.update(
        {
            "live_page": body.live_page,
            "network_mutations": body.network_mutations,
            "submit": body.submit,
        }
    )
    attempt = store.create(metadata=meta, message="queued")
    result = await run_draft(
        attempt_id=attempt.attempt_id,
        url=body.url,
        applicant=body.applicant,
        adapter_hint=body.adapter,
        live_page=body.live_page,
        network_mutations=body.network_mutations,
        submit=body.submit,
    )
    return result


@app.post("/v1/apply/submit")
async def apply_submit(body: ApplySubmitRequest) -> JSONResponse:
    """Fail-closed submit gate.

    Even with PERSONAL_JOB_APPLY_SUBMIT_ENABLED=true, unattended click-submit is
    refused here — CAPTCHA/login walls require human handoff or a dedicated
    controlled canary runner. Default remains 403.
    """
    attempt = store.get(body.attempt_id)
    if not _submit_enabled():
        if attempt:
            store.update(
                body.attempt_id,
                state=ApplyState.submit_disabled,
                stop_reason=StopReason.submit_disabled,
                message="Submit disabled (PERSONAL_JOB_APPLY_SUBMIT_ENABLED not set)",
            )
        return JSONResponse(
            status_code=403,
            content={
                "attempt_id": body.attempt_id,
                "state": ApplyState.submit_disabled.value,
                "stop_reason": StopReason.submit_disabled.value,
                "dry_run": True,
                "final_url": attempt.final_url if attempt else None,
                "screenshot_paths": attempt.screenshot_paths if attempt else [],
                "message": "POST /v1/apply/submit is disabled (fail-closed default)",
            },
        )
    if attempt:
        store.update(
            body.attempt_id,
            state=ApplyState.submit_disabled,
            stop_reason=StopReason.submit_disabled,
            message="Automated click-submit not enabled; use human handoff or canary runner",
        )
    return JSONResponse(
        status_code=403,
        content={
            "attempt_id": body.attempt_id,
            "state": ApplyState.submit_disabled.value,
            "stop_reason": StopReason.submit_disabled.value,
            "dry_run": False,
            "message": (
                "Submit flag acknowledged but unattended click-submit is refused "
                "(CAPTCHA/policy). Use controlled canary/human handoff."
            ),
        },
    )


@app.get("/v1/apply/{attempt_id}", response_model=ApplyAttemptResponse)
async def get_attempt(attempt_id: str) -> ApplyAttemptResponse:
    attempt = store.get(attempt_id)
    if not attempt:
        raise HTTPException(status_code=404, detail="attempt not found")
    return attempt
