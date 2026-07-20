# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Idempotent classification backfill after install/upgrade."""
    try:
        backends = env["openproject.backend"].search([("active", "=", True)])
        if backends:
            n = backends.action_refresh_project_classification()
            _logger.info("openproject_sync post_init: classified %s maps", n)
    except Exception:
        _logger.exception("openproject_sync post_init classification backfill failed")
