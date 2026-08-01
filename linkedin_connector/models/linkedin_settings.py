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
    linkedin_live_job_search_enabled = fields.Boolean(
        string="Enable live job search (cron)",
        config_parameter="linkedin_connector.live_job_search_enabled",
        help=(
            "When enabled, the daily digest cron calls LinkedIn/RemoteOK/JSearch. "
            "Keep OFF until UAT is approved. Default False."
        ),
    )
    linkedin_job_score_threshold = fields.Char(
        string="Shortlist score threshold",
        config_parameter="linkedin_connector.job_score_threshold",
        default="50",
        help="Minimum score to auto-create a Discovered application (default 50).",
    )
    linkedin_job_search_queries = fields.Char(
        string="Job search queries (pipe-separated)",
        config_parameter="linkedin_connector.job_search_queries",
        default="Senior Odoo Developer|Odoo Developer|Odoo Consultant|Senior Odoo",
    )
    linkedin_job_search_locations = fields.Char(
        string="Job search locations (pipe-separated)",
        config_parameter="linkedin_connector.job_search_locations",
        default="Remote|Egypt|United Arab Emirates",
    )
    linkedin_job_preferred_geos = fields.Char(
        string="Preferred geo tokens (comma-separated)",
        config_parameter="linkedin_connector.job_preferred_geos",
        default="egypt,cairo,uae,dubai,remote,europe,eu,germany,netherlands,uk",
    )
