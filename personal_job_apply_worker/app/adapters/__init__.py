"""Adapter package for ATS-like fixtures and gated live draft adapters."""

from app.adapters.ashby_like import AshbyLikeAdapter
from app.adapters.base import AdapterResult, BaseApplyAdapter, get_adapter
from app.adapters.bebee_like import BebeeLikeAdapter
from app.adapters.greenhouse_like import GreenhouseLikeAdapter
from app.adapters.lever_like import LeverLikeAdapter
from app.adapters.odoo_careers import OdooCareersAdapter
from app.adapters.workable_like import WorkableLikeAdapter

__all__ = [
    "AdapterResult",
    "BaseApplyAdapter",
    "get_adapter",
    "AshbyLikeAdapter",
    "BebeeLikeAdapter",
    "GreenhouseLikeAdapter",
    "LeverLikeAdapter",
    "OdooCareersAdapter",
    "WorkableLikeAdapter",
]
