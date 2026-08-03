"""In-memory attempt store for dry-run sessions."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.models import ApplyAttemptResponse, ApplyState, StopReason


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AttemptStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, ApplyAttemptResponse] = {}

    def create(
        self,
        *,
        metadata: Optional[dict] = None,
        message: Optional[str] = None,
        state: ApplyState = ApplyState.pending,
        stop_reason: StopReason = StopReason.none,
    ) -> ApplyAttemptResponse:
        now = _utcnow()
        attempt = ApplyAttemptResponse(
            attempt_id=str(uuid.uuid4()),
            state=state,
            stop_reason=stop_reason,
            dry_run=True,
            screenshot_paths=[],
            filled_fields=[],
            message=message,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
        with self._lock:
            self._items[attempt.attempt_id] = attempt
        return attempt

    def get(self, attempt_id: str) -> Optional[ApplyAttemptResponse]:
        with self._lock:
            return self._items.get(attempt_id)

    def update(self, attempt_id: str, **kwargs) -> Optional[ApplyAttemptResponse]:
        with self._lock:
            existing = self._items.get(attempt_id)
            if not existing:
                return None
            data = existing.model_dump()
            data.update(kwargs)
            data["updated_at"] = _utcnow()
            updated = ApplyAttemptResponse(**data)
            self._items[attempt_id] = updated
            return updated


store = AttemptStore()
