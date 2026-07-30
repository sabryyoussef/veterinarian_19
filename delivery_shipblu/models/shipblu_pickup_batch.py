# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.delivery_shipblu.services import cutoff_service


class ShipBluPickupBatch(models.Model):
    _name = "shipblu.pickup.batch"
    _description = "ShipBlu Pickup Batch"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(required=True, default="New", copy=False)
    backend_id = fields.Many2one("shipblu.backend", required=True, ondelete="restrict")
    company_id = fields.Many2one(related="backend_id.company_id", store=True, index=True)
    pickup_point_id = fields.Many2one("shipblu.pickup.point", string="Pickup Location")
    shipment_ids = fields.Many2many(
        "shipblu.shipment",
        "shipblu_pickup_batch_shipment_rel",
        "batch_id",
        "shipment_id",
        string="Shipments",
    )
    shipment_count = fields.Integer(compute="_compute_counts", store=True)
    planned_pickup_date = fields.Date(required=True)
    request_status = fields.Selection(
        [
            ("draft", "Draft"),
            ("ready", "Ready"),
            ("submitted", "Submitted"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        tracking=True,
        required=True,
    )
    shipblu_pickup_ref = fields.Char(string="ShipBlu Pickup Reference", copy=False)
    estimated_low_volume_surcharge = fields.Float(compute="_compute_counts", store=True, digits=(16, 2))
    below_minimum = fields.Boolean(compute="_compute_counts", store=True)
    label_readiness = fields.Selection(
        [
            ("unknown", "Unknown"),
            ("incomplete", "Incomplete"),
            ("ready", "Ready"),
        ],
        compute="_compute_readiness",
        store=True,
    )
    qr_readiness = fields.Selection(
        [
            ("unknown", "Unknown"),
            ("incomplete", "Incomplete"),
            ("ready", "Ready"),
            ("not_exposed", "Not exposed by API"),
        ],
        default="not_exposed",
        help="Courier QR scan is only claimed when confirmed via API event or manual action.",
    )
    validation_state = fields.Selection(
        [
            ("ok", "OK"),
            ("warning", "Warning"),
            ("blocked", "Blocked"),
        ],
        compute="_compute_readiness",
        store=True,
    )
    low_volume_confirmed = fields.Boolean(
        string="Confirm low-volume surcharge",
        help="Required before manual submission when below minimum shipment count.",
        tracking=True,
    )
    pickup_warning = fields.Char(compute="_compute_warning")
    notes = fields.Text()

    @api.depends("shipment_ids", "backend_id")
    def _compute_counts(self):
        for rec in self:
            count = len(rec.shipment_ids)
            rec.shipment_count = count
            min_n = int(rec.backend_id.min_shipments_per_pickup or 5) if rec.backend_id else 5
            rec.below_minimum = bool(count and count < min_n)
            rec.estimated_low_volume_surcharge = (
                float(rec.backend_id.low_volume_pickup_surcharge or 0.0) if rec.below_minimum else 0.0
            )

    @api.depends("shipment_ids", "shipment_ids.label_ready", "shipment_ids.ready_for_pickup", "below_minimum")
    def _compute_readiness(self):
        for rec in self:
            if not rec.shipment_ids:
                rec.label_readiness = "unknown"
                rec.validation_state = "warning"
                continue
            if all(s.label_ready for s in rec.shipment_ids):
                rec.label_readiness = "ready"
            else:
                rec.label_readiness = "incomplete"
            if any(not s.ready_for_pickup for s in rec.shipment_ids):
                rec.validation_state = "blocked"
            elif rec.below_minimum:
                rec.validation_state = "warning"
            else:
                rec.validation_state = "ok"

    @api.depends("backend_id", "shipment_count", "planned_pickup_date")
    def _compute_warning(self):
        for rec in self:
            if not rec.backend_id:
                rec.pickup_warning = False
                continue
            rec.pickup_warning = cutoff_service.pickup_warning_text(
                rec.backend_id, shipment_count=rec.shipment_count
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("shipblu.pickup.batch") or "PKB/NEW"
        return super().create(vals_list)

    def action_submit_pickup(self):
        """Manual submission only — never auto. Blocked unless creation/pickup automation gates allow."""
        for rec in self:
            backend = rec.backend_id
            backend.assert_write_allowed("request pickup")
            if not backend.enable_pickup_automation and not self.env.context.get("shipblu_force_pickup"):
                # Manual button still allowed for ops, but never auto-cron
                pass
            if rec.below_minimum and not rec.low_volume_confirmed:
                raise UserError(
                    _(
                        "Pickup %(name)s has %(count)s shipments (minimum %(min)s). "
                        "Confirm the estimated surcharge of %(fee).2f EGP before submitting."
                    )
                    % {
                        "name": rec.name,
                        "count": rec.shipment_count,
                        "min": backend.min_shipments_per_pickup,
                        "fee": rec.estimated_low_volume_surcharge,
                    }
                )
            if rec.validation_state == "blocked":
                raise UserError(_("Batch %(name)s is blocked: shipments not ready for pickup.") % {"name": rec.name})
            # Do not call live API during development unless explicitly forced via context
            if self.env.context.get("shipblu_allow_live_pickup"):
                # Delegate per-shipment pickup via existing shipment action
                for shipment in rec.shipment_ids:
                    if hasattr(shipment, "action_request_pickup"):
                        shipment.action_request_pickup()
                rec.request_status = "submitted"
                rec.message_post(body=_("Pickup submitted to ShipBlu (live)."))
            else:
                raise UserError(
                    _(
                        "Live pickup submission is gated. "
                        "Set context shipblu_allow_live_pickup=True only after explicit approval. "
                        "Batch saved as draft/ready without calling ShipBlu."
                    )
                )
        return True
