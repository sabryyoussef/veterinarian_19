# -*- coding: utf-8 -*-
"""Availability inquiry — operator panel, My Work fields, navigation, Mark Done."""

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.petspot_fulfillment_vetution.models import ops_activity as ops


class PetspotAvailabilityInquiry(models.Model):
    _inherit = "petspot.availability.inquiry"

    vetution_assessment_id = fields.Many2one(
        "petspot.vetution.shadow.assessment",
        string="Active Vetution Assessment",
        copy=False,
    )
    vetution_assessment_state = fields.Selection(
        related="vetution_assessment_id.state",
        store=True,
        string="Vetution Assessment State",
    )
    vetution_size_id_resolved = fields.Integer(copy=False)
    vetution_resolution_method = fields.Char(copy=False)
    vetution_assessment_ids = fields.One2many(
        "petspot.vetution.shadow.assessment",
        "inquiry_id",
        string="Assessment History",
    )

    # --- Operator My Work panel (stored by orchestrator) ---
    ops_action_code = fields.Char(index=True, copy=False)
    ops_blocker_code = fields.Char(index=True, copy=False)
    ops_blocker_label = fields.Text(copy=False)
    ops_next_action_label = fields.Char(copy=False)
    ops_owner_id = fields.Many2one("res.users", index=True, copy=False)
    ops_activity_id = fields.Many2one("mail.activity", copy=False)
    ops_due_date = fields.Date(index=True, copy=False)
    ops_category = fields.Char(index=True, copy=False)
    ops_stage = fields.Char(index=True, copy=False)
    ops_environment = fields.Selection(
        [
            ("production_shadow", "Production Shadow"),
            ("production", "Production"),
            ("test_synthetic", "TEST Synthetic"),
        ],
        copy=False,
        index=True,
    )
    ops_priority = fields.Selection(
        [("0", "Normal"), ("1", "High")],
        default="0",
        copy=False,
    )
    ops_overdue = fields.Boolean(compute="_compute_ops_overdue", search="_search_ops_overdue")

    @api.depends("ops_due_date")
    def _compute_ops_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.ops_overdue = bool(rec.ops_due_date and rec.ops_due_date < today and rec.ops_action_code)

    def _search_ops_overdue(self, operator, value):
        today = fields.Date.context_today(self)
        positive = operator in ("=", "==") and value or operator == "!=" and not value
        domain = [
            ("ops_due_date", "!=", False),
            ("ops_due_date", "<", today),
            ("ops_action_code", "!=", False),
        ]
        return domain if positive else ["!"] + domain

    # ------------------------------------------------------------------ assess
    def action_assess_vetution_availability(self):
        Assessment = self.env["petspot.vetution.shadow.assessment"]
        for inquiry in self:
            Assessment.assess_inquiry(inquiry, force_refresh=False)
            inquiry._petspot_ops_sync()
        return self._action_open_assessment() if len(self) == 1 else True

    def action_refresh_and_reassess_vetution(self):
        Assessment = self.env["petspot.vetution.shadow.assessment"]
        for inquiry in self:
            Assessment.assess_inquiry(inquiry, force_refresh=True)
            inquiry._petspot_ops_sync()
        return self._action_open_assessment() if len(self) == 1 else True

    def action_open_vetution_mapping_review(self):
        self.ensure_one()
        review = self.vetution_assessment_id.mapping_review_id
        if not review and self.product_id:
            review = self.env["petspot.vetution.mapping.review"].ensure_pending(
                self.product_id,
                "missing_size_id",
                inquiry=self,
                shopify_variant_id=self.shopify_variant_id,
            )
        if not review:
            raise UserError(_("No mapping review available for this inquiry."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Mapping Review"),
            "res_model": "petspot.vetution.mapping.review",
            "res_id": review.id,
            "view_mode": "form",
            "target": "current",
        }

    def _action_open_assessment(self):
        self.ensure_one()
        assessment = self.vetution_assessment_id
        if not assessment:
            raise UserError(_("Assessment was not created."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Vetution Shadow Assessment"),
            "res_model": "petspot.vetution.shadow.assessment",
            "res_id": assessment.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_source_supplier(self):
        if self.env.context.get("petspot_skip_vetution_bridge"):
            return super().action_source_supplier()
        for inquiry in self:
            self.env["petspot.vetution.shadow.assessment"].assess_inquiry(
                inquiry, force_refresh=False
            )
            inquiry.message_post(
                body=_(
                    "Vetution shadow assessment completed (Phase 15A). "
                    "No quotation, PO, or customer message was created. "
                    "Supplier stock is not reserved."
                )
            )
            if inquiry.state in ("draft", "review_required", "store_check"):
                inquiry.state = "supplier_check"
            inquiry._petspot_ops_sync()
        return True if len(self) > 1 else self._action_open_assessment()

    def _petspot_ops_sync(self):
        Orchestrator = self.env["petspot.vetution.ops.activity"]
        for inquiry in self:
            Orchestrator.sync_inquiry(inquiry)
        return True

    # ------------------------------------------------------------------ Mark Done
    def action_ops_mark_done_and_reassess(self):
        """Complete current managed activity, reassess safely, sync next activity."""
        self.ensure_one()
        if not self.env.user.has_group("petspot_fulfillment.group_fulfillment_user"):
            raise AccessError(_("You need PetSpot Fulfillment User rights."))

        activity = self.ops_activity_id
        if activity and activity.petspot_managed and activity.active:
            if (
                activity.user_id != self.env.user
                and not self.env.user.has_group(
                    "petspot_fulfillment.group_fulfillment_manager"
                )
            ):
                raise AccessError(
                    _("Only the assignee or a Fulfillment Manager can complete this activity.")
                )
            activity.with_context(petspot_ops_skip_sync=True).action_feedback(
                feedback=_("Marked done by %s — reassessing.") % self.env.user.display_name
            )
            self.message_post(
                body=_("Operator marked managed activity done and requested reassessment.")
            )

        try:
            self.env["petspot.vetution.shadow.assessment"].assess_inquiry(
                self, force_refresh=False
            )
        except Exception as err:  # noqa: BLE001
            self.message_post(
                body=_("Reassessment failed: %s. A recovery activity will be ensured.")
                % str(err)[:500]
            )
            # Keep / recreate visible work item
            self.with_context(petspot_ops_skip_sync=False)._petspot_ops_sync()
            raise UserError(
                _("Reassessment failed: %s") % str(err)[:500]
            ) from err

        self._petspot_ops_sync()
        return {
            "type": "ir.actions.act_window",
            "name": _("Availability Inquiry"),
            "res_model": "petspot.availability.inquiry",
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
        }

    # ------------------------------------------------------------------ Navigation (no live side effects)
    def action_ops_open_next(self):
        """Open the exact related record for the current action code."""
        self.ensure_one()
        code = self.ops_action_code
        definition = ops.ACTION_DEFS.get(code) or {}
        nav = definition.get("nav")
        return self._ops_navigate(nav)

    def _ops_navigate(self, nav):
        self.ensure_one()
        Assessment = self.vetution_assessment_id

        if nav == "mapping_review":
            return self.action_open_vetution_mapping_review()
        if nav == "shadow_assessment":
            return self._action_open_assessment()
        if nav == "data_health":
            return self._ops_action_xml("petspot_fulfillment_vetution.action_data_health")
        if nav == "supplier_snapshot":
            return self._ops_action_xml("petspot_fulfillment_vetution.action_supplier_snapshot")
        if nav == "landed_cost_policy":
            policy = Assessment.policy_id if Assessment else False
            if policy:
                return {
                    "type": "ir.actions.act_window",
                    "name": _("Landed Cost Policy"),
                    "res_model": "petspot.vetution.landed.cost.policy",
                    "res_id": policy.id,
                    "view_mode": "form",
                    "target": "current",
                }
            return self._ops_action_xml("petspot_fulfillment_vetution.action_landed_cost_policy")
        if nav == "quotation_ledger":
            ledger = self.env["petspot.vetution.quotation.ledger"].search(
                [("inquiry_id", "=", self.id)], order="id desc", limit=1
            )
            if ledger:
                return {
                    "type": "ir.actions.act_window",
                    "name": _("Quotation Ledger"),
                    "res_model": "petspot.vetution.quotation.ledger",
                    "res_id": ledger.id,
                    "view_mode": "form",
                    "target": "current",
                }
            return self._ops_action_xml("petspot_fulfillment_vetution.action_quotation_ledger")
        if nav == "payment_trust":
            return self._ops_action_xml("petspot_fulfillment_vetution.action_payment_trust")
        if nav == "payment_events":
            return self._ops_action_xml("petspot_fulfillment_vetution.action_payment_event")
        if nav == "supplier_task":
            task = self.env["petspot.vetution.supplier.order.task"].search(
                [("case_id", "=", self.case_id.id)] if self.case_id else [("id", "=", 0)],
                order="id desc",
                limit=1,
            )
            if task:
                return {
                    "type": "ir.actions.act_window",
                    "name": _("Supplier Order Task"),
                    "res_model": "petspot.vetution.supplier.order.task",
                    "res_id": task.id,
                    "view_mode": "form",
                    "target": "current",
                }
            return self._ops_action_xml("petspot_fulfillment_vetution.action_supplier_task")
        if nav == "giza_receipt":
            return self._ops_action_xml("petspot_fulfillment_vetution.action_giza_receipt")
        if nav == "mock_awb":
            return self._ops_action_xml("petspot_fulfillment_vetution.action_mock_awb")
        if nav == "shipblu_backend":
            return self._ops_action_xml("petspot_shipblu_base.action_shipblu_backend")
        if nav == "fulfillment_case" and self.case_id:
            return {
                "type": "ir.actions.act_window",
                "name": _("Fulfillment Case"),
                "res_model": "petspot.fulfillment.case",
                "res_id": self.case_id.id,
                "view_mode": "form",
                "target": "current",
            }
        if nav == "settings":
            return {
                "type": "ir.actions.act_url",
                "url": "/odoo/settings",
                "target": "self",
            }
        raise UserError(_("No navigation target for this action."))

    def _ops_action_xml(self, xml_id):
        action = self.env.ref(xml_id, raise_if_not_found=False)
        if not action:
            raise UserError(_("Action %s is not available.") % xml_id)
        result = action.read()[0]
        result["target"] = "current"
        return result

    # Convenience wrappers for buttons (visibility via attrs/invisible)
    def action_ops_open_mapping(self):
        return self._ops_navigate("mapping_review")

    def action_ops_open_assessment(self):
        return self._ops_navigate("shadow_assessment")

    def action_ops_open_policy(self):
        return self._ops_navigate("landed_cost_policy")

    def action_ops_open_quotation(self):
        return self._ops_navigate("quotation_ledger")

    def action_ops_open_payment(self):
        return self._ops_navigate("payment_trust")

    def action_ops_open_rfq_task(self):
        return self._ops_navigate("supplier_task")

    def action_ops_open_giza(self):
        return self._ops_navigate("giza_receipt")

    def action_ops_open_shipment(self):
        return self._ops_navigate("mock_awb")

    def action_ops_open_case(self):
        return self._ops_navigate("fulfillment_case")

    @api.model
    def cron_repair_ops_activities(self):
        """Low-frequency repair: missing managed activities + duplicate cleanup."""
        return self.cron_petspot_ops_repair_activities()

    @api.model
    def cron_petspot_ops_repair_activities(self):
        """Idempotent repair: sync open inquiries that need a managed activity.

        Does not send quotes, trust payments, create RFQs, publish Shopify,
        create ShipBlu AWBs, or contact customers/suppliers.
        """
        Orchestrator = self.env["petspot.vetution.ops.activity"]
        domain = [
            ("state", "not in", ("fulfilled", "cancelled")),
            ("vetution_assessment_id", "!=", False),
        ]
        inquiries = self.search(domain, limit=200, order="id desc")
        repaired = 0
        for inquiry in inquiries:
            before = inquiry.ops_activity_id
            try:
                Orchestrator.sync_inquiry(inquiry)
            except Exception:  # noqa: BLE001
                continue
            acts = self.env["mail.activity"].sudo().search(
                [
                    ("res_model", "=", "petspot.availability.inquiry"),
                    ("res_id", "=", inquiry.id),
                    ("petspot_managed", "=", True),
                ]
            )
            if len(acts) > 1:
                keep = (
                    acts.filtered(lambda a: a.petspot_action_code == inquiry.ops_action_code)[:1]
                    or acts.sorted("id", reverse=True)[:1]
                )
                Orchestrator._resolve_managed(
                    acts - keep,
                    note=_("Duplicate managed activity removed by repair cron."),
                )
            if inquiry.ops_activity_id and inquiry.ops_activity_id != before:
                repaired += 1
        return repaired
