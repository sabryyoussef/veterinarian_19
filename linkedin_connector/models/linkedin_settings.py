import os

from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    linkedin_jsearch_env_configured = fields.Boolean(
        string="JSearch key loaded from environment",
        compute="_compute_linkedin_jsearch_env_configured",
        readonly=True,
        help=(
            "True when LINKEDIN_JSEARCH_RAPIDAPI_KEY (or JSEARCH_RAPIDAPI_KEY / RAPIDAPI_KEY) "
            "is present in the Odoo process environment. "
            "Install via root-managed systemd EnvironmentFile — never paste into Odoo settings."
        ),
    )
    linkedin_jsearch_env_name = fields.Char(
        string="JSearch env var detected",
        compute="_compute_linkedin_jsearch_env_configured",
        readonly=True,
    )
    # Deprecated writable ICP field kept off the form; cleared on save if empty.
    linkedin_rapidapi_key = fields.Char(
        string="RapidAPI Key (deprecated ICP)",
        config_parameter="linkedin_connector.rapidapi_key",
    )
    linkedin_live_job_search_enabled = fields.Boolean(
        string="Enable live job search (cron)",
        config_parameter="linkedin_connector.live_job_search_enabled",
        help=(
            "When enabled, daily JSearch (search-v2) + internal digest crons may run. "
            "Keep OFF until UAT is approved. Default False."
        ),
    )
    linkedin_auto_create_applications = fields.Boolean(
        string="Auto-create applications above threshold",
        config_parameter="linkedin_connector.auto_create_applications",
        help="Keep OFF for read-only digest mode. Manual Track only.",
    )
    linkedin_job_score_threshold = fields.Char(
        string="Shortlist / digest score threshold",
        config_parameter="linkedin_connector.job_score_threshold",
        default="50",
        help="Minimum score for digest inclusion (default 50). Applications stay manual.",
    )
    linkedin_job_search_queries = fields.Char(
        string="Job search queries (pipe-separated)",
        config_parameter="linkedin_connector.job_search_queries",
        default="Odoo Developer in UAE|Odoo Developer in Egypt|Remote Odoo Developer",
    )
    linkedin_job_search_locations = fields.Char(
        string="Job search locations (pipe-separated)",
        config_parameter="linkedin_connector.job_search_locations",
        default="United Arab Emirates|Egypt|Remote",
    )
    linkedin_job_preferred_geos = fields.Char(
        string="Preferred geo tokens (comma-separated)",
        config_parameter="linkedin_connector.job_preferred_geos",
        default="egypt,cairo,uae,dubai,remote,europe,eu,germany,netherlands,uk",
    )
    linkedin_jsearch_max_requests_per_day = fields.Char(
        string="JSearch max requests / day",
        config_parameter="linkedin_connector.jsearch_max_requests_per_day",
        default="8",
    )
    linkedin_jsearch_max_jobs_per_day = fields.Char(
        string="JSearch max imported jobs / day",
        config_parameter="linkedin_connector.jsearch_max_jobs_per_day",
        default="120",
    )
    linkedin_jsearch_max_requests_per_month = fields.Char(
        string="JSearch max requests / month",
        config_parameter="linkedin_connector.jsearch_max_requests_per_month",
        default="120",
    )

    @api.depends_context("uid")
    def _compute_linkedin_jsearch_env_configured(self):
        detected = ""
        for env_name in (
            "LINKEDIN_JSEARCH_RAPIDAPI_KEY",
            "JSEARCH_RAPIDAPI_KEY",
            "RAPIDAPI_KEY",
        ):
            if (os.environ.get(env_name) or "").strip():
                detected = env_name
                break
        for rec in self:
            rec.linkedin_jsearch_env_configured = bool(detected)
            rec.linkedin_jsearch_env_name = detected or False

    def set_values(self):
        # Never persist a RapidAPI key from the settings form into ICP.
        self.linkedin_rapidapi_key = False
        super().set_values()
        self.env["ir.config_parameter"].sudo().set_param(
            "linkedin_connector.rapidapi_key", ""
        )
