# -*- coding: utf-8 -*-
"""Adapter registry for job sources."""

from __future__ import annotations

import logging
from typing import Any, Optional, Type, Union

from .adapters import (
    AdzunaAdapter,
    ArbeitnowAdapter,
    AshbyAdapter,
    EmailAlertAdapter,
    GreenhouseAdapter,
    JoobleAdapter,
    JsearchAdapter,
    LeverAdapter,
    ManualUrlAdapter,
    RecruiteeAdapter,
    RemoteOkAdapter,
    RemotiveAdapter,
    RestrictedSourceAdapter,
    SmartRecruitersAdapter,
    WorkableAdapter,
)
from .base import AdapterError, BaseJobSourceAdapter

_logger = logging.getLogger(__name__)

ADAPTERS: dict[str, Type[BaseJobSourceAdapter]] = {
    JoobleAdapter.adapter_key: JoobleAdapter,
    AdzunaAdapter.adapter_key: AdzunaAdapter,
    ArbeitnowAdapter.adapter_key: ArbeitnowAdapter,
    RemotiveAdapter.adapter_key: RemotiveAdapter,
    RemoteOkAdapter.adapter_key: RemoteOkAdapter,
    JsearchAdapter.adapter_key: JsearchAdapter,
    GreenhouseAdapter.adapter_key: GreenhouseAdapter,
    LeverAdapter.adapter_key: LeverAdapter,
    AshbyAdapter.adapter_key: AshbyAdapter,
    WorkableAdapter.adapter_key: WorkableAdapter,
    SmartRecruitersAdapter.adapter_key: SmartRecruitersAdapter,
    RecruiteeAdapter.adapter_key: RecruiteeAdapter,
    ManualUrlAdapter.adapter_key: ManualUrlAdapter,
    EmailAlertAdapter.adapter_key: EmailAlertAdapter,
    RestrictedSourceAdapter.adapter_key: RestrictedSourceAdapter,
    # Aliases for restricted boards
    "linkedin": RestrictedSourceAdapter,
    "indeed": RestrictedSourceAdapter,
}


def get_adapter(
    adapter_key: Union[str, Any],
    *,
    env: Any = None,
    connector: Any = None,
    config: Optional[dict] = None,
) -> BaseJobSourceAdapter:
    """Instantiate adapter by key or connector record (``adapter_key`` attribute)."""
    key = adapter_key
    conn = connector
    if not isinstance(adapter_key, str):
        conn = adapter_key
        key = getattr(adapter_key, "adapter_key", None) or getattr(adapter_key, "code", None) or ""
    key = (key or "").strip().lower()
    if not key:
        raise AdapterError("adapter_key_required")
    cls = ADAPTERS.get(key)
    if cls is None:
        raise AdapterError(f"unknown_adapter:{key}")
    return cls(connector=conn, env=env, config=config)


def list_adapter_keys() -> list[str]:
    return sorted({k for k in ADAPTERS if k not in {"linkedin", "indeed"}})
