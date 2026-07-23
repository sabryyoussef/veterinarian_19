# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Backfill OP company classification after upgrade (test-safe, idempotent)."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    try:
        backends = env["openproject.backend"].search([("active", "=", True)])
        if backends:
            n = backends.action_refresh_project_classification()
            _logger.info("openproject_sync 19.0.1.4.0: classified %s maps", n)
    except Exception:
        _logger.exception("openproject_sync classification migration failed")
