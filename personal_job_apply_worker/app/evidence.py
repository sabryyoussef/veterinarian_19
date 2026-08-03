# -*- coding: utf-8 -*-
"""Confirmation / evidence detection for fail-closed applied transitions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse

_THANK_YOU_RE = re.compile(
    r"thank\s*you|application\s+(received|submitted|successful)|"
    r"we\s+have\s+received\s+your\s+application|successfully\s+applied|"
    r"confirmation\s*(number|id|code)|application\s*#?\s*\d+",
    re.I,
)
_REF_RE = re.compile(
    r"(?:application|reference|confirmation|ticket)\s*(?:id|number|#|no\.?)?\s*[:#]?\s*([A-Z0-9\-_]{5,})",
    re.I,
)


@dataclass
class EvidenceResult:
    ok: bool
    kind: str
    confirmation_url: str = ""
    confirmation_reference: str = ""
    message: str = ""
    ambiguous: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "kind": self.kind,
            "confirmation_url": self.confirmation_url,
            "confirmation_reference": self.confirmation_reference,
            "message": self.message,
            "ambiguous": self.ambiguous,
        }


def evidence_from_page(*, url: str, text: str, html: str = "") -> EvidenceResult:
    """Classify post-submit page evidence. Fail closed on ambiguity."""
    blob = f"{text or ''}\n{html or ''}"
    url = url or ""
    path = (urlparse(url).path or "").lower()
    thank = bool(_THANK_YOU_RE.search(blob) or _THANK_YOU_RE.search(path))
    ref_m = _REF_RE.search(blob)
    ref = ref_m.group(1) if ref_m else ""

    if thank and (ref or "thank" in path or "success" in path or "confirm" in path):
        return EvidenceResult(
            ok=True,
            kind="browser_success_page",
            confirmation_url=url,
            confirmation_reference=ref,
            message="strong_browser_evidence",
        )
    if thank:
        # Thank-you text without path/ref — still accept as strong signal per approval
        return EvidenceResult(
            ok=True,
            kind="browser_thank_you_text",
            confirmation_url=url,
            confirmation_reference=ref,
            message="thank_you_text",
        )
    if ref and ("success" in path or "confirm" in path or "complete" in path):
        return EvidenceResult(
            ok=True,
            kind="browser_reference_url",
            confirmation_url=url,
            confirmation_reference=ref,
            message="reference_on_success_url",
        )
    # Clicked submit but no clear confirmation
    return EvidenceResult(
        ok=False,
        kind="ambiguous",
        confirmation_url=url,
        confirmation_reference=ref,
        message="no_strong_confirmation",
        ambiguous=True,
    )


def evidence_from_email(
    *,
    provider_message_id: str,
    rfc_message_id: str,
    recipient: str,
    job_id: Optional[int] = None,
    send_error: str = "",
) -> EvidenceResult:
    if send_error:
        return EvidenceResult(
            ok=False,
            kind="email_send_error",
            message=send_error[:300],
            ambiguous=False,
        )
    if not provider_message_id and not rfc_message_id:
        return EvidenceResult(
            ok=False,
            kind="ambiguous",
            message="missing_message_ids",
            ambiguous=True,
        )
    if not recipient or "@" not in recipient:
        return EvidenceResult(
            ok=False,
            kind="ambiguous",
            message="invalid_recipient",
            ambiguous=True,
        )
    return EvidenceResult(
        ok=True,
        kind="email_sent",
        confirmation_reference=rfc_message_id or provider_message_id,
        message=f"email_ok:{recipient}:job={job_id or ''}",
    )
