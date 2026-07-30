# -*- coding: utf-8 -*-
def post_init_hook(env):
    """Drop legacy unique(picking_id) if present; seed reference config."""
    cr = env.cr
    cr.execute(
        """
        SELECT 1 FROM pg_constraint
        WHERE conname = 'shipblu_shipment_picking_uniq'
        """
    )
    if cr.fetchone():
        cr.execute(
            "ALTER TABLE shipblu_shipment DROP CONSTRAINT IF EXISTS shipblu_shipment_picking_uniq"
        )
    backends = env["shipblu.backend"].search([])
    if backends and hasattr(backends, "_ensure_reference_config"):
        backends._ensure_reference_config()
