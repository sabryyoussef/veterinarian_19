# -*- coding: utf-8 -*-
from odoo import models
from odoo.exceptions import UserError

_MSG = (
    "Legacy WhatsApp bulk marketing is retired. "
    "Customer marketing must use PetSpot WA Marketing Queue "
    "(petspot_wa_marketing_queue) only. "
    "Individual Discuss / single-recipient WhatsApp remains available."
)


class WhatsappBulkWizard(models.TransientModel):
    _inherit = "whatsapp.bulk.wizard"

    def action_send_bulk(self):
        raise UserError(self.env._(_MSG))
