# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .odoo_jsonrpc_client import OdooJsonRpcClient


class OdooRemoteConnection(models.Model):
    _name = "odoo.remote.connection"
    _description = "Remote Odoo Connection"
    _order = "sequence, name"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    is_default = fields.Boolean(
        string="Default Connection",
        help="Used by other modules when no specific connection is selected.",
    )
    url = fields.Char(
        string="API Base URL",
        required=True,
        help="JSON-RPC base URL without /odoo suffix, e.g. https://drpaws.ai",
    )
    web_url = fields.Char(
        string="Web URL",
        help="Browser login URL, e.g. https://drpaws.ai/odoo",
    )
    database = fields.Char(required=True)
    username = fields.Char(required=True)
    auth_type = fields.Selection(
        [
            ("api_key", "API Key"),
            ("password", "Password"),
        ],
        default="api_key",
        required=True,
    )
    api_key = fields.Char(groups="base.group_system")
    password = fields.Char(groups="base.group_system")
    notes = fields.Text()
    last_test_date = fields.Datetime(readonly=True)
    last_test_state = fields.Selection(
        [
            ("ok", "OK"),
            ("failed", "Failed"),
        ],
        readonly=True,
    )
    last_test_message = fields.Text(readonly=True)
    remote_uid = fields.Integer(readonly=True)
    remote_user_name = fields.Char(readonly=True)
    remote_company_name = fields.Char(readonly=True)
    color = fields.Integer(default=0)

    @api.constrains("is_default")
    def _check_single_default(self):
        for record in self.filtered("is_default"):
            others = self.search(
                [
                    ("is_default", "=", True),
                    ("id", "!=", record.id),
                ]
            )
            if others:
                raise ValidationError(_("Only one default remote connection is allowed."))

    @api.constrains("url")
    def _check_url(self):
        for record in self:
            url = (record.url or "").strip()
            if not url.startswith(("http://", "https://")):
                raise ValidationError(_("API Base URL must start with http:// or https://."))

    def _get_secret(self) -> str:
        self.ensure_one()
        if self.auth_type == "api_key":
            secret = self.api_key
            if not secret:
                raise UserError(_("API Key is required for connection “%s”.") % self.name)
        else:
            secret = self.password
            if not secret:
                raise UserError(_("Password is required for connection “%s”.") % self.name)
        return secret

    def get_rpc_client(self) -> OdooJsonRpcClient:
        self.ensure_one()
        return OdooJsonRpcClient(
            self.url,
            self.database,
            self.username,
            self._get_secret(),
        )

    @api.model
    def get_default_connection(self):
        connection = self.search(
            [("is_default", "=", True), ("active", "=", True)],
            limit=1,
        )
        if not connection:
            connection = self.search([("active", "=", True)], limit=1)
        return connection

    @api.model
    def get_default_rpc_client(self) -> OdooJsonRpcClient:
        connection = self.get_default_connection()
        if not connection:
            raise UserError(_("No active remote Odoo connection is configured."))
        return connection.get_rpc_client()

    def _update_test_result(self, state: str, message: str, **extra):
        self.write(
            {
                "last_test_date": fields.Datetime.now(),
                "last_test_state": state,
                "last_test_message": message,
                **extra,
            }
        )

    def action_test_connection(self):
        self.ensure_one()
        try:
            client = self.get_rpc_client()
            uid = client.authenticate()
            users = client.search_read(
                "res.users",
                [("id", "=", uid)],
                ["name", "login"],
                limit=1,
            )
            companies = client.search_read("res.company", [], ["name"], limit=1)
            user_name = users[0]["name"] if users else ""
            company_name = companies[0]["name"] if companies else ""
            message = _(
                "Connected as %(user)s (uid %(uid)s) — company: %(company)s",
                user=user_name or self.username,
                uid=uid,
                company=company_name or "—",
            )
            self._update_test_result(
                "ok",
                message,
                remote_uid=uid,
                remote_user_name=user_name,
                remote_company_name=company_name,
            )
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Connection OK"),
                    "message": message,
                    "type": "success",
                    "sticky": False,
                },
            }
        except Exception as exc:
            self._update_test_result(
                "failed",
                str(exc),
                remote_uid=0,
                remote_user_name=False,
                remote_company_name=False,
            )
            raise UserError(_("Connection failed:\n%s") % exc) from exc

    def action_open_web_ui(self):
        self.ensure_one()
        target = (self.web_url or self.url or "").strip()
        if not target:
            raise UserError(_("No web URL configured for this connection."))
        return {
            "type": "ir.actions.act_url",
            "url": target,
            "target": "new",
        }
