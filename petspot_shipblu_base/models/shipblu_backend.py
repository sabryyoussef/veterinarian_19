# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.petspot_shipblu_base.services.shipblu_client import ShipBluApiError, ShipBluClient


class ShipBluBackend(models.Model):
    _name = "shipblu.backend"
    _description = "ShipBlu API Backend"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True, default="ShipBlu")
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    active = fields.Boolean(default=True)

    api_key = fields.Char(
        string="API Key",
        copy=False,
        groups="petspot_shipblu_base.group_shipblu_manager",
        help="ShipBlu merchant API key. Header: Authorization: Api-Key <key>",
    )
    environment = fields.Selection(
        [
            ("production", "Production"),
            ("staging", "Staging"),
        ],
        default="production",
        required=True,
        tracking=True,
    )
    api_base = fields.Char(
        string="API Base",
        default="https://api.shipblu.com/api",
        required=True,
        help="Production: https://api.shipblu.com/api — Staging: https://api.staging.shipblu.com/api",
    )
    tracking_url_template = fields.Char(
        string="Tracking URL Template",
        default="https://shipblu.com/tracking/?tracking_number=<shipmenttrackingnumber>",
        help="Use <shipmenttrackingnumber> as placeholder.",
    )
    timeout_seconds = fields.Integer(default=30, required=True)
    max_retries = fields.Integer(default=3, required=True)

    merchant_id = fields.Integer(string="ShipBlu Merchant ID", readonly=True)
    merchant_name = fields.Char(readonly=True)

    default_zone_id = fields.Integer(
        string="Default Drop-off Zone ID",
        default=204,
        help="Pet Spot North Coast / Sahel zone verified as 204.",
        tracking=True,
    )
    default_package_size = fields.Integer(
        string="Default Package Size ID",
        help="Integer package_size from your ShipBlu account. Required before enabling create.",
        tracking=True,
    )
    fallback_line_2 = fields.Char(
        string="Fallback Address Line 2",
        default="EG",
        help="ShipBlu requires line_2; used when partner street2 is empty.",
    )

    shipment_creation_enabled = fields.Boolean(
        string="Enable Odoo Shipment Creation",
        default=False,
        tracking=True,
        help="Master switch for create/update/cancel/return/exchange writes. Keep off until UAT.",
    )
    shipping_owner_mode = fields.Selection(
        [
            ("track_only", "Track Only (import + sync)"),
            ("shopify_owned", "Shopify Owned (import/track, no Odoo create)"),
            ("odoo_owned", "Odoo Owned (Odoo may create)"),
            # legacy aliases kept for existing DB rows
            ("legacy_observation", "Legacy observation (= Shopify Owned)"),
            ("odoo_owner", "Legacy odoo_owner (= Odoo Owned)"),
        ],
        string="Shipping Owner Mode",
        default="track_only",
        required=True,
        tracking=True,
        help="TEST starts in Track Only. Production must stay Track Only / creation disabled.",
    )
    import_page_size = fields.Integer(default=50, required=True)
    last_import_at = fields.Datetime(readonly=True)
    last_import_result = fields.Char(readonly=True)
    last_tracking_sync_at = fields.Datetime(readonly=True)
    last_tracking_sync_result = fields.Char(readonly=True)

    last_connection_ok = fields.Boolean(readonly=True)
    last_connection_at = fields.Datetime(readonly=True)
    last_connection_message = fields.Char(readonly=True)

    def _normalized_owner_mode(self):
        self.ensure_one()
        mode = self.shipping_owner_mode
        if mode in ("legacy_observation", "shopify_owned"):
            return "shopify_owned"
        if mode in ("odoo_owner", "odoo_owned"):
            return "odoo_owned"
        return "track_only"

    def can_create_shipments(self):
        self.ensure_one()
        return bool(
            self.shipment_creation_enabled
            and self._normalized_owner_mode() == "odoo_owned"
            and self.default_package_size
        )

    def assert_write_allowed(self, action_label="write"):
        self.ensure_one()
        if self._normalized_owner_mode() == "track_only":
            raise UserError(
                _("ShipBlu backend is in Track Only mode — %(action)s is blocked.")
                % {"action": action_label}
            )
        if self._normalized_owner_mode() == "shopify_owned" and action_label == "create":
            raise UserError(_("Shopify Owned mode: Odoo cannot create ShipBlu shipments."))
        if action_label == "create" and not self.can_create_shipments():
            raise UserError(
                _(
                    "Odoo ShipBlu create is disabled. Set owner mode to Odoo Owned, "
                    "enable creation, and configure Default Package Size ID."
                )
            )

    _shipblu_backend_company_uniq = models.Constraint(
        "unique(company_id)",
        "Only one ShipBlu backend is allowed per company.",
    )

    @api.constrains("timeout_seconds", "max_retries")
    def _check_limits(self):
        for rec in self:
            if rec.timeout_seconds < 5 or rec.timeout_seconds > 120:
                raise ValidationError(_("Timeout must be between 5 and 120 seconds."))
            if rec.max_retries < 0 or rec.max_retries > 5:
                raise ValidationError(_("Max retries must be between 0 and 5."))

    @api.onchange("environment")
    def _onchange_environment(self):
        for rec in self:
            if rec.environment == "staging":
                rec.api_base = "https://api.staging.shipblu.com/api"
            else:
                rec.api_base = "https://api.shipblu.com/api"

    @api.model
    def _get_for_company(self, company=None):
        company = company or self.env.company
        backend = self.search([("company_id", "=", company.id)], limit=1)
        if not backend:
            raise UserError(_("No ShipBlu backend configured for company %s.") % company.display_name)
        return backend

    def get_client(self):
        self.ensure_one()
        return ShipBluClient(self)

    def action_test_connection(self):
        self.ensure_one()
        client = self.get_client()
        try:
            merchants = client.get_merchants()
            results = merchants.get("results") if isinstance(merchants, dict) else merchants
            merchant = (results or [None])[0] if isinstance(results, list) else None
            govs = client.get_governorates()
            pickups = client.get_pickup_points(limit=10)
            pickup_results = pickups.get("results") if isinstance(pickups, dict) else []
            default_zone_ok = any(
                (p.get("address") or {}).get("zone") == self.default_zone_id for p in (pickup_results or [])
            )
            mid = merchant.get("id") if isinstance(merchant, dict) else False
            mname = merchant.get("name") if isinstance(merchant, dict) else False
            gov_count = len(govs) if isinstance(govs, list) else (govs.get("count") if isinstance(govs, dict) else 0)
            msg = _(
                "OK — merchant %(name)s (#%(id)s), %(govs)s governorates, %(pickups)s pickup points. "
                "Default zone %(zone)s %(status)s."
            ) % {
                "name": mname or "?",
                "id": mid or "?",
                "govs": gov_count,
                "pickups": len(pickup_results or []),
                "zone": self.default_zone_id,
                "status": _("found on pickup") if default_zone_ok else _("not on default pickup"),
            }
            self.write(
                {
                    "merchant_id": mid or 0,
                    "merchant_name": mname or False,
                    "last_connection_ok": True,
                    "last_connection_at": fields.Datetime.now(),
                    "last_connection_message": msg,
                }
            )
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("ShipBlu Connection"),
                    "message": msg,
                    "type": "success" if default_zone_ok else "warning",
                    "sticky": False,
                },
            }
        except (ShipBluApiError, UserError, ValidationError) as exc:
            self.write(
                {
                    "last_connection_ok": False,
                    "last_connection_at": fields.Datetime.now(),
                    "last_connection_message": str(exc)[:500],
                }
            )
            raise UserError(str(exc)) from exc

    def tracking_url_for(self, tracking_number):
        self.ensure_one()
        tpl = self.tracking_url_template or ""
        return tpl.replace("<shipmenttrackingnumber>", str(tracking_number or ""))
