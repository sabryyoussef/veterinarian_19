"""Pydantic request/response models for the dry-run apply API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class ApplyState(str, Enum):
    pending = "pending"
    running = "running"
    drafted = "drafted"
    stopped = "stopped"
    failed = "failed"
    submit_disabled = "submit_disabled"


class StopReason(str, Enum):
    captcha = "captcha"
    otp = "otp"
    login_wall = "login_wall"
    consent = "consent"
    unknown_question = "unknown_question"
    linkedin_blocked = "linkedin_blocked"
    submit_disabled = "submit_disabled"
    dry_run_required = "dry_run_required"
    invalid_url = "invalid_url"
    network_mutation = "network_mutation"
    none = "none"


class ApplicantFixture(BaseModel):
    """Applicant data for draft fill.

    Offline fixture mode: fictional defaults + fixtures/test.pdf only.
    Gated live_page mode: may use allowlisted local CV path (never uploaded).
    """

    full_name: str = Field(default="Alex Example", max_length=120)
    email: str = Field(default="alex.example@example.test", max_length=200)
    phone: str = Field(default="+10000000000", max_length=40)
    cover_letter: str = Field(
        default="This is a fictional dry-run cover letter for offline fixture testing.",
        max_length=5000,
    )
    # Relative to fixtures/ in offline mode; must be test.pdf unless live_page.
    cv_filename: str = Field(default="test.pdf", max_length=200)
    # Absolute allowlisted CV path for gated live_page drafts only.
    cv_local_path: Optional[str] = Field(default=None, max_length=500)


class ApplyDraftRequest(BaseModel):
    """POST /v1/apply/draft body."""

    url: str = Field(..., description="Fixture name or (gated) live https URL.")
    dry_run: bool = Field(..., description="Must be true. Real submits are hard-disabled.")
    submit: bool = Field(default=False, description="Must remain false.")
    live_page: bool = Field(
        default=False,
        description="When true, allow a single live https page with network containment.",
    )
    network_mutations: bool = Field(
        default=False,
        description="Must be false. Live mode blocks POST/PUT/PATCH/DELETE/upload/websocket.",
    )
    applicant: ApplicantFixture = Field(default_factory=ApplicantFixture)
    adapter: Optional[str] = Field(
        default=None,
        description="Optional adapter hint: bebee_like | greenhouse_like | odoo_careers | auto",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("dry_run")
    @classmethod
    def dry_run_must_be_true(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("dry_run=true is mandatory in this phase")
        return v

    @model_validator(mode="after")
    def validate_live_gates(self) -> "ApplyDraftRequest":
        if self.submit is not False:
            raise ValueError("submit must be false")
        if self.network_mutations is not False:
            raise ValueError("network_mutations must be false")
        if self.live_page:
            if not (self.url.startswith("http://") or self.url.startswith("https://")):
                raise ValueError("live_page=true requires an http(s) URL")
            if "linkedin.com" in self.url.lower():
                raise ValueError("LinkedIn URLs are blocked")
        else:
            if self.applicant.cv_local_path:
                raise ValueError("cv_local_path is only allowed when live_page=true")
            if self.applicant.cv_filename != "test.pdf":
                raise ValueError("offline mode requires cv_filename=test.pdf")
        return self


class ApplySubmitRequest(BaseModel):
    """POST /v1/apply/submit body — always rejected with 403."""

    attempt_id: str
    dry_run: bool = True
    confirm: bool = False


class ApplyAttemptResponse(BaseModel):
    attempt_id: str
    state: ApplyState
    stop_reason: StopReason
    dry_run: bool = True
    final_url: Optional[str] = None
    screenshot_paths: list[str] = Field(default_factory=list)
    adapter_used: Optional[str] = None
    filled_fields: list[str] = Field(default_factory=list)
    message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "personal-job-apply-worker"
    dry_run_only: bool = True
    submit_enabled: bool = False
    version: str = "0.1.0"
