# -*- coding: utf-8 -*-
"""
Migration: 18.0 → 19.0
- error.report model no longer exists
- All data is now stored in crm.lead
- No data can be migrated automatically (different model)
- Old fields are safely dropped by Odoo when the original module is removed
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info("[chatwoot_evolution_error_bridge] Pre-migration 19.0 — no-op")
