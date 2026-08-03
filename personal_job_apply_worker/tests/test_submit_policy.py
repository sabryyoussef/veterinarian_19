"""Unit tests for fail-closed submit authorization policy."""

from __future__ import annotations

import time

from app.submit_policy import (
    APPROVED_SUBMIT_ADAPTERS,
    evaluate_submit_authorization,
    verify_one_time_token,
)


def _auth(**overrides):
    base = {
        "live_submit_enabled": True,
        "approved_adapter": "greenhouse_like",
        "score": 65,
        "captcha_cleared": True,
        "login_cleared": True,
        "otp_cleared": True,
        "sensitive_docs_cleared": True,
        "profile_complete": True,
        "duplicate_cleared": True,
        "within_caps": True,
    }
    base.update(overrides)
    return base


def test_approved_adapters_include_direct_ats() -> None:
    assert "greenhouse_like" in APPROVED_SUBMIT_ADAPTERS
    assert "lever_like" in APPROVED_SUBMIT_ADAPTERS
    assert "workable_like" in APPROVED_SUBMIT_ADAPTERS
    assert "ashby_like" in APPROVED_SUBMIT_ADAPTERS
    assert "odoo_careers" in APPROVED_SUBMIT_ADAPTERS
    assert "bebee_like" not in APPROVED_SUBMIT_ADAPTERS


def test_gate_requires_live_submit_flag(monkeypatch) -> None:
    monkeypatch.setenv("PERSONAL_JOB_APPLY_SUBMIT_ENABLED", "true")
    gate = evaluate_submit_authorization(auth=_auth(live_submit_enabled=False), adapter_used="greenhouse_like")
    assert not gate.ok
    assert gate.code == "live_submit_disabled"


def test_gate_allows_score_zero(monkeypatch) -> None:
    monkeypatch.setenv("PERSONAL_JOB_APPLY_SUBMIT_ENABLED", "true")
    gate = evaluate_submit_authorization(auth=_auth(score=0), adapter_used="greenhouse_like")
    assert gate.ok


def test_gate_score_does_not_block(monkeypatch) -> None:
    monkeypatch.setenv("PERSONAL_JOB_APPLY_SUBMIT_ENABLED", "true")
    gate = evaluate_submit_authorization(auth=_auth(score=1), adapter_used="greenhouse_like")
    assert gate.ok
    assert gate.code == "ok"


def test_captcha_becomes_human_required(monkeypatch) -> None:
    monkeypatch.setenv("PERSONAL_JOB_APPLY_SUBMIT_ENABLED", "true")
    gate = evaluate_submit_authorization(auth=_auth(captcha_cleared=False), adapter_used="greenhouse_like")
    assert not gate.ok
    assert gate.human_required
    assert gate.code == "captcha"


def test_bebee_draft_only(monkeypatch) -> None:
    monkeypatch.setenv("PERSONAL_JOB_APPLY_SUBMIT_ENABLED", "true")
    gate = evaluate_submit_authorization(auth=_auth(approved_adapter="bebee_like"), adapter_used="bebee_like")
    assert not gate.ok
    assert gate.human_required


def test_all_gates_pass(monkeypatch) -> None:
    monkeypatch.setenv("PERSONAL_JOB_APPLY_SUBMIT_ENABLED", "true")
    gate = evaluate_submit_authorization(auth=_auth(), adapter_used="greenhouse_like")
    assert gate.ok


def test_token_consume_once() -> None:
    rec = {
        "token": "abc",
        "attempt_id": "att-1",
        "expires_at": time.time() + 60,
        "consumed": False,
    }
    ok = verify_one_time_token(token="abc", expected_attempt_id="att-1", token_store=rec)
    assert ok.ok
    rec["consumed"] = True
    bad = verify_one_time_token(token="abc", expected_attempt_id="att-1", token_store=rec)
    assert not bad.ok
    assert bad.code == "token_consumed"
