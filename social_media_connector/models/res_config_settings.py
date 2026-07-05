# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .social_media_remote import get_remote_client


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    remote_url = fields.Char(
        string="Remote Odoo URL",
        config_parameter="social_media_connector.remote_url",
        help="Odoo Online base URL without /odoo suffix, e.g. https://deebvet.odoo.com",
    )
    remote_db = fields.Char(
        string="Remote Database",
        config_parameter="social_media_connector.remote_db",
    )
    remote_username = fields.Char(
        string="Remote Username",
        config_parameter="social_media_connector.remote_username",
    )
    remote_api_key = fields.Char(
        string="Remote API Key",
        config_parameter="social_media_connector.remote_api_key",
    )
    campaign_prefix = fields.Char(
        string="Campaign Prefix",
        config_parameter="social_media_connector.campaign_prefix",
        default="[PetSpot FB]",
        help="Prepended to pushed posts for idempotency and identification on remote.",
    )
    auto_push_enabled = fields.Boolean(
        string="Auto-push Ready Posts",
        config_parameter="social_media_connector.auto_push_enabled",
        default=False,
    )
    auto_push_lead_minutes = fields.Integer(
        string="Auto-push Lead (minutes)",
        config_parameter="social_media_connector.auto_push_lead_minutes",
        default=15,
        help="Cron pushes ready scheduled posts this many minutes before scheduled_date.",
    )
    campaign_whatsapp = fields.Char(
        string="Campaign WhatsApp",
        config_parameter="social_media_connector.campaign_whatsapp",
        default="01000059085",
    )
    campaign_call_center = fields.Char(
        string="Campaign Call Center",
        config_parameter="social_media_connector.campaign_call_center",
        default="01201568888",
    )
    campaign_website = fields.Char(
        string="Campaign Website",
        config_parameter="social_media_connector.campaign_website",
        default="https://petspot.odoo.com",
    )
    campaign_facebook_url = fields.Char(
        string="Facebook Page URL",
        config_parameter="social_media_connector.campaign_facebook_url",
        default="https://www.facebook.com/1378190768902001",
    )
    campaign_linkedin_url = fields.Char(
        string="LinkedIn Page URL",
        config_parameter="social_media_connector.campaign_linkedin_url",
        default="https://www.linkedin.com/company/129944345",
    )
    campaign_location_en = fields.Char(
        string="Location (English)",
        config_parameter="social_media_connector.campaign_location_en",
        default="Beside Amwaj 1 gate, Main Road, Sidi Abdel Rahman, North Coast",
    )
    campaign_location_ar = fields.Char(
        string="Location (Arabic)",
        config_parameter="social_media_connector.campaign_location_ar",
        default="بجوار بوابة أمواج 1، الطريق الرئيسي، سيدي عبد الرحمن، الساحل الشمالي",
    )
    campaign_maps_url = fields.Char(
        string="Google Maps URL",
        config_parameter="social_media_connector.campaign_maps_url",
        default="https://maps.app.goo.gl/AaHup6NEFodZEs7S7",
    )
    campaign_schedule_interval = fields.Integer(
        string="Campaign Schedule Interval (minutes)",
        config_parameter="social_media_connector.campaign_schedule_interval",
        default=60,
        help="Minutes between each post when preparing campaign reposts.",
    )
    campaign_schedule_timezone = fields.Char(
        string="Campaign Timezone",
        config_parameter="social_media_connector.campaign_schedule_timezone",
        default="Africa/Cairo",
    )
    campaign_schedule_start_hour = fields.Integer(
        string="Daily Window Start (hour)",
        config_parameter="social_media_connector.campaign_schedule_start_hour",
        default=13,
        help="Local hour when the daily posting window opens (e.g. 13 = 1 PM).",
    )
    campaign_schedule_end_hour = fields.Integer(
        string="Daily Window End (hour, next day)",
        config_parameter="social_media_connector.campaign_schedule_end_hour",
        default=3,
        help="Local hour when the window closes the next calendar day (e.g. 3 = 3 AM).",
    )
    campaign_schedule_start_date = fields.Char(
        string="Campaign Start Date",
        config_parameter="social_media_connector.campaign_schedule_start_date",
        help="First day of the schedule (YYYY-MM-DD, local date). Empty = next 1 PM window.",
    )
    facebook_page_id = fields.Many2one(
        "social.media.page",
        string="Default Facebook Page",
        help="Pre-selected when creating new posts (main page with most followers).",
    )

    @api.model
    def get_values(self):
        res = super().get_values()
        remote_id = int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("social_media_connector.default_remote_account_id", "4")
            or 0
        )
        if remote_id:
            page = self.env["social.media.page"].search(
                [("remote_account_id", "=", remote_id)], limit=1
            )
            res["facebook_page_id"] = page.id
        return res

    def set_values(self):
        super().set_values()
        remote_id = self.facebook_page_id.remote_account_id if self.facebook_page_id else 0
        self.env["ir.config_parameter"].sudo().set_param(
            "social_media_connector.default_remote_account_id", str(remote_id)
        )

    def action_test_remote_connection(self):
        self.ensure_one()
        self._save_remote_params()
        try:
            from .social_media_remote import test_remote_connection

            result = test_remote_connection(self.env)
        except Exception as exc:
            raise UserError(_("Connection failed: %s") % exc) from exc

        mods = result["modules"]
        social_ok = mods.get("social") == "installed"
        fb_ok = mods.get("social_facebook") == "installed"
        detail = (
            f"Connected as uid={result['uid']} on {result['url']} (db={result['db']}).\n"
            f"social: {mods.get('social', '?')}, social_facebook: {mods.get('social_facebook', '?')}.\n"
            f"Facebook pages on remote: {result['page_count']}."
        )
        if not social_ok or not fb_ok:
            raise UserError(
                _("Connected but required modules missing on remote.\n\n%s") % detail
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Connection OK"),
                "message": detail,
                "type": "success",
                "sticky": False,
            },
        }

    def action_fetch_facebook_pages(self):
        self.ensure_one()
        self._save_remote_params()
        try:
            count = self.env["social.media.page"].sync_from_remote()
        except Exception as exc:
            raise UserError(_("Fetch failed: %s") % exc) from exc
        disconnected = self.env["social.media.page"].search_count(
            [("is_disconnected", "=", True), ("active", "=", True)]
        )
        msg = _("Synced %s Facebook page(s) from remote Odoo.") % count
        if disconnected:
            msg += _(
                "\n\nWarning: %s page(s) are disconnected on Odoo Online. "
                "Reconnect Facebook there before pushing posts."
            ) % disconnected
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Pages Synced"),
                "message": msg,
                "type": "warning" if disconnected else "success",
                "sticky": bool(disconnected),
            },
        }

    def action_open_remote_social(self):
        self.ensure_one()
        url = (self.remote_url or "").rstrip("/")
        if not url:
            raise UserError(_("Set Remote Odoo URL first."))
        return {
            "type": "ir.actions.act_url",
            "url": f"{url}/odoo/social",
            "target": "new",
        }

    def action_import_sahel_from_remote(self):
        return self.env["social.media.post"].import_sahel_posts_from_remote()

    def action_import_all_posts(self):
        return self.env["social.media.post"].import_all_posts()

    def action_prepare_campaign_reposts(self):
        return self.env["social.media.post"].prepare_campaign_reposts()

    def action_scrape_facebook_gallery(self):
        return self.env["social.media.post"].scrape_facebook_gallery_to_website()

    def _save_remote_params(self):
        """Persist settings before RPC calls (buttons may run before Save)."""
        ICP = self.env["ir.config_parameter"].sudo()
        for field_name, key in (
            ("remote_url", "social_media_connector.remote_url"),
            ("remote_db", "social_media_connector.remote_db"),
            ("remote_username", "social_media_connector.remote_username"),
            ("remote_api_key", "social_media_connector.remote_api_key"),
            ("campaign_prefix", "social_media_connector.campaign_prefix"),
        ):
            value = getattr(self, field_name) or ""
            ICP.set_param(key, value)
