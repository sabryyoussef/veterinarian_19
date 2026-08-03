# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class PetspotWaMarketingEvent(models.Model):
    _name = "petspot.wa.marketing.event"
    _description = "WhatsApp Marketing Immutable Event"
    _order = "id desc"
    _rec_name = "event_type"

    event_type = fields.Selection(
        [
            ("approve", "Campaign Approve"),
            ("schedule", "Schedule"),
            ("eligibility", "Eligibility"),
            ("dispatch", "Dispatch"),
            ("dispatch_skip", "Dispatch Skip"),
            ("dispatch_fail", "Dispatch Fail"),
            ("reply", "Reply"),
            ("opt_out", "Opt Out"),
            ("wrong_number", "Wrong Number"),
            ("pause", "Pause"),
            ("unpause", "Unpause"),
            ("campaign_pause", "Campaign Pause"),
            ("campaign_cancel", "Campaign Cancel"),
            ("tier_increase", "Tier Increase"),
            ("health", "Health"),
            ("audience_load", "Audience Load"),
        ],
        required=True,
        index=True,
    )
    campaign_id = fields.Many2one("petspot.wa.marketing.campaign", index=True, ondelete="set null")
    queue_item_id = fields.Many2one("petspot.wa.marketing.queue.item", index=True, ondelete="set null")
    partner_id = fields.Many2one("res.partner", index=True, ondelete="set null")
    mobile_normalized = fields.Char(index=True)
    note = fields.Text()
    payload = fields.Text()
    operator_id = fields.Many2one("res.users", default=lambda self: self.env.user)

    def unlink(self):
        raise UserError(self.env._("Marketing event audit records cannot be deleted."))

    def write(self, vals):
        raise UserError(self.env._("Marketing event audit records are immutable."))
