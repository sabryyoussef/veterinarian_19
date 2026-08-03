"""FastAPI entrypoint for personal-job-apply-worker.

Default fail-closed: dry-run draft only. Unattended submit is allowed only when
PERSONAL_JOB_APPLY_SUBMIT_ENABLED=true AND all authorization gates pass.
CAPTCHA is never auto-solved.
"""

from __future__ import annotations

import os
import time

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
from app.submit_policy import (
    evaluate_submit_authorization,
    submit_env_enabled,
    verify_one_time_token,
)
from app.worker import ensure_artifacts_dir, run_draft, run_gated_submit
from app.evidence import evidence_from_email, evidence_from_page
from app.challenge_resume import (
    issue_challenge_token,
    verify_and_consume_challenge_token,
    load_challenge_token,
)
from app.email_apply import send_application_email, validate_application_email
from app.answer_mapper import map_schema_to_answers
from pydantic import BaseModel, Field
from typing import Any, Optional

app = FastAPI(
    title="Personal Job Apply Worker",
    description=(
        "Playwright worker for ATS draft/fill and fail-closed gated submit. "
        "LinkedIn URLs are rejected. CAPTCHA is never auto-solved."
    ),
    version=__version__,
)


@app.on_event("startup")
def _startup() -> None:
    ensure_artifacts_dir()


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    enabled = submit_env_enabled()
    return HealthResponse(
        version=__version__,
        dry_run_only=not enabled,
        submit_enabled=enabled,
    )


@app.post("/v1/apply/draft", response_model=ApplyAttemptResponse)
async def apply_draft(body: ApplyDraftRequest) -> ApplyAttemptResponse:
    if body.dry_run is not True:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "dry_run_required",
                "message": "dry_run=true is mandatory for draft",
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
            "fixture_url": body.url if not body.live_page else None,
            "url": body.url,
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
    """Fail-closed conditional submit.

    Requires env flag + live_submit_enabled + one-time token + approved adapter
    + cleared captcha/login/otp/sensitive + profile/duplicate/caps gates.
    CAPTCHA/login/OTP → human_required (never bypassed).
    """
    attempt = store.get(body.attempt_id)
    if not body.confirm:
        return JSONResponse(
            status_code=403,
            content={
                "attempt_id": body.attempt_id,
                "state": ApplyState.submit_disabled.value,
                "stop_reason": StopReason.submit_disabled.value,
                "message": "confirm=true is required",
            },
        )

    auth = body.authorization.model_dump()
    gate = evaluate_submit_authorization(
        auth=auth,
        adapter_used=(attempt.adapter_used if attempt else None) or auth.get("approved_adapter"),
        draft_metadata=attempt.metadata if attempt else None,
    )
    if not gate.ok:
        state = (
            ApplyState.human_required
            if gate.human_required
            else ApplyState.submit_disabled
        )
        stop = (
            StopReason.captcha
            if gate.code == "captcha"
            else StopReason.login_wall
            if gate.code == "login_wall"
            else StopReason.otp
            if gate.code == "otp"
            else StopReason.sensitive_docs
            if gate.code == "sensitive_docs"
            else StopReason.policy
            if gate.code not in {"submit_disabled", "live_submit_disabled"}
            else StopReason.submit_disabled
        )
        if attempt:
            store.update(
                body.attempt_id,
                state=state,
                stop_reason=stop,
                message=gate.message,
                dry_run=True,
            )
        return JSONResponse(
            status_code=403,
            content={
                "attempt_id": body.attempt_id,
                "state": state.value,
                "stop_reason": stop.value,
                "code": gate.code,
                "message": gate.message,
                "human_required": gate.human_required,
            },
        )

    # Register / verify one-time token (request may seed token store for first use)
    token_rec = store.get_token(body.attempt_id)
    if not token_rec:
        # Allow caller to seed token atomically with first submit request
        expires = time.time() + 3600
        token_rec = {
            "token": auth.get("one_time_token"),
            "attempt_id": body.attempt_id,
            "expires_at": expires,
            "consumed": False,
            **{k: auth.get(k) for k in auth},
        }
        store.put_token(body.attempt_id, token_rec)

    tok_gate = verify_one_time_token(
        token=str(auth.get("one_time_token") or ""),
        expected_attempt_id=body.attempt_id,
        token_store=token_rec,
    )
    if not tok_gate.ok:
        return JSONResponse(
            status_code=403,
            content={
                "attempt_id": body.attempt_id,
                "state": ApplyState.submit_disabled.value,
                "stop_reason": StopReason.policy.value,
                "code": tok_gate.code,
                "message": tok_gate.message,
            },
        )

    if not attempt:
        return JSONResponse(
            status_code=404,
            content={
                "attempt_id": body.attempt_id,
                "state": ApplyState.failed.value,
                "stop_reason": StopReason.invalid_url.value,
                "message": "attempt not found — draft first",
            },
        )

    result = await run_gated_submit(attempt_id=body.attempt_id, auth=auth)
    status = 200 if result.state in (ApplyState.succeeded, ApplyState.submission_unknown) else 409
    if result.state == ApplyState.human_required:
        status = 409
    return JSONResponse(status_code=status, content=result.model_dump(mode="json"))


@app.get("/v1/apply/{attempt_id}", response_model=ApplyAttemptResponse)
async def get_attempt(attempt_id: str) -> ApplyAttemptResponse:
    attempt = store.get(attempt_id)
    if not attempt:
        raise HTTPException(status_code=404, detail="attempt not found")
    return attempt


class ChallengePrepareRequest(BaseModel):
    attempt_id: str
    application_id: int
    job_id: int
    apply_url: str = ""
    challenge_type: str = "captcha"
    ttl_seconds: int = 1800
    filled_summary: dict[str, Any] = Field(default_factory=dict)


class ChallengeResumeRequest(BaseModel):
    attempt_id: str
    token: str
    application_id: Optional[int] = None
    challenge_solved: bool = False
    page_url: str = ""
    page_text: str = ""
    confirm_submit: bool = False


class EmailApplyRequest(BaseModel):
    recipient: str
    subject: str
    body: str
    cv_path: str
    cv_filename: str = "CV.pdf"
    job_url: str = ""
    job_id: Optional[int] = None
    application_id: Optional[int] = None
    dry_run: bool = True
    idempotency_key: str = ""


class MapSchemaRequest(BaseModel):
    fields_schema: list[dict[str, Any]] = Field(default_factory=list, alias="schema")
    extra_facts: dict[str, Any] = Field(default_factory=dict)
    applicant: Optional[dict[str, Any]] = None

    model_config = {"populate_by_name": True}


class EvidenceClassifyRequest(BaseModel):
    url: str = ""
    text: str = ""
    html: str = ""


@app.post("/v1/challenge/prepare")
async def challenge_prepare(body: ChallengePrepareRequest) -> JSONResponse:
    """Issue a single-use resume token after form fill; CAPTCHA never solved here."""
    tok = issue_challenge_token(
        attempt_id=body.attempt_id,
        application_id=body.application_id,
        job_id=body.job_id,
        apply_url=body.apply_url,
        ttl_seconds=body.ttl_seconds,
        challenge_type=body.challenge_type,
    )
    return JSONResponse(
        content={
            "ok": True,
            "token": tok.token,
            "fingerprint": tok.to_dict()["fingerprint"],
            "expires_at": tok.expires_at,
            "attempt_id": body.attempt_id,
            "application_id": body.application_id,
            "filled_summary": body.filled_summary,
            "message": "Solve challenge only; worker will auto-resume submit once.",
        }
    )


@app.post("/v1/challenge/resume")
async def challenge_resume(body: ChallengeResumeRequest) -> JSONResponse:
    """Consume one-time token after human challenge; submit at most once."""
    ok, code, data = verify_and_consume_challenge_token(
        attempt_id=body.attempt_id,
        token=body.token,
        expected_application_id=body.application_id,
    )
    if not ok:
        return JSONResponse(
            status_code=403,
            content={
                "ok": False,
                "code": code,
                "state": ApplyState.human_required.value,
                "message": f"challenge_token:{code}",
            },
        )
    if not body.challenge_solved:
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "code": "challenge_not_solved",
                "state": ApplyState.human_required.value,
                "message": "Challenge not marked solved; no submit.",
                "token_consumed": True,
            },
        )
    if not body.confirm_submit:
        return JSONResponse(
            status_code=403,
            content={
                "ok": False,
                "code": "confirm_required",
                "state": ApplyState.submit_disabled.value,
                "message": "confirm_submit=true required for auto-resume submit",
                "token_consumed": True,
            },
        )
    # Evidence classification — never mark applied without strong signal
    ev = evidence_from_page(url=body.page_url, text=body.page_text)
    state = ApplyState.succeeded if ev.ok else (
        ApplyState.submission_unknown if ev.ambiguous else ApplyState.human_required
    )
    return JSONResponse(
        content={
            "ok": ev.ok,
            "code": "resume_submit_authorized" if ev.ok else ("ambiguous" if ev.ambiguous else "no_evidence"),
            "state": state.value,
            "token_consumed": True,
            "submit_once": True,
            "evidence": ev.to_dict(),
            "challenge": {k: data.get(k) for k in ("attempt_id", "application_id", "job_id", "fingerprint")},
        }
    )


@app.post("/v1/email/apply")
async def email_apply(body: EmailApplyRequest) -> JSONResponse:
    valid, reason = validate_application_email(body.recipient)
    if not valid:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "code": reason, "recipient": body.recipient},
        )
    # Idempotency: same key returns prior dry-run result marker
    if body.idempotency_key:
        existing = store.get_token(f"email:{body.idempotency_key}")
        if existing and existing.get("result"):
            return JSONResponse(content={**existing["result"], "idempotent_replay": True})
    result = send_application_email(
        recipient=body.recipient,
        subject=body.subject,
        body=body.body,
        cv_path=body.cv_path,
        cv_filename=body.cv_filename,
        job_url=body.job_url,
        job_id=body.job_id,
        dry_run=body.dry_run,
    )
    payload = result.to_dict()
    payload["application_id"] = body.application_id
    if body.idempotency_key:
        store.put_token(
            f"email:{body.idempotency_key}",
            {"result": payload, "consumed": True, "expires_at": time.time() + 86400 * 30},
        )
    status = 200 if result.ok else 409
    return JSONResponse(status_code=status, content=payload)


@app.post("/v1/schema/map")
async def schema_map(body: MapSchemaRequest) -> JSONResponse:
    from app.models import ApplicantFixture

    applicant = None
    if body.applicant:
        applicant = ApplicantFixture(**body.applicant)
    answers, missing = map_schema_to_answers(
        body.fields_schema, applicant=applicant, extra_facts=body.extra_facts
    )
    return JSONResponse(
        content={
            "ok": not missing,
            "answers": answers,
            "missing_required": missing,
            "code": "ok" if not missing else "missing_fact",
        }
    )


@app.post("/v1/evidence/classify")
async def evidence_classify(body: EvidenceClassifyRequest) -> JSONResponse:
    ev = evidence_from_page(url=body.url, text=body.text, html=body.html)
    return JSONResponse(content=ev.to_dict())
