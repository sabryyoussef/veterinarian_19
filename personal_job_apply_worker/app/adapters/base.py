"""Base adapter interface for dry-run form filling."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from app.models import ApplicantFixture, StopReason


@dataclass
class AdapterResult:
    filled_fields: list[str] = field(default_factory=list)
    stop_reason: Optional[StopReason] = None
    message: Optional[str] = None
    adapter_name: str = "base"


class BaseApplyAdapter(ABC):
    name: str = "base"

    @abstractmethod
    async def can_handle(self, page) -> bool:
        """Return True if this adapter recognizes the current page."""

    @abstractmethod
    async def fill_draft(self, page, applicant: ApplicantFixture, cv_path: str) -> AdapterResult:
        """Fill form fields only. Never click a real submit control."""


def get_adapter(hint: Optional[str] = None) -> list[BaseApplyAdapter]:
    """Return adapters in try-order. Hint narrows to a single adapter when known."""
    from app.adapters.ashby_like import AshbyLikeAdapter
    from app.adapters.bebee_like import BebeeLikeAdapter
    from app.adapters.greenhouse_like import GreenhouseLikeAdapter
    from app.adapters.lever_like import LeverLikeAdapter
    from app.adapters.odoo_careers import OdooCareersAdapter
    from app.adapters.workable_like import WorkableLikeAdapter

    all_adapters: list[BaseApplyAdapter] = [
        OdooCareersAdapter(),
        GreenhouseLikeAdapter(),
        LeverLikeAdapter(),
        WorkableLikeAdapter(),
        AshbyLikeAdapter(),
        BebeeLikeAdapter(),
    ]
    if not hint or hint == "auto":
        return all_adapters
    for adapter in all_adapters:
        if adapter.name == hint:
            return [adapter]
    return all_adapters
