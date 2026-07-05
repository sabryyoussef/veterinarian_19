# -*- coding: utf-8 -*-
"""
Pre-migration: rename whatsapp.template → evo.wa.template.
Cleans up ir.model.data and ir.model references from the old model name.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    _logger.info("[evo_wa] Pre-migration: cleaning up old whatsapp.template references")

    # Remove ir.model.data records pointing to the old model so they get re-created
    cr.execute("""
        DELETE FROM ir_model_data
        WHERE module = 'evolution_whatsapp_chat'
          AND model = 'whatsapp.template'
    """)
    deleted = cr.rowcount
    _logger.info(f"[evo_wa] Deleted {deleted} ir.model.data rows for old whatsapp.template")

    # Remove ir.model record for old model (if it existed standalone)
    cr.execute("""
        DELETE FROM ir_model WHERE model = 'whatsapp.template'
          AND id NOT IN (
            SELECT DISTINCT res_id FROM ir_model_data
            WHERE model = 'ir.model' AND module != 'evolution_whatsapp_chat'
          )
    """)
    _logger.info(f"[evo_wa] Cleaned ir.model rows: {cr.rowcount}")

    # Drop old table if it exists (only ours, not the enterprise one)
    # We check if the enterprise whatsapp module is installed first
    cr.execute("SELECT 1 FROM ir_module_module WHERE name='whatsapp' AND state='installed'")
    enterprise_wa_installed = cr.fetchone()

    if not enterprise_wa_installed:
        cr.execute("""
            DROP TABLE IF EXISTS whatsapp_template CASCADE
        """)
        _logger.info("[evo_wa] Dropped old whatsapp_template table")
    else:
        _logger.info("[evo_wa] Enterprise whatsapp module present — skipping table drop")
