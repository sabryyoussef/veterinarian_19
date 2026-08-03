"""Adapter package for ATS-like fixtures and gated live draft adapters."""

from app.adapters.base import AdapterResult, BaseApplyAdapter, get_adapter
from app.adapters.bebee_like import BebeeLikeAdapter
from app.adapters.greenhouse_like import GreenhouseLikeAdapter
from app.adapters.odoo_careers import OdooCareersAdapter

__all__ = [
    "AdapterResult",
    "BaseApplyAdapter",
    "get_adapter",
    "BebeeLikeAdapter",
    "GreenhouseLikeAdapter",
    "OdooCareersAdapter",
]
