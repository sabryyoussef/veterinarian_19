# -*- coding: utf-8 -*-
"""Reusable Dev Hub project aliases for WhatsApp / AI candidate matching."""
from __future__ import annotations

import re
import unicodedata

from odoo import api, fields, models
from odoo.exceptions import ValidationError

ALIAS_TYPES = [
    ("canonical", "Canonical"),
    ("customer", "Customer"),
    ("repository", "Repository"),
    ("database", "Database"),
    ("environment", "Environment"),
    ("arabic_name", "Arabic name"),
    ("english_name", "English name"),
    ("abbreviation", "Abbreviation"),
    ("misspelling", "Common misspelling"),
    ("whatsapp_group", "WhatsApp group name"),
]


def normalize_alias(value):
    """Lowercase, strip, collapse spaces, remove diacritics for matching."""
    text = (value or "").strip().lower()
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_ish = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    ascii_ish = re.sub(r"[\s_\-]+", " ", ascii_ish)
    return ascii_ish.strip()


class DevProjectAlias(models.Model):
    _name = "dev.project.alias"
    _description = "Dev Hub Project Alias"
    _order = "priority desc, id"

    name = fields.Char(required=True, index=True)
    normalized_name = fields.Char(
        required=True, index=True, readonly=True, copy=False
    )
    dev_project_id = fields.Many2one(
        "dev.project", required=True, ondelete="cascade", index=True
    )
    alias_type = fields.Selection(ALIAS_TYPES, required=True, default="english_name")
    language = fields.Selection(
        [("en", "English"), ("ar", "Arabic"), ("mixed", "Mixed"), ("any", "Any")],
        default="any",
        required=True,
    )
    active = fields.Boolean(default=True)
    priority = fields.Integer(
        default=10,
        help="Higher priority wins when multiple aliases match.",
    )
    notes = fields.Char()

    _normalized_unique = models.Constraint(
        "unique(normalized_name)",
        "Normalized alias must be unique across projects.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals["normalized_name"] = normalize_alias(vals.get("name"))
            if not vals["normalized_name"]:
                raise ValidationError("Alias name cannot be empty.")
        return super().create(vals_list)

    def write(self, vals):
        if "name" in vals:
            vals = dict(vals)
            vals["normalized_name"] = normalize_alias(vals.get("name"))
            if not vals["normalized_name"]:
                raise ValidationError("Alias name cannot be empty.")
        return super().write(vals)

    @api.model
    def match_text(self, text, limit=10):
        """Return aliases whose normalized name appears in text (exact or token)."""
        hay = normalize_alias(text)
        if not hay:
            return self.browse()
        aliases = self.search([("active", "=", True)], order="priority desc, id")
        hits = self.browse()
        for alias in aliases:
            needle = alias.normalized_name
            if not needle:
                continue
            if needle == hay or needle in hay or hay in needle:
                hits |= alias
            if len(hits) >= limit:
                break
        return hits

    @api.model
    def _seed_default_aliases(self):
        """Idempotent seed of common aliases (Test + shared)."""
        Project = self.env["dev.project"].sudo()
        specs = [
            ("PETSPOT", [
                ("PetSpot", "canonical", "en", 100),
                ("Pet Spot", "english_name", "en", 90),
                ("Petspot Elsahel", "english_name", "en", 85),
                ("petspot", "abbreviation", "en", 80),
                ("فرع الساحل", "arabic_name", "ar", 80),
                ("Pet spot sahel branch", "whatsapp_group", "en", 70),
            ]),
            ("TOURZ", [
                ("Tours Trading", "canonical", "en", 100),
                ("Torz Trading", "misspelling", "en", 95),
                ("Torz", "abbreviation", "en", 90),
                ("Tours", "abbreviation", "en", 85),
                ("Qatar client", "customer", "en", 60),
            ]),
            ("ASTA", [
                ("ASTA Training", "canonical", "en", 100),
                ("ASTA", "abbreviation", "en", 95),
                ("Asta", "english_name", "en", 90),
                ("أستا", "arabic_name", "ar", 95),
                ("Asta development", "whatsapp_group", "en", 80),
                ("انهاء مشروع ASTA", "whatsapp_group", "ar", 80),
            ]),
            ("AZONE", [
                ("WorldPosta / A-Zone Shopify-Odoo", "canonical", "en", 100),
                ("A-Zone", "english_name", "en", 95),
                ("AZone", "abbreviation", "en", 95),
                ("WorldPosta", "customer", "en", 90),
                ("iZone", "english_name", "en", 90),
                ("Izone", "misspelling", "en", 85),
                ("Bright&I zone", "whatsapp_group", "en", 80),
                ("shopify", "repository", "en", 50),
            ]),
            ("CYCLEX", [
                ("Cycle X", "canonical", "en", 100),
                ("CycleX", "abbreviation", "en", 95),
                ("cyclex", "abbreviation", "en", 90),
            ]),
            ("ALSHMOUKH", [
                ("Al Shmoukh", "canonical", "en", 100),
                ("الشموخ", "arabic_name", "ar", 95),
                ("Asasat", "english_name", "en", 80),
            ]),
            ("KAFAAT", [
                ("Kafaat", "canonical", "en", 100),
                ("كفاءات", "arabic_name", "ar", 95),
            ]),
        ]
        Alias = self.sudo()
        for code, rows in specs:
            project = Project.search([("code", "=", code)], limit=1)
            if not project:
                continue
            for name, alias_type, language, priority in rows:
                norm = normalize_alias(name)
                existing = Alias.search([("normalized_name", "=", norm)], limit=1)
                if existing:
                    if existing.dev_project_id != project:
                        continue
                    existing.write(
                        {
                            "name": name,
                            "alias_type": alias_type,
                            "language": language,
                            "priority": priority,
                            "active": True,
                        }
                    )
                else:
                    Alias.create(
                        {
                            "name": name,
                            "dev_project_id": project.id,
                            "alias_type": alias_type,
                            "language": language,
                            "priority": priority,
                        }
                    )
        return True


class DevProject(models.Model):
    _inherit = "dev.project"

    alias_ids = fields.One2many("dev.project.alias", "dev_project_id", string="Aliases")
