# -*- coding: utf-8 -*-
import json
from collections import Counter

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

from .audience import SAHEL_TAGGED_CODE
from odoo.addons.petspot_wa_marketing_consent.models.wa_marketing_eligibility import (
    EXCLUDED_TAG_NAMES,
)


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
    audience_id = fields.Many2one(
        "petspot.wa.marketing.audience",
        string="Configured Audience",
        help="Optional reusable audience (e.g. SAHEL_TAGGED_CLIENTS_2020_2026).",
    )
    partner_domain = fields.Char(
        string="Recipient Domain",
        default="[('is_company','=',False),('active','=',True)]",
        help="Odoo domain on res.partner; eligibility still fail-closed. Built from category IDs when loading a tagged audience.",
    )
    preview_count = fields.Integer(readonly=True)
    preview_exclusion_json = fields.Text(readonly=True)
    preview_audit_json = fields.Text(
        string="Preview Audit (JSON)",
        readonly=True,
        help="Detailed exclusion breakdown; never stores full phone numbers.",
    )
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

    def action_load_sahel_tagged_audience(self):
        """Load SAHEL_TAGGED_CLIENTS_2020_2026 domain (category IDs) and preview."""
        self.ensure_one()
        Audience = self.env["petspot.wa.marketing.audience"]
        audience = Audience.get_by_code(SAHEL_TAGGED_CODE)
        result = audience.resolve_tags()
        self.write(
            {
                "audience_id": audience.id,
                "partner_domain": result["domain_str"],
            }
        )
        self.env["petspot.wa.marketing.event"].sudo().create(
            {
                "event_type": "audience_load",
                "campaign_id": self.id,
                "note": "Loaded %s tag_ids=%s" % (SAHEL_TAGGED_CODE, result["tag_ids"]),
                "operator_id": self.env.user.id,
            }
        )
        # Preview even if template not approved yet? Spec wants preview counts — require approved template
        if self.template_id and self.template_id.state == "approved":
            self.action_preview()
        return True

    def _classify_exclusion_bucket(self, reason):
        """Map eligibility reason strings to preview audit buckets."""
        r = reason or "unknown"
        if r == "company_only":
            return "company"
        if r.startswith("excluded_tags:"):
            return "excluded_tag"
        if r in ("invalid_or_missing_eg_mobile",):
            return "invalid_mobile"
        if r.startswith("duplicate_mobile_ambiguous"):
            return "duplicate_normalized_mobile"
        if r in ("no_consent_record", "consent_pending", "consent_pending_review") or r.startswith(
            "consent_status:"
        ) or r == "opt_in_missing_source_or_wording":
            return "no_consent"
        if r == "opted_out":
            return "opted_out"
        if r == "wrong_number":
            return "wrong_number"
        if r == "contacted_within_14_days":
            return "cooldown_14_days"
        if r == "already_queued_or_sent_this_campaign_template":
            return "already_received_campaign"
        if r in ("excluded_internal_or_donotcontact", "employee", "blacklisted", "revoked"):
            return "internal_or_donotcontact"
        return "other:%s" % r

    def _mask_mobile(self, mobile):
        if not mobile:
            return ""
        s = str(mobile)
        if len(s) <= 6:
            return "***"
        return s[:4] + "***" + s[-2:]

    def action_preview(self):
        self.ensure_one()
        if not self.template_id or self.template_id.state != "approved":
            raise UserError(self.env._("Select an approved template first."))
        Eligibility = self.env["petspot.wa.marketing.queue.eligibility"]
        Partner = self.env["res.partner"].sudo()
        domain = safe_eval(self.partner_domain or "[]")

        # Resolve tag IDs from audience if linked (for raw pool audit)
        tag_ids = []
        resolved_tags_audit = []
        rename_warnings = []
        if self.audience_id:
            if self.audience_id.resolved_tags_json:
                resolved_tags_audit = json.loads(self.audience_id.resolved_tags_json)
                tag_ids = [int(r["id"]) for r in resolved_tags_audit]
            if self.audience_id.rename_warnings_json:
                rename_warnings = json.loads(self.audience_id.rename_warnings_json or "[]")

        # Raw unique tagged pool (OR of tags; no company/active filter)
        raw_partners = Partner.browse()
        if tag_ids:
            raw_partners = Partner.with_context(active_test=False).search(
                [("category_id", "in", tag_ids)]
            )
        else:
            # Domain-only preview: approximate raw from domain without active/company if possible
            raw_partners = Partner.with_context(active_test=False).search(domain)

        raw_unique = len(raw_partners)
        company_excl = len(raw_partners.filtered(lambda p: p.is_company))
        inactive_excl = len(raw_partners.filtered(lambda p: not p.active and not p.is_company))
        # Excluded-tag among tagged persons (active or not) — eligibility layer, counted here for audit
        excluded_tag_count = 0
        for p in raw_partners.filtered(lambda x: not x.is_company):
            names = set(p.category_id.mapped("name"))
            if any(n in names for n in EXCLUDED_TAG_NAMES):
                excluded_tag_count += 1

        partners = Partner.search(domain)
        active_person_count = len(partners)

        eligible = []
        reason_counts = Counter()
        bucket_counts = Counter()
        sample_body = ""
        sample_fallback_body = ""

        for partner in partners:
            result = Eligibility.evaluate(
                partner,
                campaign=self,
                template=self.template_id,
                check_pause=False,
                check_instance=False,
            )
            if result.get("eligible"):
                eligible.append(partner.id)
                if not sample_body:
                    sample_body = self.template_id.render_body(partner)
            else:
                reason = result.get("reason") or "unknown"
                reason_counts[reason] += 1
                bucket_counts[self._classify_exclusion_bucket(reason)] += 1

        # Fallback greeting preview (no partner / unreliable name)
        sample_fallback_body = self.template_id.render_body(Partner.browse())

        audit = {
            "audience_code": self.audience_id.code if self.audience_id else None,
            "resolved_tags": resolved_tags_audit,
            "rename_warnings": rename_warnings,
            "partner_domain": self.partner_domain,
            "raw_unique_tagged_pool": raw_unique,
            "active_person_count": active_person_count,
            "company_exclusions": company_excl,
            "inactive_exclusions": inactive_excl,
            "excluded_tag_contacts": excluded_tag_count,
            "exclusion_buckets": dict(bucket_counts),
            "exclusion_reasons": dict(reason_counts),
            "final_eligible_count": len(eligible),
            "phones_in_report": False,
            "queue_created": False,
            "note": "Tags define membership only; not consent. No full phones stored.",
        }

        self.write(
            {
                "preview_count": len(eligible),
                "preview_exclusion_json": json.dumps(dict(reason_counts), ensure_ascii=False, indent=2),
                "preview_audit_json": json.dumps(audit, ensure_ascii=False, indent=2),
                "preview_sample_body": sample_body or sample_fallback_body,
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
