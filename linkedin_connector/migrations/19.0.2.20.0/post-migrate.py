# -*- coding: utf-8 -*-
"""Additive migration for job-source expansion (19.0.2.20.0).

Column creation is handled by the ORM on module upgrade. This script only
records a marker and ensures live_submit stays disabled.
"""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE ir_config_parameter
           SET value = 'False'
         WHERE key = 'linkedin_connector.live_submit_enabled'
           AND COALESCE(value, '') NOT IN ('False', 'false', '0')
        """
    )
    # Intentionally do not enable discovery or connectors here.
