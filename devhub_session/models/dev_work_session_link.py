# -*- coding: utf-8 -*-
from odoo import fields, models


class DevWorkItemSession(models.Model):
    _inherit = "dev.work.item"

    session_ids = fields.One2many("dev.session", "work_item_id")
