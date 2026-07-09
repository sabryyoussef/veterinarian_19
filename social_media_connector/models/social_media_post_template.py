# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SocialMediaPostTemplate(models.Model):
    _name = "social.media.post.template"
    _description = "Social Media Post Template"
    _order = "sequence, name, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        help="Stable identifier, e.g. general_petspot_sahel",
    )
    body = fields.Text(
        required=True,
        help=(
            "Use placeholders from campaign settings: "
            "{location_en}, {location_ar}, {phone_amwaj}, {phone_marassi}, "
            "{whatsapp}, {call_center}, {website}, {website_display}, "
            "{maps_url}, {hashtags}, {facebook_url}, {linkedin_url}"
        ),
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    _code_unique = models.Constraint(
        "UNIQUE(code)",
        "Template code must be unique.",
    )

    @api.model
    def _get_campaign_placeholders(self):
        return self.env["social.media.post"]._get_campaign_contact_config()

    def render_body(self):
        self.ensure_one()
        cfg = self._get_campaign_placeholders()
        try:
            return self.body.format(**cfg)
        except KeyError as exc:
            raise UserError(
                _("Unknown placeholder in template “%s”: %s") % (self.name, exc.args[0])
            ) from exc

    @api.model
    def get_by_code(self, code):
        template = self.search([("code", "=", code), ("active", "=", True)], limit=1)
        if not template:
            raise UserError(_("Post template “%s” was not found.") % code)
        return template

    def action_preview_rendered(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.name,
                "message": self.render_body(),
                "type": "info",
                "sticky": True,
            },
        }
