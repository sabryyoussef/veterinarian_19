# -*- coding: utf-8 -*-
"""Concrete job-source adapters."""

from .adzuna import AdzunaAdapter
from .arbeitnow import ArbeitnowAdapter
from .ashby import AshbyAdapter
from .email_alert import EmailAlertAdapter
from .greenhouse import GreenhouseAdapter
from .jooble import JoobleAdapter
from .jsearch import JsearchAdapter
from .lever import LeverAdapter
from .manual import ManualUrlAdapter
from .recruitee import RecruiteeAdapter
from .remoteok import RemoteOkAdapter
from .remotive import RemotiveAdapter
from .restricted import RestrictedSourceAdapter
from .smartrecruiters import SmartRecruitersAdapter
from .workable import WorkableAdapter

__all__ = [
    "AdzunaAdapter",
    "ArbeitnowAdapter",
    "AshbyAdapter",
    "EmailAlertAdapter",
    "GreenhouseAdapter",
    "JoobleAdapter",
    "JsearchAdapter",
    "LeverAdapter",
    "ManualUrlAdapter",
    "RecruiteeAdapter",
    "RemoteOkAdapter",
    "RemotiveAdapter",
    "RestrictedSourceAdapter",
    "SmartRecruitersAdapter",
    "WorkableAdapter",
]
