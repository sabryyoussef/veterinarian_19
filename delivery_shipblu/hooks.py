# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID


def post_init_hook(env):
    """Drop legacy unique(picking_id) if present; picking is optional for imports."""
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
