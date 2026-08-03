# -*- coding: utf-8 -*-
"""Reusable configured marketing audiences (tag-based; never consent)."""
import json

from odoo import api, fields, models
from odoo.exceptions import UserError

SAHEL_TAGGED_CODE = "SAHEL_TAGGED_CLIENTS_2020_2026"
SAHEL_REQUIRED_TAG_NAMES = (
    "Sahel Client",
    "Sahel 2020",
    "Sahel 2021",
    "Sahel 2022",
    "Sahel 2023",
    "Sahel 2024",
    "Sahel 2025",
    "Sahel 2026",
)


class PetspotWaMarketingAudience(models.Model):
    _name = "petspot.wa.marketing.audience"
    _description = "WhatsApp Marketing Configured Audience"
    _order = "code"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    required_tag_names_json = fields.Text(
        string="Required Tag Names (JSON)",
        required=True,
        help="Exact res.partner.category names that must resolve 1:1. Not used as domain values.",
    )
    resolved_tags_json = fields.Text(
        string="Resolved Tags Audit (JSON)",
        readonly=True,
        help="[{id, expected_name, current_name}, ...] after last successful resolve.",
    )
    rename_warnings_json = fields.Text(string="Rename Warnings (JSON)", readonly=True)
    partner_domain = fields.Char(
        string="Partner Domain",
        readonly=True,
        help="Built from resolved category IDs only.",
    )
    resolved_at = fields.Datetime(readonly=True)
    resolve_error = fields.Text(readonly=True)

    _sql_constraints = [
        ("code_uniq", "unique(code)", "Audience code must be unique."),
    ]

    @api.model
    def get_by_code(self, code):
        rec = self.search([("code", "=", code), ("active", "=", True)], limit=1)
        if not rec:
            raise UserError(self.env._("Configured audience not found: %s") % code)
        return rec

    def _required_names(self):
        self.ensure_one()
        try:
            names = json.loads(self.required_tag_names_json or "[]")
        except json.JSONDecodeError as exc:
            raise UserError(self.env._("Invalid required_tag_names_json: %s") % exc) from exc
        if not isinstance(names, list) or not names:
            raise UserError(self.env._("required_tag_names_json must be a non-empty JSON list."))
        return [str(n).strip() for n in names]

    def _category_display_name(self, category):
        """Stable English-ish display for audit (fail closed if empty)."""
        name = category.with_context(lang="en_US").name or category.name or ""
        return str(name).strip()

    def resolve_tags(self):
        """Resolve exact category records by name. Fail closed on missing/ambiguous.

        Does not create tags. Domain uses category IDs only.
        """
        self.ensure_one()
        Category = self.env["res.partner.category"].sudo()
        required = self._required_names()
        missing = []
        ambiguous = []
        resolved = []
        rename_warnings = []

        # Prefer previously stored IDs when present: detect renames, still require all names.
        prior = []
        if self.resolved_tags_json:
            try:
                prior = json.loads(self.resolved_tags_json)
            except json.JSONDecodeError:
                prior = []
        prior_by_expected = {
            (p.get("expected_name") or ""): p for p in prior if isinstance(p, dict)
        }

        for expected in required:
            cats = Category.search([("name", "=", expected)])
            # Deduplicate by id if search returns duplicates
            cats = cats.exists()
            if len(cats) == 0 and expected in prior_by_expected:
                # ID still present but renamed away from expected name
                pid = prior_by_expected[expected].get("id")
                cat = Category.browse(pid) if pid else Category.browse()
                if cat.exists():
                    current = self._category_display_name(cat)
                    rename_warnings.append(
                        {
                            "id": cat.id,
                            "expected_name": expected,
                            "current_name": current,
                        }
                    )
                    # Fail closed: required exact name not found
                    missing.append(expected)
                    continue
            if len(cats) == 0:
                missing.append(expected)
                continue
            if len(cats) > 1:
                ambiguous.append(
                    {
                        "name": expected,
                        "ids": cats.ids,
                        "current_names": [self._category_display_name(c) for c in cats],
                    }
                )
                continue
            cat = cats[0]
            current = self._category_display_name(cat)
            if current != expected:
                rename_warnings.append(
                    {
                        "id": cat.id,
                        "expected_name": expected,
                        "current_name": current,
                    }
                )
                # Exact-name search matched a translation variant; still bind ID but warn.
            resolved.append(
                {
                    "id": cat.id,
                    "expected_name": expected,
                    "current_name": current,
                }
            )

        if missing or ambiguous:
            err = {
                "missing": missing,
                "ambiguous": ambiguous,
                "rename_warnings": rename_warnings,
            }
            self.write(
                {
                    "resolve_error": json.dumps(err, ensure_ascii=False, indent=2),
                    "partner_domain": False,
                    "rename_warnings_json": json.dumps(rename_warnings, ensure_ascii=False, indent=2)
                    if rename_warnings
                    else False,
                }
            )
            parts = []
            if missing:
                parts.append("missing tags: %s" % ", ".join(missing))
            if ambiguous:
                parts.append(
                    "ambiguous tags: %s"
                    % ", ".join("%s→%s" % (a["name"], a["ids"]) for a in ambiguous)
                )
            raise UserError(
                self.env._(
                    "Audience %s fail-closed tag resolve: %s. Do not create tags automatically."
                )
                % (self.code, "; ".join(parts))
            )

        tag_ids = [r["id"] for r in resolved]
        # Deduplicate IDs while preserving order
        seen = set()
        unique_ids = []
        for tid in tag_ids:
            if tid not in seen:
                seen.add(tid)
                unique_ids.append(tid)

        domain = [
            ("is_company", "=", False),
            ("active", "=", True),
            ("category_id", "in", unique_ids),
        ]
        domain_str = repr(domain)
        self.write(
            {
                "resolved_tags_json": json.dumps(resolved, ensure_ascii=False, indent=2),
                "rename_warnings_json": json.dumps(rename_warnings, ensure_ascii=False, indent=2)
                if rename_warnings
                else "[]",
                "partner_domain": domain_str,
                "resolved_at": fields.Datetime.now(),
                "resolve_error": False,
            }
        )
        return {
            "resolved": resolved,
            "tag_ids": unique_ids,
            "domain": domain,
            "domain_str": domain_str,
            "rename_warnings": rename_warnings,
        }

    def action_resolve(self):
        for rec in self:
            rec.resolve_tags()
        return True

    def get_resolved_tag_ids(self):
        self.ensure_one()
        if not self.resolved_tags_json or not self.partner_domain:
            self.resolve_tags()
        data = json.loads(self.resolved_tags_json or "[]")
        return [int(r["id"]) for r in data]
