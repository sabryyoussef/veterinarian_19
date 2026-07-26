# -*- coding: utf-8 -*-
"""Shared git identity validators used by execution and provider modules."""
import re

SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
BRANCH_RE = re.compile(
    r"^devhub/DW-[0-9]+-[a-z0-9](?:[a-z0-9-]{0,70}[a-z0-9])?$"
)
