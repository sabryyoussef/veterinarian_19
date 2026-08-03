# -*- coding: utf-8 -*-
import json
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval


class PetspotWaMarketingCampaign(models.Model):
    _name = "petspot.wa.marketing.campaign"
    _description = "WhatsApp Marketing Campaign"
    _order = "id desc"
    _inherit = ["mail.thread"]

    name = fields.Char(required=True, tracking=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("approved_scheduled", "Approved & Scheduled"),
            ("sending", "Sending"),
            ("completed", "Completed"),
            ("paused", "Paused"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
        tracking=True,
        index=True,
    )
    template_id = fields.Many2one(
        "petspot.wa.marketing.template",
        required=True,
        domain=[("state", "=", "approved")],
    )
    partner_domain = fields.Char(
        string="Recipient Domain",
        default="[('is_company','=',False),('active','=',True)]",
        help="Odoo domain on res.partner; eligibility still fail-closed.",
    )
    preview_count = fields.Integer(readonly=True)
    preview_exclusion_json = fields.Text(readonly=True)
    preview_sample_body = fields.Text(readonly=True)
    approved_by = fields.Many2one("res.users", readonly=True)
    approved_at = fields.Datetime(readonly=True)
    internal_test_ok = fields.Boolean(
        string="Internal Test Passed",
        help="Required before Approve and Schedule (production rule). On TEST, set after mock test.",
    )
    queue_item_ids = fields.One2many("petspot.wa.marketing.queue.item", "campaign_id")
    queue_count = fields.Integer(compute="_compute_queue_count")

    def _compute_queue_count(self):
        for rec in self:
            rec.queue_count = len(rec.queue_item_ids)

    def action_preview(self):
        self.ensure_one()
        if not self.template_id or self.template_id.state != "approved":
            raise UserError(self.env._("Select an approved template first."))
        Eligibility = self.env["petspot.wa.marketing.queue.eligibility"]
        domain = safe_eval(self.partner_domain or "[]")
        partners = self.env["res.partner"].search(domain)
        eligible = []
        exclusions = {}
        sample_body = ""
        for partner in partners:
            result = Eligibility.evaluate(
                partner, campaign=self, template=self.template_id, check_pause=False, check_instance=False
            )
            if result.get("eligible"):
                eligible.append(partner.id)
                if not sample_body:
                    sample_body = self.template_id.render_body(partner)
            else:
                reason = result.get("reason") or "unknown"
                exclusions.setdefault(reason, 0)
                exclusions[reason] += 1
        self.write(
            {
                "preview_count": len(eligible),
                "preview_exclusion_json": json.dumps(exclusions, ensure_ascii=False, indent=2),
                "preview_sample_body": sample_body,
            }
        )
        return True

    def action_mark_internal_test_ok(self):
        """Record that allowlisted/mock internal test succeeded for this campaign."""
        self.write({"internal_test_ok": True})

    def action_approve_and_schedule(self):
        """Sabry one-shot approval: enqueue all currently eligible recipients."""
        self.ensure_one()
        if self.state != "draft":
            raise UserError(self.env._("Only draft campaigns can be approved."))
        if not self.template_id or self.template_id.state != "approved":
            raise UserError(self.env._("Template must be approved."))
        if not self.internal_test_ok:
            raise UserError(
                self.env._("Run/mark internal test success before Approve and Schedule.")
            )
        # Enqueue even if global pause ON; dispatcher will not send until pause OFF.
        self.action_preview()
        Eligibility = self.env["petspot.wa.marketing.queue.eligibility"]
        Item = self.env["petspot.wa.marketing.queue.item"]
        domain = safe_eval(self.partner_domain or "[]")
        partners = self.env["res.partner"].search(domain)

        # Schedule first item soon; subsequent spacing applied by dispatcher
        base_time = fields.Datetime.now()
        created = 0
        for partner in partners:
            result = Eligibility.evaluate(
                partner,
                campaign=self,
                template=self.template_id,
                check_pause=False,
                check_instance=False,
            )
            self.env["petspot.wa.marketing.event"].sudo().create(
                {
                    "event_type": "eligibility",
                    "campaign_id": self.id,
                    "partner_id": partner.id,
                    "mobile_normalized": result.get("mobile_normalized"),
                    "note": result.get("reason"),
                    "operator_id": self.env.user.id,
                }
            )
            if not result.get("eligible"):
                continue
            mobile = result["mobile_normalized"]
            key = Item.build_idempotency_key(
                self.id, self.template_id.version, partner.id, mobile
            )
            if Item.search_count([("idempotency_key", "=", key)]):
                continue
            body = self.template_id.render_body(partner)
            Item.create(
                {
                    "campaign_id": self.id,
                    "partner_id": partner.id,
                    "mobile_normalized": mobile,
                    "template_id": self.template_id.id,
                    "template_version": self.template_id.version,
                    "idempotency_key": key,
                    "rendered_body": body,
                    "state": "pending",
                    "scheduled_at": base_time,
                }
            )
            created += 1

        self.write(
            {
                "state": "approved_scheduled",
                "approved_by": self.env.user.id,
                "approved_at": fields.Datetime.now(),
            }
        )
        self.env["petspot.wa.marketing.event"].sudo().create(
            {
                "event_type": "approve",
                "campaign_id": self.id,
                "note": f"Approved & scheduled {created} queue items",
                "operator_id": self.env.user.id,
            }
        )
        self.env["petspot.wa.marketing.event"].sudo().create(
            {
                "event_type": "schedule",
                "campaign_id": self.id,
                "note": f"queued={created}",
                "operator_id": self.env.user.id,
            }
        )
        return True

    def action_pause(self):
        self.write({"state": "paused"})
        for rec in self:
            self.env["petspot.wa.marketing.event"].sudo().create(
                {
                    "event_type": "campaign_pause",
                    "campaign_id": rec.id,
                    "operator_id": self.env.user.id,
                }
            )

    def action_cancel(self):
        self.write({"state": "cancelled"})
        pending = self.mapped("queue_item_ids").filtered(
            lambda i: i.state in ("pending", "reserved")
        )
        pending.action_cancel(reason="campaign_cancelled")
        for rec in self:
            self.env["petspot.wa.marketing.event"].sudo().create(
                {
                    "event_type": "campaign_cancel",
                    "campaign_id": rec.id,
                    "operator_id": self.env.user.id,
                }
            )

    def action_resume(self):
        for rec in self:
            if rec.state != "paused":
                continue
            rec.state = "approved_scheduled"
