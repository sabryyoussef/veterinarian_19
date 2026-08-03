# -*- coding: utf-8 -*-
"""Authenticated job-application email channel (fail-closed, mockable)."""

from __future__ import annotations

import hashlib
import os
import re
import smtplib
import time
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Optional

from app.evidence import evidence_from_email

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_BLOCKED_RECIPIENT_DOMAINS = frozenset(
    {
        "linkedin.com",
        "mail.linkedin.com",
        "facebook.com",
        "twitter.com",
    }
)


@dataclass
class EmailApplyResult:
    ok: bool
    code: str
    provider_message_id: str = ""
    rfc_message_id: str = ""
    recipient: str = ""
    content_hash: str = ""
    message: str = ""
    dry_run: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "code": self.code,
            "provider_message_id": self.provider_message_id,
            "rfc_message_id": self.rfc_message_id,
            "recipient": self.recipient,
            "content_hash": self.content_hash,
            "message": self.message,
            "dry_run": self.dry_run,
        }


def validate_application_email(address: str) -> tuple[bool, str]:
    addr = (address or "").strip().lower()
    if not addr or not _EMAIL_RE.match(addr):
        return False, "invalid_email"
    domain = addr.split("@", 1)[-1]
    if domain in _BLOCKED_RECIPIENT_DOMAINS:
        return False, "blocked_domain"
    if domain.endswith(".linkedin.com"):
        return False, "blocked_domain"
    return True, "ok"


def build_application_email(
    *,
    recipient: str,
    subject: str,
    body: str,
    from_addr: str,
    cv_path: str,
    cv_filename: str,
    job_url: str = "",
) -> tuple[EmailMessage, str]:
    msg = EmailMessage()
    msg["Subject"] = subject[:200]
    msg["From"] = from_addr
    msg["To"] = recipient
    rfc_id = f"<{uuid.uuid4()}@job-apply.local>"
    msg["Message-ID"] = rfc_id
    if job_url:
        body = f"{body.rstrip()}\n\nJob listing: {job_url}\n"
    msg.set_content(body)
    with open(cv_path, "rb") as fh:
        data = fh.read()
    msg.add_attachment(
        data,
        maintype="application",
        subtype="pdf",
        filename=cv_filename or "CV.pdf",
    )
    content_hash = hashlib.sha256(
        (subject + "\n" + body + "\n" + hashlib.sha256(data).hexdigest()).encode()
    ).hexdigest()
    return msg, content_hash


def send_application_email(
    *,
    recipient: str,
    subject: str,
    body: str,
    cv_path: str,
    cv_filename: str = "CV.pdf",
    job_url: str = "",
    job_id: Optional[int] = None,
    dry_run: bool = True,
) -> EmailApplyResult:
    ok, reason = validate_application_email(recipient)
    if not ok:
        return EmailApplyResult(ok=False, code=reason, recipient=recipient, dry_run=dry_run)

    from_addr = (
        os.environ.get("JOB_APPLY_EMAIL_FROM")
        or os.environ.get("PERSONAL_JOB_APPLY_EMAIL_FROM")
        or "noreply@example.invalid"
    )
    try:
        msg, content_hash = build_application_email(
            recipient=recipient,
            subject=subject,
            body=body,
            from_addr=from_addr,
            cv_path=cv_path,
            cv_filename=cv_filename,
            job_url=job_url,
        )
    except Exception as exc:  # noqa: BLE001
        return EmailApplyResult(
            ok=False, code="build_failed", recipient=recipient, message=str(exc)[:200], dry_run=dry_run
        )

    rfc_id = str(msg["Message-ID"] or "")
    if dry_run or os.environ.get("JOB_APPLY_EMAIL_DRY_RUN", "true").lower() in (
        "1",
        "true",
        "yes",
    ):
        # Mock success with synthetic provider id — still evidence for dry UAT only
        provider_id = f"dryrun-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        ev = evidence_from_email(
            provider_message_id=provider_id,
            rfc_message_id=rfc_id,
            recipient=recipient,
            job_id=job_id,
        )
        return EmailApplyResult(
            ok=ev.ok,
            code="dry_run_sent" if ev.ok else "dry_run_ambiguous",
            provider_message_id=provider_id,
            rfc_message_id=rfc_id,
            recipient=recipient,
            content_hash=content_hash,
            message=ev.message,
            dry_run=True,
        )

    host = os.environ.get("JOB_APPLY_SMTP_HOST", "")
    port = int(os.environ.get("JOB_APPLY_SMTP_PORT", "587") or 587)
    user = os.environ.get("JOB_APPLY_SMTP_USER", "")
    password = os.environ.get("JOB_APPLY_SMTP_PASSWORD", "")
    if not host or not user:
        return EmailApplyResult(
            ok=False, code="smtp_not_configured", recipient=recipient, dry_run=False
        )
    try:
        with smtplib.SMTP(host, port, timeout=60) as smtp:
            smtp.starttls()
            smtp.login(user, password)
            resp = smtp.send_message(msg)
        provider_id = str(resp) if resp else f"smtp-{uuid.uuid4().hex[:12]}"
        ev = evidence_from_email(
            provider_message_id=provider_id,
            rfc_message_id=rfc_id,
            recipient=recipient,
            job_id=job_id,
        )
        return EmailApplyResult(
            ok=ev.ok,
            code="sent" if ev.ok else "ambiguous",
            provider_message_id=provider_id,
            rfc_message_id=rfc_id,
            recipient=recipient,
            content_hash=content_hash,
            message=ev.message,
            dry_run=False,
        )
    except Exception as exc:  # noqa: BLE001
        return EmailApplyResult(
            ok=False,
            code="smtp_error",
            recipient=recipient,
            message=str(exc)[:300],
            dry_run=False,
        )
