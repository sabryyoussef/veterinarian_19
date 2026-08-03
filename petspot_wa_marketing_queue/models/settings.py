# -*- coding: utf-8 -*-
import pytz
from datetime import datetime, time as dt_time

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

FORBIDDEN_INSTANCES = ("sabry min", "sabrymin", "vodafone")
FORBIDDEN_NUMBERS = ("+201000059085", "201000059085", "01000059085")
REQUIRED_INSTANCE = "petspot-marketing"
OPT_OUT_PHRASE = "لو مش حابب تستقبل رسائل، رد وقف"
TIER_CAPS = {1: 5, 2: 10, 3: 20}
TIER_ACTIVE_DAYS = {1: 7, 2: 7, 3: None}  # None = unlimited at tier 3 until changed
CAIRO = "Africa/Cairo"


class PetspotWaMarketingSettings(models.Model):
    _name = "petspot.wa.marketing.settings"
    _description = "WhatsApp Marketing Queue Settings (singleton)"

    name = fields.Char(default="Marketing Queue Settings", required=True)
    global_pause = fields.Boolean(
        string="Global Marketing Pause",
        default=True,
        help="When ON, no marketing dispatch. Defaults ON after install.",
    )
    evolution_instance = fields.Char(
        string="Evolution Instance",
        default=REQUIRED_INSTANCE,
        required=True,
        readonly=True,
    )
    evolution_base_url = fields.Char(
        string="Evolution Base URL",
        default="http://127.0.0.1:8199",
        help="PetSpot Evolution stack only (:8199). Never master ops.",
    )
    mock_send = fields.Boolean(
        string="Mock Send (UAT)",
        default=True,
        help="When True, dispatcher does not call Evolution; records mock success. Keep True on TEST.",
    )
    tier = fields.Integer(string="Send Tier", default=1)
    tier_active_day_count = fields.Integer(
        string="Active Sending Days on Current Tier",
        default=0,
        help="Increments once per Cairo day with at least one successful send.",
    )
    last_tier_active_cairo_date = fields.Date()
    daily_cairo_date = fields.Date(string="Daily Cap Cairo Date")
    daily_sent_count = fields.Integer(string="Sent Today (Cairo)", default=0)
    daily_reserved_count = fields.Integer(string="Reserved Today (Cairo)", default=0)
    allowlist_test_mobiles = fields.Text(
        string="Internal Test Allowlist (E.164 one per line)",
        help="Only these mobiles may receive real Evolution sends when mock_send is False.",
    )
    window_start_hour = fields.Integer(default=11)
    window_end_hour = fields.Integer(default=19)
    spacing_min_minutes = fields.Integer(default=20)
    spacing_max_minutes = fields.Integer(default=45)
    consecutive_delivery_failures = fields.Integer(default=0)
    rolling_opt_out_count = fields.Integer(default=0)
    rolling_send_count = fields.Integer(default=0)

    @api.model
    def get_settings(self):
        rec = self.search([], limit=1)
        if not rec:
            rec = self.create({"name": "Marketing Queue Settings", "global_pause": True})
        return rec

    @api.constrains("evolution_instance")
    def _check_instance(self):
        for rec in self:
            name = (rec.evolution_instance or "").strip().lower()
            if name != REQUIRED_INSTANCE:
                raise ValidationError(
                    self.env._("Evolution instance must be exactly '%s'.") % REQUIRED_INSTANCE
                )
            if name in FORBIDDEN_INSTANCES or "sabry" in name:
                raise ValidationError(self.env._("Forbidden Evolution instance."))

    def write(self, vals):
        if "evolution_instance" in vals:
            inst = (vals.get("evolution_instance") or "").strip()
            if inst != REQUIRED_INSTANCE:
                raise UserError(self.env._("Cannot set Evolution instance to anything except petspot-marketing."))
        return super().write(vals)

    def cairo_now(self):
        return datetime.now(pytz.timezone(CAIRO))

    def cairo_today(self):
        return self.cairo_now().date()

    def daily_cap(self):
        self.ensure_one()
        return TIER_CAPS.get(self.tier or 1, 5)

    def in_send_window(self, when=None):
        self.ensure_one()
        now = when or self.cairo_now()
        return self.window_start_hour <= now.hour < self.window_end_hour

    def _rollover_daily_counters(self):
        self.ensure_one()
        today = self.cairo_today()
        if self.daily_cairo_date != today:
            self.sudo().write(
                {
                    "daily_cairo_date": today,
                    "daily_sent_count": 0,
                    "daily_reserved_count": 0,
                }
            )

    def reserve_daily_slot(self):
        """Atomic reserve one daily send slot. Returns True if reserved."""
        self.ensure_one()
        # Flush ORM writes so FOR UPDATE sees the same transaction state.
        self.flush_recordset()
        self.env.cr.execute(
            """
            SELECT id, daily_cairo_date, daily_sent_count, daily_reserved_count, tier, global_pause
            FROM petspot_wa_marketing_settings
            WHERE id = %s
            FOR UPDATE
            """,
            (self.id,),
        )
        row = self.env.cr.fetchone()
        if not row:
            return False
        _id, cairo_date, sent, reserved, tier, pause = row
        today = self.cairo_today()
        if cairo_date != today:
            sent, reserved = 0, 0
            cairo_date = today
        if pause:
            return False
        cap = TIER_CAPS.get(tier or 1, 5)
        if (sent or 0) + (reserved or 0) >= cap:
            return False
        reserved = (reserved or 0) + 1
        self.env.cr.execute(
            """
            UPDATE petspot_wa_marketing_settings
            SET daily_cairo_date = %s,
                daily_sent_count = %s,
                daily_reserved_count = %s
            WHERE id = %s
            """,
            (cairo_date, sent or 0, reserved, self.id),
        )
        self.invalidate_recordset()
        return True

    def commit_daily_slot(self):
        """Convert reservation to sent count."""
        self.ensure_one()
        self.flush_recordset()
        self.env.cr.execute(
            """
            SELECT daily_sent_count, daily_reserved_count, daily_cairo_date, tier_active_day_count, last_tier_active_cairo_date
            FROM petspot_wa_marketing_settings WHERE id = %s FOR UPDATE
            """,
            (self.id,),
        )
        sent, reserved, cairo_date, active_days, last_active = self.env.cr.fetchone()
        today = self.cairo_today()
        sent = (sent or 0) + 1
        reserved = max((reserved or 0) - 1, 0)
        if last_active != today:
            active_days = (active_days or 0) + 1
            last_active = today
        self.env.cr.execute(
            """
            UPDATE petspot_wa_marketing_settings
            SET daily_sent_count = %s,
                daily_reserved_count = %s,
                daily_cairo_date = %s,
                tier_active_day_count = %s,
                last_tier_active_cairo_date = %s,
                consecutive_delivery_failures = 0
            WHERE id = %s
            """,
            (sent, reserved, today, active_days, last_active, self.id),
        )
        self.invalidate_recordset()

    def release_daily_slot(self):
        self.ensure_one()
        self.flush_recordset()
        self.env.cr.execute(
            """
            UPDATE petspot_wa_marketing_settings
            SET daily_reserved_count = GREATEST(daily_reserved_count - 1, 0)
            WHERE id = %s
            """,
            (self.id,),
        )
        self.invalidate_recordset()

    def action_set_global_pause(self, paused=True, reason=""):
        self.ensure_one()
        self.global_pause = paused
        self.env["petspot.wa.marketing.event"].sudo().create(
            {
                "event_type": "pause" if paused else "unpause",
                "note": reason or ("Global pause ON" if paused else "Global pause OFF"),
                "operator_id": self.env.user.id,
            }
        )

    def action_approve_tier_increase(self):
        """Sabry-only manual tier bump. Never automatic."""
        self.ensure_one()
        if self.tier >= 3:
            raise UserError(self.env._("Already at maximum tier 3 (20/day)."))
        new_tier = self.tier + 1
        self.write({"tier": new_tier, "tier_active_day_count": 0, "last_tier_active_cairo_date": False})
        self.env["petspot.wa.marketing.event"].sudo().create(
            {
                "event_type": "tier_increase",
                "note": f"Tier manually approved → {new_tier} (cap {TIER_CAPS[new_tier]}/day)",
                "operator_id": self.env.user.id,
            }
        )

    def parse_allowlist(self):
        self.ensure_one()
        lines = (self.allowlist_test_mobiles or "").splitlines()
        return {ln.strip() for ln in lines if ln.strip()}
