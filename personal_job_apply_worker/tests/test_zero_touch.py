"""Unit tests for zero-touch evidence, challenge tokens, email, answer mapping."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.answer_mapper import map_schema_to_answers
from app.challenge_resume import (
    issue_challenge_token,
    verify_and_consume_challenge_token,
)
from app.email_apply import send_application_email, validate_application_email
from app.evidence import evidence_from_email, evidence_from_page
from app.models import ApplicantFixture


def test_evidence_thank_you_strong():
    ev = evidence_from_page(
        url="https://example.test/careers/thank-you",
        text="Thank you! Your application has been received. Reference APP-99881",
    )
    assert ev.ok
    assert not ev.ambiguous
    assert ev.confirmation_reference


def test_evidence_ambiguous_no_confirmation():
    ev = evidence_from_page(
        url="https://example.test/careers/apply",
        text="Please wait while we process…",
    )
    assert not ev.ok
    assert ev.ambiguous


def test_evidence_email_ok():
    ev = evidence_from_email(
        provider_message_id="smtp-abc",
        rfc_message_id="<x@job-apply.local>",
        recipient="jobs@acme.example",
        job_id=42,
    )
    assert ev.ok


def test_evidence_email_missing_ids_ambiguous():
    ev = evidence_from_email(
        provider_message_id="",
        rfc_message_id="",
        recipient="jobs@acme.example",
    )
    assert not ev.ok
    assert ev.ambiguous


def test_challenge_token_single_use(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_APPLY_CHALLENGE_TOKEN_DIR", str(tmp_path))
    # Force module to use new dir — re-import path via issue which reads TOKEN_DIR at call
    import app.challenge_resume as cr

    monkeypatch.setattr(cr, "TOKEN_DIR", Path(tmp_path))
    tok = issue_challenge_token(
        attempt_id="att-1",
        application_id=10,
        job_id=20,
        apply_url="https://example.test/apply",
        ttl_seconds=60,
    )
    ok, code, _ = verify_and_consume_challenge_token(
        attempt_id="att-1", token=tok.token, expected_application_id=10
    )
    assert ok and code == "ok"
    ok2, code2, _ = verify_and_consume_challenge_token(
        attempt_id="att-1", token=tok.token, expected_application_id=10
    )
    assert not ok2 and code2 == "token_consumed"


def test_challenge_token_expiry(tmp_path, monkeypatch):
    import app.challenge_resume as cr

    monkeypatch.setattr(cr, "TOKEN_DIR", Path(tmp_path))
    tok = issue_challenge_token(
        attempt_id="att-exp",
        application_id=1,
        job_id=2,
        apply_url="https://example.test/a",
        ttl_seconds=1,
    )
    # Force expire
    data = cr.load_challenge_token("att-exp")
    assert data
    data["expires_at"] = time.time() - 10
    (Path(tmp_path) / "att-exp.json").write_text(__import__("json").dumps(data))
    ok, code, _ = verify_and_consume_challenge_token(
        attempt_id="att-exp", token=tok.token
    )
    assert not ok and code == "token_expired"


def test_map_schema_known_and_missing():
    schema = [
        {"field_id": "n", "name": "full_name", "label": "Full name", "field_type": "text", "required": True},
        {"field_id": "e", "name": "email", "label": "Email", "field_type": "email", "required": True},
        {
            "field_id": "x",
            "name": "favorite_color",
            "label": "Favorite color",
            "field_type": "text",
            "required": True,
        },
    ]
    applicant = ApplicantFixture(full_name="Sabry Youssef", email="vendorah2@gmail.com")
    answers, missing = map_schema_to_answers(schema, applicant=applicant)
    assert answers.get("full_name") == "Sabry Youssef"
    assert answers.get("email") == "vendorah2@gmail.com"
    assert any("Favorite color" in m for m in missing)


def test_map_schema_sensitive_not_via_mapper_file_ok():
    schema = [
        {"field_id": "r", "name": "resume", "label": "Resume", "field_type": "file", "required": True},
    ]
    answers, missing = map_schema_to_answers(schema)
    assert answers.get("r") == "__CV__"
    assert not missing


def test_email_validate_blocks_linkedin():
    ok, reason = validate_application_email("hr@linkedin.com")
    assert not ok
    assert reason == "blocked_domain"


def test_email_dry_run_send(tmp_path):
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4 test")
    result = send_application_email(
        recipient="careers@acme.example",
        subject="Application: Odoo Developer",
        body="Please find my CV attached.",
        cv_path=str(cv),
        job_id=7,
        dry_run=True,
    )
    assert result.ok
    assert result.dry_run
    assert result.rfc_message_id
    assert result.provider_message_id.startswith("dryrun-")
