from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    linkedin_rapidapi_key = fields.Char(
        string="RapidAPI Key",
        config_parameter="linkedin_connector.rapidapi_key",
        help=(
            "API key from rapidapi.com for the JSearch API (free tier: 200 req/month). "
            "Sign up at https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch and subscribe (free). "
            "Copy the X-RapidAPI-Key value here."
        ),
    )
