# -*- coding: utf-8 -*-
"""
Migration: 18.0 → 19.0
- Removes dependency on error_reporter_16 / error.report model
- No data migration needed (logs/tokens/queue are standalone)
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info("[integration_bridge_core] Pre-migration 19.0: cleaning up legacy references")

    # Remove any ir.model.access entries pointing to error.report that we may have created
    cr.execute("""
        DELETE FROM ir_model_access
        WHERE name ILIKE '%error_report%'
          AND model_id IN (
              SELECT id FROM ir_model WHERE model = 'error.report'
          )
    """)

    _logger.info("[integration_bridge_core] Pre-migration 19.0 complete")
