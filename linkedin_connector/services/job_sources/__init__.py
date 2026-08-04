# -*- coding: utf-8 -*-
"""Job source adapter framework (fetch / normalize / pipeline)."""

from .base import (
    TRI_NO,
    TRI_UNKNOWN,
    TRI_YES,
    AdapterError,
    BaseJobSourceAdapter,
    ComplianceError,
    FetchResult,
    NormalizedJobDict,
    RateLimitError,
    SCORE_CATEGORIES,
    description_fingerprint,
    empty_score_breakdown,
)
from .pipeline import (
    apply_filter_rules,
    compute_description_fingerprint,
    deterministic_dedupe,
    process_normalized_jobs,
    score_normalized_job,
    set_lifecycle,
)
from .registry import ADAPTERS, get_adapter, list_adapter_keys
from .sanitize import sanitize_payload_for_storage
from .ssrf import SSRFError, validate_http_url

__all__ = [
    "ADAPTERS",
    "AdapterError",
    "BaseJobSourceAdapter",
    "ComplianceError",
    "FetchResult",
    "NormalizedJobDict",
    "RateLimitError",
    "SCORE_CATEGORIES",
    "SSRFError",
    "TRI_NO",
    "TRI_UNKNOWN",
    "TRI_YES",
    "apply_filter_rules",
    "compute_description_fingerprint",
    "description_fingerprint",
    "deterministic_dedupe",
    "empty_score_breakdown",
    "get_adapter",
    "list_adapter_keys",
    "process_normalized_jobs",
    "sanitize_payload_for_storage",
    "score_normalized_job",
    "set_lifecycle",
    "validate_http_url",
]
