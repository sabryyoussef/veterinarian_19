# -*- coding: utf-8 -*-
"""Track OpenProject attachment ids on Odoo ir.attachment rows."""
from odoo import fields, models


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    op_attachment_id = fields.Integer(
        string="OpenProject Attachment ID",
        index=True,
        copy=False,
        help="Source OpenProject attachment id used for idempotent sync.",
    )
    op_attachment_url = fields.Char(
        string="OpenProject Attachment URL",
        copy=False,
        help="Direct OpenProject download/view URL for this attachment.",
    )
