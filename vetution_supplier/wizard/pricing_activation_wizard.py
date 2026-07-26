# -*- coding: utf-8 -*-
"""System-admin wizard for controlled selling-price activation pilot."""

from odoo import fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.vetution_supplier.models.vetution_pricing import (
    MULTI_PILOT_MAX_TEMPLATES,
    MULTI_PILOT_MAX_VARIANTS,
    PILOT_MAX_TEMPLATES,
)


class VetutionPricingActivationWizard(models.TransientModel):
    _name = "vetution.pricing.activation.wizard"
    _description = "Vetution Pricing Activation Pilot Wizard"

    connection_id = fields.Many2one(
        "vetution.connection",
        required=True,
        default=lambda self: self.env["vetution.connection"].search(
            [("active", "=", True)], limit=1
        ),
    )
    scope = fields.Selection(
        [
            ("single", "Single-variant templates (Phase 3)"),
            ("multi", "Multi-variant Pack Size templates (Phase 4)"),
        ],
        default="single",
        required=True,
    )
    dry_run = fields.Boolean(default=True)
    confirm_write = fields.Boolean(
        string="I confirm writing prices on Test",
        help="Required when dry_run is unchecked.",
    )
    limit = fields.Integer(default=PILOT_MAX_TEMPLATES)
    max_variants = fields.Integer(default=MULTI_PILOT_MAX_VARIANTS)
    template_ids = fields.Many2many(
        "product.template",
        string="Pilot templates (auto-selected if empty)",
    )
    result_message = fields.Text(readonly=True)
    log_count = fields.Integer(readonly=True)

    def _check_admin(self):
        if not self.env.user.has_group("base.group_system"):
            raise AccessError("Only System administrators can activate Vetution prices.")

    def action_select_pilot(self):
        self._check_admin()
        self.ensure_one()
        Pricing = self.env["vetution.pricing"]
        if self.scope == "multi":
            max_t = min(self.limit or MULTI_PILOT_MAX_TEMPLATES, MULTI_PILOT_MAX_TEMPLATES)
            tmpls, used = Pricing.select_multi_pilot_templates(
                self.connection_id, max_templates=max_t,
                max_variants=min(self.max_variants or MULTI_PILOT_MAX_VARIANTS, MULTI_PILOT_MAX_VARIANTS),
            )
            self.template_ids = [(6, 0, tmpls.ids)]
            self.result_message = f"Selected {len(tmpls)} multi-variant templates ({used} variants)."
        else:
            max_t = min(self.limit or PILOT_MAX_TEMPLATES, PILOT_MAX_TEMPLATES)
            tmpls = Pricing.select_pilot_templates(self.connection_id, limit=max_t)
            self.template_ids = [(6, 0, tmpls.ids)]
            self.result_message = f"Selected {len(tmpls)} single-variant templates."
        return self._reopen()

    def action_run(self):
        self._check_admin()
        self.ensure_one()
        if not self.dry_run and not self.confirm_write:
            raise UserError("Confirm writing prices before a non-dry run.")
        Pricing = self.env["vetution.pricing"]
        if self.scope == "multi":
            max_t = min(self.limit or MULTI_PILOT_MAX_TEMPLATES, MULTI_PILOT_MAX_TEMPLATES)
            max_v = min(self.max_variants or MULTI_PILOT_MAX_VARIANTS, MULTI_PILOT_MAX_VARIANTS)
            templates = self.template_ids[:max_t] if self.template_ids else None
            logs = Pricing.activate_multi_pilot(
                self.connection_id, templates=templates, dry_run=self.dry_run,
                max_templates=max_t, max_variants=max_v,
            )
        else:
            limit = min(self.limit or PILOT_MAX_TEMPLATES, PILOT_MAX_TEMPLATES)
            templates = self.template_ids[:limit] if self.template_ids else None
            logs = Pricing.activate_pilot(
                self.connection_id, templates=templates, dry_run=self.dry_run, limit=limit,
            )
        applied = logs.filtered(lambda l: not l.skipped and not l.dry_run)
        dry = logs.filtered(lambda l: not l.skipped and l.dry_run)
        skipped = logs.filtered("skipped")
        placeholders = logs.filtered("placeholder_replacement")
        archived = logs.filtered("variant_archived")
        self.log_count = len(logs)
        self.result_message = (
            f"{'DRY-RUN' if self.dry_run else 'APPLIED'} [{self.scope}]: "
            f"logs={len(logs)} applied_or_previewed={len(applied) + len(dry)} "
            f"skipped={len(skipped)} placeholders={len(placeholders)} archived={len(archived)}"
        )
        return self._reopen()

    def action_open_logs(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Price Change Logs",
            "res_model": "vetution.price.change.log",
            "view_mode": "list,form",
            "domain": [("connection_id", "=", self.connection_id.id)],
        }

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }
