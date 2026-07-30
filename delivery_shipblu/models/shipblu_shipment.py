# -*- coding: utf-8 -*-
import base64
import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.delivery_shipblu.services.import_service import ImportService
from odoo.addons.delivery_shipblu.services.shipment_service import ShipmentService
from odoo.addons.delivery_shipblu.services.status_mapping import NORMALIZED, RAW_STATUS_SELECTION
from odoo.addons.petspot_shipblu_base.services.shipblu_client import ShipBluApiError

_logger = logging.getLogger(__name__)


class ShipBluShipment(models.Model):
    _name = "shipblu.shipment"
    _description = "ShipBlu Shipment"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(required=True, copy=False, default="New", tracking=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    backend_id = fields.Many2one("shipblu.backend", required=True, ondelete="restrict")
    picking_id = fields.Many2one(
        "stock.picking",
        required=False,
        ondelete="set null",
        index=True,
        copy=False,
    )
    sale_order_id = fields.Many2one("sale.order", index=True, copy=False)
    carrier_id = fields.Many2one("delivery.carrier", related="picking_id.carrier_id", store=True)

    business_reference = fields.Char(required=True, index=True, copy=False)
    shipblu_order_id = fields.Char(copy=False, index=True, tracking=True)
    tracking_number = fields.Char(string="AWB / Tracking", copy=False, tracking=True, index=True)
    tracking_url = fields.Char(copy=False)
    shopify_order_ref = fields.Char(index=True, copy=False)
    shopify_order_id = fields.Char(index=True, copy=False)

    customer_name = fields.Char()
    customer_phone = fields.Char()
    customer_email = fields.Char()
    address_line_1 = fields.Char()
    address_line_2 = fields.Char()
    zone_id = fields.Integer(string="ShipBlu Zone ID")
    zone_name = fields.Char()
    packages_json = fields.Text()
    package_summary = fields.Char()

    cod_amount = fields.Float(string="COD Amount", digits="Product Price")
    raw_status = fields.Char(copy=False, tracking=True, index=True)
    shipblu_status = fields.Selection(
        RAW_STATUS_SELECTION,
        string="ShipBlu Status",
        index=True,
        copy=False,
    )
    normalized_status = fields.Selection(NORMALIZED, default="created", tracking=True, index=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("creating", "Creating"),
            ("created", "Created"),
            ("tracking", "Tracking"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
            ("error", "Error"),
            ("needs_matching", "Needs Matching"),
            ("manual_review", "Manual Review"),
            ("verification_required", "Verification Required"),
        ],
        default="draft",
        required=True,
        tracking=True,
        index=True,
    )
    needs_matching = fields.Boolean(default=False, index=True)
    match_candidates = fields.Text(help="JSON list of ambiguous match candidates.")
    creation_source = fields.Selection(
        [
            ("shopify", "Shopify"),
            ("odoo", "Odoo"),
            ("portal", "Portal"),
            ("unknown", "Unknown"),
        ],
        default="unknown",
        required=True,
        index=True,
    )
    shipment_owner = fields.Selection(
        [
            ("legacy_shopify", "Legacy Shopify ShipBlu"),
            ("odoo_shipblu", "Odoo ShipBlu"),
            ("manual_external", "Manual / External"),
            ("imported", "Imported"),
        ],
        default="imported",
        required=True,
        tracking=True,
        index=True,
    )
    # Duplicate AWB guard
    canonical_shipment_key = fields.Char(
        string="Canonical Shipment Key",
        index=True,
        copy=False,
        help="Deterministic identity sent as merchant_order_reference.",
    )
    idempotency_key = fields.Char(copy=False, index=True)
    duplicate_guard_status = fields.Selection(
        [
            ("unchecked", "Unchecked"),
            ("checking", "Checking"),
            ("clear", "Clear to create"),
            ("creating", "Creating"),
            ("created", "Created"),
            ("reconciled", "Reconciled existing"),
            ("verification_required", "Verification Required"),
            ("blocked", "Blocked"),
            ("error", "Error"),
        ],
        default="unchecked",
        index=True,
        copy=False,
    )
    duplicate_detection_source = fields.Selection(
        [
            ("local_awb", "Local AWB"),
            ("imported_delivery", "Imported delivery"),
            ("shopify_fulfillment", "Shopify fulfillment"),
            ("remote_reference", "Remote merchant reference"),
            ("remote_awb", "Remote AWB"),
            ("verification_required", "Verification required"),
        ],
        copy=False,
        index=True,
    )
    last_remote_precheck_at = fields.Datetime(copy=False)
    reconciliation_notes = fields.Text(copy=False)
    last_error = fields.Text(copy=False)
    last_sync_at = fields.Datetime()
    last_sync_result = fields.Char()
    last_action_user_id = fields.Many2one("res.users", readonly=True)
    last_action_at = fields.Datetime(readonly=True)
    last_action_name = fields.Char(readonly=True)
    last_action_result = fields.Char(readonly=True)
    payload_snapshot = fields.Text()
    label_attachment_id = fields.Many2one("ir.attachment", copy=False)
    event_ids = fields.One2many("shipblu.shipment.event", "shipment_id", string="Tracking Timeline")

    _shipblu_shipment_order_uniq = models.Constraint(
        "unique(shipblu_order_id)",
        "ShipBlu order id must be unique.",
    )
    _shipblu_shipment_business_ref_uniq = models.Constraint(
        "unique(business_reference)",
        "ShipBlu business reference must be unique.",
    )

    def init(self):
        # Drop legacy unique(picking_id) — imports may have no picking.
        self.env.cr.execute(
            "ALTER TABLE IF EXISTS shipblu_shipment "
            "DROP CONSTRAINT IF EXISTS shipblu_shipment_picking_uniq"
        )
        # Partial uniques for non-empty canonical key / AWB
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS shipblu_shipment_canonical_key_uniq
            ON shipblu_shipment (canonical_shipment_key)
            WHERE canonical_shipment_key IS NOT NULL AND canonical_shipment_key != ''
            """
        )
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS shipblu_shipment_tracking_uniq
            ON shipblu_shipment (tracking_number)
            WHERE tracking_number IS NOT NULL AND tracking_number != ''
            """
        )
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS shipblu_shipment_idempotency_uniq
            ON shipblu_shipment (idempotency_key)
            WHERE idempotency_key IS NOT NULL AND idempotency_key != ''
            """
        )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("shipblu.shipment") or "SB-SHIP"
        return super().create(vals_list)

    def action_refresh_status(self):
        service = ShipmentService(self.env)
        for shipment in self:
            try:
                service.refresh_shipment(shipment)
            except (ShipBluApiError, UserError, ValidationError) as exc:
                shipment.write(
                    {
                        "last_error": str(exc)[:2000],
                        "state": "error",
                        "last_sync_result": "error",
                    }
                )
                raise
        return True

    def action_request_pickup(self):
        for shipment in self:
            shipment.backend_id.assert_write_allowed("request pickup")
            if not shipment.tracking_number:
                raise UserError(_("No tracking number for pickup request."))
            if shipment.raw_status and str(shipment.raw_status).upper() not in (
                "CREATED",
                "PICKUP_RESCHEDULED",
            ):
                raise UserError(
                    _("Pickup only allowed from CREATED/PICKUP_RESCHEDULED. Current: %s")
                    % shipment.raw_status
                )
            client = shipment.backend_id.get_client()
            try:
                client.request_pickup([shipment.tracking_number])
            except ShipBluApiError as exc:
                shipment._record_action("request_pickup", str(exc)[:500])
                raise UserError(str(exc)) from exc
            shipment._record_action("request_pickup", "ok")
            shipment.message_post(body=_("Pickup requested for %s") % shipment.tracking_number)
            shipment.action_refresh_status()
        return True

    def action_download_label(self):
        self.ensure_one()
        if not self.shipblu_order_id:
            raise UserError(_("No ShipBlu order id for label download."))
        client = self.backend_id.get_client()
        try:
            result = client.get_shipping_label(self.shipblu_order_id, label_type="pdf")
        except ShipBluApiError as exc:
            raise UserError(str(exc)) from exc
        if isinstance(result, (bytes, bytearray)):
            data = base64.b64encode(bytes(result)).decode()
            att = self.env["ir.attachment"].create(
                {
                    "name": f"ShipBlu-Label-{self.tracking_number or self.shipblu_order_id}.pdf",
                    "type": "binary",
                    "datas": data,
                    "res_model": self._name,
                    "res_id": self.id,
                    "mimetype": "application/pdf",
                }
            )
            self.label_attachment_id = att.id
            self._record_action("download_label", "ok")
            return {
                "type": "ir.actions.act_url",
                "url": f"/web/content/{att.id}?download=true",
                "target": "new",
            }
        raise UserError(_("Label response was not a PDF. Check API logs."))

    def action_open_sale_order(self):
        self.ensure_one()
        if not self.sale_order_id:
            raise UserError(_("No linked sale order."))
        return {
            "type": "ir.actions.act_window",
            "res_model": "sale.order",
            "res_id": self.sale_order_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_retry_match(self):
        ImportService(self.env).rematch_shipment(self)
        return True

    def _record_action(self, name, result):
        self.write(
            {
                "last_action_user_id": self.env.user.id,
                "last_action_at": fields.Datetime.now(),
                "last_action_name": name,
                "last_action_result": (result or "")[:500],
            }
        )
