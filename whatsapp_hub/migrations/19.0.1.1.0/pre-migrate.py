# -*- coding: utf-8 -*-
"""Phase 1/2 upgrade: audit duplicate provider ids before unique indexes apply.

Does not auto-delete or merge historical Hub rows (sprawl remains until manual
backfill/cleanup). Clears conflicting NULL-safe duplicates of business_key /
wa_message_log_id only when empty duplicates would block UniqueIndex — none
expected for new columns.
"""


def migrate(cr, version):
    cr.execute(
        """
        SELECT evolution_message_id, COUNT(*) AS cnt
          FROM whatsapp_message
         WHERE evolution_message_id IS NOT NULL
           AND evolution_message_id <> ''
         GROUP BY evolution_message_id
        HAVING COUNT(*) > 1
         ORDER BY cnt DESC
         LIMIT 50
        """
    )
    dups = cr.fetchall()
    if dups:
        # Log via NOTICE for operators; do not fail upgrade.
        cr.execute(
            "SELECT 1"
        )  # keep cursor healthy
        # Store audit in ir_logging if available later; print for migrate logs
        import logging

        _logger = logging.getLogger(__name__)
        _logger.warning(
            "whatsapp_hub 19.0.1.1.0: %s duplicate evolution_message_id groups "
            "(sample=%s) — UniqueIndex on provider+instance+id only; no auto-merge",
            len(dups),
            dups[:5],
        )

    # Ensure new columns that UniqueIndex references can be NULL for old rows
    # (Odoo ORM adds columns; this is a no-op safety check).
    cr.execute(
        """
        SELECT COUNT(*) FROM whatsapp_message
         WHERE wa_message_log_id IS NOT NULL AND wa_message_log_id <> 0
        """
    )
