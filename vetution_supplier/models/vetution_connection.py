# -*- coding: utf-8 -*-
"""Restricted Vetution API connection / credential holder."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

TOKEN_PARAM_KEY = "vetution_supplier.access_token"
TOKEN_ISSUED_PARAM_KEY = "vetution_supplier.token_issued_at"
DEFAULT_BASE_URL = "https://dashboard.vetution.site/api"
DEFAULT_PASSWORD_ENV = "VETUTION_PASSWORD"
TOKEN_PROACTIVE_RENEW_DAYS = 90


def mask_secret(value, keep=4):
    """Return a masked representation safe for logs/UI."""
    if not value:
        return ""
    text = str(value)
    if text.lower().startswith("bearer "):
        text = text[7:]
    # Never show JWT header/payload prefixes in the UI.
    if text.startswith("eyJ") or len(text) > 20:
        return f"*** ({len(text)} chars)"
    if len(text) <= keep * 2:
        return "***"
    return f"{text[:keep]}…{text[-keep:]}"


class VetutionConnection(models.Model):
    _name = "vetution.connection"
    _description = "Vetution Supplier Connection"
    _order = "id"

    name = fields.Char(required=True, default="Vetution")
    active = fields.Boolean(default=True)
    base_url = fields.Char(required=True, default=DEFAULT_BASE_URL)
    phone = fields.Char(
        string="Phone",
        groups="base.group_system",
        help="Accepted Vetution account phone (MSISDN).",
    )
    password_source = fields.Selection(
        [
            ("env", "Environment variable"),
        ],
        default="env",
        required=True,
        groups="base.group_system",
    )
    password_env_key = fields.Char(
        default=DEFAULT_PASSWORD_ENV,
        required=True,
        groups="base.group_system",
    )
    # Token is never written to this Char in DB; stored in ir.config_parameter.
    access_token = fields.Char(
        string="Access Token (masked)",
        compute="_compute_access_token_display",
        groups="base.group_system",
        help="Stored in a restricted system parameter. Display is always masked.",
    )
    token_issued_at = fields.Datetime(groups="base.group_system")
    token_expires_at = fields.Datetime(groups="base.group_system")
    user_id_external = fields.Integer(string="External User Id", groups="base.group_system")
    account_is_accepted = fields.Boolean(groups="base.group_system")
    state = fields.Selection(
        [
            ("disconnected", "Disconnected"),
            ("connected", "Connected"),
            ("authentication_error", "Authentication Error"),
            ("unaccepted", "Unaccepted Account"),
            ("configuration_error", "Configuration Error"),
        ],
        default="disconnected",
        required=True,
    )
    last_auth_check_at = fields.Datetime()
    last_successful_login_at = fields.Datetime()
    last_error = fields.Text()
    commercial_sync_enabled = fields.Boolean(
        default=False,
        help="Master switch for commercial crons (crons themselves stay inactive in Phase 1).",
    )
    commercial_sync_interval = fields.Integer(
        string="Commercial Sync Interval (hours)",
        default=2,
    )
    stale_after_hours = fields.Integer(default=12)
    minimum_expiry_days = fields.Integer(
        default=90,
        help="Offers with exact expiry below this many days are blocked from procurement.",
    )
    near_expiry_days = fields.Integer(default=180)
    low_stock_threshold = fields.Float(
        default=3.0,
        help="Qty at or below this (and > 0) is normalized as limited.",
    )
    supplier_lead_time_days = fields.Integer(default=3)
    supplier_partner_id = fields.Many2one(
        "res.partner",
        string="Vetution Supplier Partner",
        domain="[('supplier_rank', '>', 0)]",
    )
    offer_count = fields.Integer(compute="_compute_offer_count")
    sync_log_count = fields.Integer(compute="_compute_sync_log_count")

    # Pricing engine (Phase 3 activation writes list_price only via controlled pilot)
    default_markup_percent = fields.Float(default=20.0)
    fixed_markup_amount = fields.Float(default=0.0)
    min_gross_margin_percent = fields.Float(default=15.0)
    min_gross_profit_amount = fields.Float(default=50.0)
    price_rounding = fields.Float(default=5.0)
    max_auto_price_change_percent = fields.Float(default=5000.0)
    supplier_cost_review_percent = fields.Float(default=15.0)

    _sql_constraints = [
        (
            "vetution_connection_name_uniq",
            "unique(name)",
            "Connection name must be unique.",
        ),
    ]

    @api.depends()
    def _compute_access_token_display(self):
        for rec in self:
            token = rec._get_stored_token()
            rec.access_token = mask_secret(token) if token else False

    def _compute_offer_count(self):
        Offer = self.env["vetution.supplier.offer"]
        for rec in self:
            rec.offer_count = Offer.search_count([("connection_id", "=", rec.id)])

    def _compute_sync_log_count(self):
        Log = self.env["vetution.sync.log"]
        for rec in self:
            rec.sync_log_count = Log.search_count([("connection_id", "=", rec.id)])

    # ------------------------------------------------------------------ security
    def _check_system_admin(self):
        if not self.env.user.has_group("base.group_system"):
            raise AccessError("Only System administrators can manage Vetution connections.")

    @api.model_create_multi
    def create(self, vals_list):
        self._check_system_admin()
        return super().create(vals_list)

    def write(self, vals):
        self._check_system_admin()
        return super().write(vals)

    def unlink(self):
        self._check_system_admin()
        return super().unlink()

    # ------------------------------------------------------------------ credentials
    def _get_password(self):
        self.ensure_one()
        key = (self.password_env_key or DEFAULT_PASSWORD_ENV).strip()
        password = os.environ.get(key)
        if not password:
            raise UserError(
                f"Password environment variable {key!r} is not set. "
                "Set it on the Odoo service and restart."
            )
        return password

    def _get_stored_token(self):
        self.ensure_one()
        # Prefer connection-scoped param; fall back to global key for single-connection Phase 1.
        ICP = self.env["ir.config_parameter"].sudo()
        scoped = ICP.get_param(f"{TOKEN_PARAM_KEY}.{self.id}")
        if scoped:
            return scoped
        return ICP.get_param(TOKEN_PARAM_KEY) or False

    def _store_token(self, token, issued_at=None, expires_at=None):
        self.ensure_one()
        self._check_system_admin()
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param(f"{TOKEN_PARAM_KEY}.{self.id}", token or "")
        ICP.set_param(TOKEN_PARAM_KEY, token or "")
        issued = issued_at or fields.Datetime.now()
        ICP.set_param(
            f"{TOKEN_ISSUED_PARAM_KEY}.{self.id}",
            fields.Datetime.to_string(issued) if issued else "",
        )
        vals = {
            "token_issued_at": issued,
            "token_expires_at": expires_at or False,
            "last_successful_login_at": fields.Datetime.now(),
            "state": "connected",
            "last_error": False,
        }
        # write without re-entering credential checks for token fields already gated
        super(VetutionConnection, self).write(vals)

    def _clear_token(self):
        self.ensure_one()
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_param(f"{TOKEN_PARAM_KEY}.{self.id}", "")
        ICP.set_param(TOKEN_PARAM_KEY, "")
        super(VetutionConnection, self).write(
            {
                "token_issued_at": False,
                "token_expires_at": False,
                "state": "disconnected",
            }
        )

    def _token_needs_proactive_renewal(self):
        self.ensure_one()
        issued = self.token_issued_at
        if not issued:
            return True
        age = fields.Datetime.now() - issued
        return age >= timedelta(days=TOKEN_PROACTIVE_RENEW_DAYS)

    def action_open_offers(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Supplier Offers",
            "res_model": "vetution.supplier.offer",
            "view_mode": "list,form",
            "domain": [("connection_id", "=", self.id)],
        }

    def action_open_sync_logs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Sync Logs",
            "res_model": "vetution.sync.log",
            "view_mode": "list,form",
            "domain": [("connection_id", "=", self.id)],
        }

    def action_test_connection(self):
        self.ensure_one()
        sync = self.env["vetution.commercial.sync"]
        sync.with_context(vetution_connection_id=self.id).assert_authentication(self)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Vetution",
                "message": "Authentication assertion passed.",
                "type": "success",
                "sticky": False,
            },
        }

    def action_login_refresh_token(self):
        self.ensure_one()
        self.env["vetution.commercial.sync"].login(self, force=True)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Vetution",
                "message": "Token refreshed.",
                "type": "success",
                "sticky": False,
            },
        }

    @api.model
    def get_default_connection(self):
        conn = self.search([("active", "=", True)], limit=1, order="id")
        if not conn:
            raise UserError("No active Vetution connection configured.")
        return conn

    def preview_sale_price(self, effective_cost):
        """Compute candidate selling price from supplier cost (Phase 3 formula).

        Does not write list_price by itself — activation methods do that.
        Formula:
          markup_price = cost × (1 + markup%/100) + fixed
          minimum_margin_price = cost / (1 - margin%/100)   # when margin% < 100
          minimum_profit_price = cost + min_profit
          candidate = max(...)
          selling_price = round_up(candidate, rounding)
        """
        self.ensure_one()
        return self.compute_sale_price(effective_cost)["selling_price"]

    def compute_sale_price(self, effective_cost):
        """Return a breakdown dict for audit / activation."""
        self.ensure_one()
        import math

        cost = float(effective_cost or 0.0)
        result = {
            "supplier_cost": cost,
            "markup_price": 0.0,
            "minimum_margin_price": 0.0,
            "minimum_profit_price": 0.0,
            "candidate": 0.0,
            "selling_price": 0.0,
            "markup_percent": self.default_markup_percent or 0.0,
            "min_margin_percent": self.min_gross_margin_percent or 0.0,
            "min_profit_amount": self.min_gross_profit_amount or 0.0,
            "rounding": self.price_rounding or 1.0,
        }
        if cost <= 0:
            return result
        markup = result["markup_percent"]
        fixed = self.fixed_markup_amount or 0.0
        markup_price = cost * (1.0 + markup / 100.0) + fixed
        min_margin = result["min_margin_percent"]
        if min_margin >= 100:
            margin_price = cost
        else:
            margin_price = cost / (1.0 - min_margin / 100.0)
        profit_price = cost + (result["min_profit_amount"] or 0.0)
        candidate = max(markup_price, margin_price, profit_price)
        rounding = result["rounding"] or 1.0
        if rounding > 0:
            selling = math.ceil(candidate / rounding - 1e-9) * rounding
        else:
            selling = candidate
        result.update(
            {
                "markup_price": markup_price,
                "minimum_margin_price": margin_price,
                "minimum_profit_price": profit_price,
                "candidate": candidate,
                "selling_price": selling,
            }
        )
        return result
