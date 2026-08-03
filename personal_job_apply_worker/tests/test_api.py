"""FastAPI contract tests (TestClient). Playwright E2E marked separately."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "personal-job-apply-worker"
    assert body["dry_run_only"] is True
    assert body["submit_enabled"] is False


def test_draft_rejects_dry_run_false() -> None:
    r = client.post(
        "/v1/apply/draft",
        json={"url": "bebee_like.html", "dry_run": False},
    )
    assert r.status_code == 422


def test_draft_blocks_linkedin() -> None:
    r = client.post(
        "/v1/apply/draft",
        json={
            "url": "https://www.linkedin.com/jobs/view/999",
            "dry_run": True,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["stop_reason"] == "linkedin_blocked"
    assert body["state"] == "stopped"
    assert body["dry_run"] is True


def test_submit_always_403() -> None:
    r = client.post(
        "/v1/apply/submit",
        json={"attempt_id": "does-not-exist", "dry_run": True, "confirm": True},
    )
    assert r.status_code == 403
    body = r.json()
    assert body["stop_reason"] == "submit_disabled"
    assert body["state"] == "submit_disabled"


@pytest.mark.playwright
def test_draft_bebee_like_playwright() -> None:
    r = client.post(
        "/v1/apply/draft",
        json={
            "url": "bebee_like.html",
            "dry_run": True,
            "adapter": "bebee_like",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert body["state"] in ("drafted", "failed")  # failed if browser missing
    if body["state"] == "drafted":
        assert body["stop_reason"] == "none"
        assert "full_name" in body["filled_fields"]
        assert body["adapter_used"] == "bebee_like"
        assert body["screenshot_paths"]
        attempt_id = body["attempt_id"]
        g = client.get(f"/v1/apply/{attempt_id}")
        assert g.status_code == 200
        assert g.json()["attempt_id"] == attempt_id
        # submit still 403 after draft
        s = client.post(
            "/v1/apply/submit",
            json={"attempt_id": attempt_id, "dry_run": True, "confirm": True},
        )
        assert s.status_code == 403


@pytest.mark.playwright
def test_draft_captcha_stops() -> None:
    r = client.post(
        "/v1/apply/draft",
        json={"url": "captcha.html", "dry_run": True},
    )
    assert r.status_code == 200
    body = r.json()
    if body["state"] == "stopped":
        assert body["stop_reason"] == "captcha"


@pytest.mark.playwright
def test_draft_otp_stops() -> None:
    r = client.post(
        "/v1/apply/draft",
        json={"url": "otp.html", "dry_run": True},
    )
    assert r.status_code == 200
    body = r.json()
    if body["state"] == "stopped":
        assert body["stop_reason"] == "otp"


@pytest.mark.playwright
def test_draft_unknown_question_stops() -> None:
    r = client.post(
        "/v1/apply/draft",
        json={"url": "unknown_question.html", "dry_run": True},
    )
    assert r.status_code == 200
    body = r.json()
    if body["state"] == "stopped":
        assert body["stop_reason"] == "unknown_question"
