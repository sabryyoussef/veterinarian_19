"""Fixture presence + detector unit tests (no browser required)."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"

REQUIRED = [
    "bebee_like.html",
    "greenhouse_like.html",
    "unknown_question.html",
    "captcha.html",
    "otp.html",
    "test.pdf",
]


@pytest.mark.parametrize("name", REQUIRED)
def test_fixture_exists(name: str) -> None:
    path = FIXTURES / name
    assert path.is_file(), f"missing fixture: {name}"
    assert path.stat().st_size > 0


def test_test_pdf_is_pdf_header() -> None:
    data = (FIXTURES / "test.pdf").read_bytes()
    assert data.startswith(b"%PDF")


def test_detect_stop_reasons_from_html() -> None:
    from app.detectors import detect_stop_reason_from_html
    from app.models import StopReason

    captcha = (FIXTURES / "captcha.html").read_text(encoding="utf-8")
    otp = (FIXTURES / "otp.html").read_text(encoding="utf-8")
    unknown = (FIXTURES / "unknown_question.html").read_text(encoding="utf-8")
    bebee = (FIXTURES / "bebee_like.html").read_text(encoding="utf-8")

    assert detect_stop_reason_from_html(captcha) == StopReason.captcha
    assert detect_stop_reason_from_html(otp) == StopReason.otp
    assert detect_stop_reason_from_html(unknown) == StopReason.unknown_question
    assert detect_stop_reason_from_html(bebee) is None


def test_linkedin_url_blocked() -> None:
    from app.detectors import is_linkedin_url

    assert is_linkedin_url("https://www.linkedin.com/jobs/view/123")
    assert is_linkedin_url("https://linkedin.com/jobs/")
    assert is_linkedin_url("file:///tmp/linkedin.com/fake.html")  # path contains linkedin.com
    assert not is_linkedin_url("bebee_like.html")
    assert not is_linkedin_url("https://example.test/jobs/1")


def test_resolve_offline_fixture() -> None:
    from app.worker import resolve_offline_url

    path = resolve_offline_url("bebee_like.html")
    assert path.name == "bebee_like.html"
    assert path.is_file()

    with pytest.raises(PermissionError):
        resolve_offline_url("https://www.linkedin.com/jobs/view/1")

    with pytest.raises(ValueError):
        resolve_offline_url("https://boards.greenhouse.io/example/jobs/1")
