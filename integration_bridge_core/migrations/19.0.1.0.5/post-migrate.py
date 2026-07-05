# -*- coding: utf-8 -*-

def migrate(cr, version):
    # Only rewrite the previous packaged default so other environments keep their URL.
    cr.execute(
        """
        UPDATE ir_config_parameter
        SET value = %s
        WHERE key = 'integration_bridge.evolution_web_url'
          AND value = 'https://evo.freezonermirror.online'
        """,
        ("http://127.0.0.1:8099/manager",),
    )
