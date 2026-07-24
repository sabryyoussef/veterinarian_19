# -*- coding: utf-8 -*-
"""Whitelisted WhatsApp development sources (group JID → Dev Hub routing)."""
from __future__ import annotations

import json
import logging
import os
import re

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

GROUP_JID_RE = re.compile(r"^\d{10,25}@g\.us$")
SENDER_JID_RE = re.compile(r"^[0-9]+@(s\.whatsapp\.net|lid)$")
# Canonical managed work groups (mirrors /home/sabry/nextcloud/group-project-map.json)
KNOWN_WHITELIST = (
    ("120363408076611149@g.us", "Torz Trading - Qatar"),
    ("120363408418840478@g.us", "انهاء مشروع ASTA"),
    ("120363408457090778@g.us", "Bright&I zone (Odoo ERP)"),
    ("120363409667117343@g.us", "Izone - Internal BIS"),
    ("120363409479957889@g.us", "Alzaeem Medical project - internal BIS"),
    ("120363411424964076@g.us", "Testopenclow"),
    ("120363422104853335@g.us", "Dev Needed"),
    ("120363404024033208@g.us", "Cycle X"),
    ("120363427125783045@g.us", "AZone - WorldPosta"),
    ("120363428056737368@g.us", "Asta development"),
    ("120363409395291215@g.us", "Pet spot sahel branch"),
    ("120363427581631722@g.us", "مهمات مفتوحة لاستكمال فرع الساحل petspot"),
)
GROUP_MAP_PATHS = (
    "/home/sabry/nextcloud/group-project-map.json",
    os.path.expanduser("~/nextcloud/group-project-map.json"),
)

CLINIC_OBSERVE_JIDS = frozenset(
    {
        "120363409395291215@g.us",
        "120363427581631722@g.us",
    }
)


class DevWhatsappSource(models.Model):
    _name = "dev.whatsapp.source"
    _description = "Dev Hub WhatsApp Source"
    _order = "name"

    name = fields.Char(required=True)
    group_jid = fields.Char(
        required=True,
        index=True,
        help="Stable WhatsApp group JID (…@g.us). Display names are not used for whitelist.",
    )
    active = fields.Boolean(default=True)
    evolution_instance_ref = fields.Char()
    chatwoot_inbox_id = fields.Integer(default=2)
    chatwoot_label = fields.Char()
    chatwoot_conversation_id = fields.Integer(
        help="Optional known Chatwoot conversation id for this group thread."
    )
    hub_group_id = fields.Many2one("whatsapp.group", ondelete="set null", index=True)
    hub_message_count = fields.Integer(compute="_compute_hub_message_count")
    last_hub_message_at = fields.Datetime(compute="_compute_hub_message_count")
    dev_project_id = fields.Many2one(
        "dev.project", required=True, ondelete="restrict", index=True
    )
    default_environment_id = fields.Many2one(
        "dev.environment",
        ondelete="restrict",
        domain="[('project_id', '=', dev_project_id)]",
    )
    default_repository_id = fields.Many2one(
        "dev.repository",
        ondelete="restrict",
        domain="[('project_id', '=', dev_project_id)]",
    )
    odoo_project_id = fields.Many2one("project.project", ondelete="set null")
    intake_mode = fields.Selection(
        [
            ("devhub", "Dev Hub owns intake"),
            ("legacy_op_only", "Legacy OpenProject only"),
            ("observe", "Observe only"),
        ],
        required=True,
        default="devhub",
        index=True,
    )
    auto_create_candidate = fields.Boolean(
        default=True,
        help="When classification indicates a new request, create an intake candidate.",
    )
    require_human_confirm = fields.Boolean(
        default=True,
        help="Human confirmation required before creating a Dev Hub work item.",
    )
    # AI triage (Hub-native). Disabled by default — enable per source after UAT.
    ai_triage_enabled = fields.Boolean(
        default=False,
        help="Allow enqueueing WhatsApp AI group triage for this source.",
    )
    project_mapping_state = fields.Selection(
        [
            ("confirmed", "Confirmed"),
            ("inferred", "Inferred"),
            ("ambiguous", "Ambiguous"),
            ("unmapped", "Unmapped"),
        ],
        default="inferred",
        required=True,
        index=True,
        help="Authoritative mapping quality. AI is blocked when ambiguous/unmapped.",
    )
    project_mapping_confidence = fields.Float(default=0.0)
    project_mapping_evidence = fields.Text(
        help="Human-readable evidence for the current project mapping."
    )
    project_mapping_confirmed_by = fields.Many2one("res.users", readonly=True)
    project_mapping_confirmed_at = fields.Datetime(readonly=True)
    auto_ignore_enabled = fields.Boolean(
        default=False,
        help="When enabled, high-confidence noise may be ignored via controlled Odoo methods.",
    )
    auto_ignore_min_confidence = fields.Float(
        default=0.92,
        help="Minimum confidence required for automatic ignore (when enabled).",
    )
    max_messages_per_batch = fields.Integer(default=12)
    max_chars_per_batch = fields.Integer(default=12000)
    cooldown_minutes = fields.Integer(
        default=15,
        help="Minimum minutes between automatic analysis enqueues for this source.",
    )
    analysis_prompt_version = fields.Char(
        default="wa_triage_v1",
        help="Included in batch fingerprint; bump to force a new analysis version.",
    )
    analysis_mode = fields.Char(default="group_triage")
    sender_policy = fields.Selection(
        [
            ("any_member", "Any group member"),
            ("allowlist", "Allowlisted senders only"),
            ("allowlist_or_approval", "Allowlist or sender review"),
        ],
        required=True,
        default="any_member",
    )
    min_confidence = fields.Float(default=0.75)
    grouping_window_minutes = fields.Integer(default=30)
    map_sync_key = fields.Char(help="Optional key from group-project-map.json")
    sender_ids = fields.One2many("dev.whatsapp.sender", "source_id")
    intake_ids = fields.One2many("dev.whatsapp.intake", "source_id")

    _group_jid_unique = models.Constraint(
        "unique(group_jid)", "Each WhatsApp group JID may be configured once."
    )

    def _compute_hub_message_count(self):
        Message = self.env["whatsapp.message"].sudo()
        for rec in self:
            domain = [("group_jid", "=", rec.group_jid)] if rec.group_jid else [("id", "=", 0)]
            rec.hub_message_count = Message.search_count(domain)
            last = Message.search(domain, order="message_timestamp desc, id desc", limit=1)
            rec.last_hub_message_at = last.message_timestamp if last else False

    @api.constrains("group_jid")
    def _check_group_jid(self):
        for rec in self:
            jid = (rec.group_jid or "").strip()
            if GROUP_JID_RE.fullmatch(jid):
                continue
            if jid.endswith("@g.us") and len(jid) > 8:
                continue
            raise ValidationError(
                "group_jid must be a WhatsApp group id ending with @g.us."
            )

    @api.constrains("default_environment_id", "dev_project_id")
    def _check_non_production_environment(self):
        for rec in self:
            env = rec.default_environment_id
            if not env:
                continue
            if env.project_id != rec.dev_project_id:
                raise ValidationError("Default environment must belong to the Dev Hub project.")
            if getattr(env, "is_production", False) or env.environment_type == "production":
                raise ValidationError(
                    "WhatsApp intake must not default to a production environment."
                )
            if env.data_sensitivity in ("production", "restricted", "confidential"):
                raise ValidationError(
                    "WhatsApp intake default environment must be non-production sensitivity."
                )

    def action_open_hub_messages(self):
        self.ensure_one()
        return self._act_window_hub_messages(
            name="Hub messages · %s" % self.name,
            domain=[("group_jid", "=", self.group_jid)],
            context={"default_group_jid": self.group_jid},
        )

    @api.model
    def _act_window_hub_messages(self, name, domain, context=None):
        # Odoo 19 web client requires action.views (not only view_mode).
        search_view = self.env.ref(
            "whatsapp_hub.view_whatsapp_message_search", raise_if_not_found=False
        )
        ctx = dict(context or {})
        ctx.setdefault("search_default_filter_to_group", 1)
        return {
            "type": "ir.actions.act_window",
            "name": name,
            "res_model": "whatsapp.message",
            "view_mode": "list,form",
            "views": [(False, "list"), (False, "form")],
            "search_view_id": search_view.id if search_view else False,
            "domain": domain,
            "context": ctx,
            "target": "current",
        }

    @api.model
    def _act_window_sources(self):
        return {
            "type": "ir.actions.act_window",
            "name": "WhatsApp Sources",
            "res_model": "dev.whatsapp.source",
            "view_mode": "list,form",
            "views": [(False, "list"), (False, "form")],
            "target": "current",
        }

    @api.model
    def _load_group_project_map(self):
        """Load managed JIDs from canonical Nextcloud map when readable on host."""
        candidates = {}
        for path in GROUP_MAP_PATHS:
            if not path or not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, json.JSONDecodeError) as exc:
                _logger.warning("Could not read group-project-map at %s: %s", path, exc)
                continue
            if not isinstance(data, dict):
                continue
            for jid, meta in data.items():
                if not isinstance(jid, str) or not jid.endswith("@g.us"):
                    continue
                if isinstance(meta, dict):
                    name = meta.get("name") or meta.get("chatwoot_label") or jid
                    label = meta.get("chatwoot_label") or False
                else:
                    name = str(meta) if meta else jid
                    label = False
                candidates[jid] = {"name": name, "chatwoot_label": label}
            if candidates:
                break
        return candidates

    @api.model
    def _default_routing_project(self):
        project = self.env["dev.project"].sudo().search([("name", "=", "PetSpot")], limit=1)
        if not project:
            project = self.env["dev.project"].sudo().search([], limit=1)
        return project

    @api.model
    def _default_routing_environment(self, project):
        if not project:
            return self.env["dev.environment"]
        return self.env["dev.environment"].sudo().search(
            [
                ("project_id", "=", project.id),
                ("environment_type", "!=", "production"),
            ],
            order="id",
            limit=1,
        )

    @api.model
    def action_sync_whitelist_from_hub(self):
        """Create/update DH sources for managed map + Hub + Discuss @g.us."""
        project = self._default_routing_project()
        if not project:
            raise UserError("Create a Dev Hub project (e.g. PetSpot) before syncing sources.")
        environment = self._default_routing_environment(project)
        odoo_project = False
        if "primary_odoo_project_id" in project._fields and project.primary_odoo_project_id:
            odoo_project = project.primary_odoo_project_id
        if not odoo_project:
            odoo_project = self.env["project.project"].sudo().search([], limit=1)

        candidates = {}
        labels = {}

        for jid, name in KNOWN_WHITELIST:
            candidates[jid] = name

        for jid, meta in self._load_group_project_map().items():
            candidates[jid] = meta.get("name") or jid
            if meta.get("chatwoot_label"):
                labels[jid] = meta["chatwoot_label"]

        if "whatsapp.group" in self.env:
            for group in self.env["whatsapp.group"].sudo().search([("active", "=", True)]):
                jid = (group.jid or "").strip()
                if jid.endswith("@g.us"):
                    candidates[jid] = group.name or candidates.get(jid) or jid
                    if group.chatwoot_label:
                        labels[jid] = group.chatwoot_label

        if "whatsapp.message" in self.env:
            Message = self.env["whatsapp.message"].sudo()
            for jid in Message.search([("group_jid", "!=", False)]).mapped("group_jid"):
                jid = (jid or "").strip()
                if jid.endswith("@g.us"):
                    candidates.setdefault(jid, jid)

        if "discuss.channel" in self.env:
            Channel = self.env["discuss.channel"].sudo()
            domain = []
            if "wa_phone" in Channel._fields:
                domain = [("wa_phone", "ilike", "@g.us")]
            channels = Channel.search(domain) if domain else Channel.search([])
            for channel in channels:
                phone = ""
                if "wa_phone" in channel._fields:
                    phone = (channel.wa_phone or "").strip()
                if phone.endswith("@g.us"):
                    candidates.setdefault(phone, channel.name or phone)

        known = dict(KNOWN_WHITELIST)
        created = 0
        updated = 0
        Source = self.sudo()
        Group = self.env["whatsapp.group"].sudo() if "whatsapp.group" in self.env else None
        for jid, name in sorted(candidates.items(), key=lambda item: (item[1] or "").lower()):
            hub_group = False
            if Group is not None:
                hub_group = Group.get_or_create_by_jid(jid, {"name": name})
            existing = Source.search([("group_jid", "=", jid)], limit=1)
            if jid.startswith("clinic-") or jid in CLINIC_OBSERVE_JIDS:
                intake_mode = "observe"
            elif jid in known or jid in labels:
                intake_mode = "devhub"
            else:
                intake_mode = "devhub"
            vals = {
                "name": (name or jid)[:200],
                "group_jid": jid,
                "active": True,
                "dev_project_id": project.id,
                "default_environment_id": environment.id or False,
                "odoo_project_id": odoo_project.id if odoo_project else False,
                "hub_group_id": hub_group.id if hub_group else False,
                "chatwoot_label": (labels.get(jid) or name or jid)[:200],
                "intake_mode": intake_mode,
            }
            if existing:
                existing.write({k: v for k, v in vals.items() if k != "group_jid"})
                updated += 1
            else:
                Source.create(vals)
                created += 1

        # Return a real act_window (with views) so the menu click never crashes.
        action = self._act_window_sources()
        action["context"] = {
            **(action.get("context") or {}),
            "dh_whatsapp_sync_created": created,
            "dh_whatsapp_sync_updated": updated,
        }
        return action

    @api.model
    def action_open_whitelisted_hub_messages(self):
        jids = [
            jid
            for jid in self.sudo().search([("active", "=", True)]).mapped("group_jid")
            if jid
        ]
        return self._act_window_hub_messages(
            name="Hub Messages (whitelist)",
            domain=[("group_jid", "in", jids)] if jids else [("id", "=", 0)],
        )

    def action_enqueue_ai_analysis(self):
        """Manual Analyse button — creates analysis + pending job."""
        self.ensure_one()
        analysis = self.env["dev.whatsapp.analysis"].action_enqueue_analysis(
            self.id, force=True
        )
        return {
            "type": "ir.actions.act_window",
            "name": "WhatsApp AI Analysis",
            "res_model": "dev.whatsapp.analysis",
            "res_id": analysis.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    def action_confirm_project_mapping(self):
        self.ensure_one()
        if not self.dev_project_id:
            raise UserError("Select a Dev Hub project before confirming mapping.")
        self.write(
            {
                "project_mapping_state": "confirmed",
                "project_mapping_confidence": 1.0,
                "project_mapping_confirmed_by": self.env.user.id,
                "project_mapping_confirmed_at": fields.Datetime.now(),
            }
        )
        return True

    def _ai_mapping_allowed(self):
        self.ensure_one()
        return self.project_mapping_state == "confirmed" and bool(self.dev_project_id)

    def _ai_mapping_block_reason(self):
        self.ensure_one()
        if self.project_mapping_state == "confirmed" and self.dev_project_id:
            return False
        if self.project_mapping_state == "ambiguous":
            return (
                "Project confirmation required: this WhatsApp group is ambiguous "
                "(multi-project or conflicting evidence). Confirm the Dev Hub project "
                "on the source before Analyse."
            )
        if self.project_mapping_state == "unmapped":
            return (
                "Project confirmation required: this WhatsApp group is unmapped. "
                "Set the correct Dev Hub project and confirm mapping before Analyse."
            )
        return (
            "Project confirmation required: mapping is not confirmed yet "
            "(state=%s)." % (self.project_mapping_state or "unknown")
        )

    @api.model
    def _apply_p0_mapping_corrections(self):
        """Correct Test source→project mappings from documented evidence (not AI)."""
        Project = self.env["dev.project"].sudo()
        by_code = {p.code: p for p in Project.search([])}
        # jid → (project_code, state, confidence, evidence)
        corrections = {
            "120363411424964076@g.us": (
                "PETSPOT",
                "confirmed",
                1.0,
                "Testopenclow pilot on PetSpot Test DB; group-project-map testing lane.",
            ),
            "clinic-hub-live-smoke@g.us": (
                "PETSPOT",
                "confirmed",
                1.0,
                "Clinic Hub smoke UAT for PetSpot.",
            ),
            "clinic-multi-uat@g.us": (
                "PETSPOT",
                "confirmed",
                1.0,
                "Clinic multi-consumer UAT for PetSpot.",
            ),
            "120363409395291215@g.us": (
                "PETSPOT",
                "confirmed",
                1.0,
                "WhatsApp group name Pet spot sahel branch; petspot-elsahel ownership.",
            ),
            "120363427581631722@g.us": (
                "PETSPOT",
                "confirmed",
                1.0,
                "Arabic PetSpot Sahel open tasks group; same petspot-elsahel ownership.",
            ),
            "120363428056737368@g.us": (
                "ASTA",
                "confirmed",
                1.0,
                "Group name Asta development; maps to Dev Hub ASTA Training.",
            ),
            "120363408418840478@g.us": (
                "ASTA",
                "confirmed",
                1.0,
                "Group name انهاء مشروع ASTA; Dev Hub ASTA Training.",
            ),
            "120363427125783045@g.us": (
                "AZONE",
                "confirmed",
                1.0,
                "Group name AZone - WorldPosta; Dev Hub WorldPosta / A-Zone.",
            ),
            "120363409667117343@g.us": (
                "AZONE",
                "confirmed",
                1.0,
                "Group name Izone - Internal BIS; same iZone/A-Zone Dev Hub project.",
            ),
            "120363408457090778@g.us": (
                "AZONE",
                "confirmed",
                0.95,
                "Bright&I zone (Odoo ERP) shares iZone/A-Zone automation map.",
            ),
            "120363404024033208@g.us": (
                "CYCLEX",
                "confirmed",
                1.0,
                "Group name Cycle X; Dev Hub Cycle X project.",
            ),
            "120363408076611149@g.us": (
                "TOURZ",
                "confirmed",
                0.95,
                "Torz Trading Qatar group; Dev Hub Tours Trading (code TOURZ).",
            ),
            "120363422104853335@g.us": (
                "PETSPOT",
                "ambiguous",
                0.35,
                "Dev Needed is a multi-customer mixed development group; "
                "do not treat PetSpot as authoritative. Confirm per analysis.",
            ),
            "120363409479957889@g.us": (
                "PETSPOT",
                "unmapped",
                0.0,
                "Alzaeem Medical has no dedicated Dev Hub project yet; block AI until mapped.",
            ),
        }
        Source = self.sudo()
        report = []
        for jid, (code, state, conf, evidence) in corrections.items():
            source = Source.search([("group_jid", "=", jid)], limit=1)
            if not source:
                report.append({"jid": jid, "status": "missing_source"})
                continue
            project = by_code.get(code)
            if not project:
                report.append({"jid": jid, "status": "missing_project", "code": code})
                continue
            vals = {
                "dev_project_id": project.id,
                "project_mapping_state": state,
                "project_mapping_confidence": conf,
                "project_mapping_evidence": evidence,
                # Clear env/repo that belong to the previous (wrong) project
                "default_environment_id": False,
                "default_repository_id": False,
            }
            if state == "confirmed":
                vals["project_mapping_confirmed_by"] = self.env.user.id
                vals["project_mapping_confirmed_at"] = fields.Datetime.now()
            else:
                vals["project_mapping_confirmed_by"] = False
                vals["project_mapping_confirmed_at"] = False
                # Keep AI off until confirmed for ambiguous/unmapped
                if state in ("ambiguous", "unmapped"):
                    vals["ai_triage_enabled"] = False
            source.write(vals)
            report.append(
                {
                    "source_id": source.id,
                    "name": source.name,
                    "jid": jid,
                    "project": project.name,
                    "state": state,
                    "confidence": conf,
                }
            )
        _logger.info("P0 WhatsApp source mapping corrections applied: %s", report)
        return report


class DevWhatsappSender(models.Model):
    _name = "dev.whatsapp.sender"
    _description = "Dev Hub WhatsApp Allowed Sender"
    _order = "source_id, sender_jid"

    source_id = fields.Many2one(
        "dev.whatsapp.source", required=True, ondelete="cascade", index=True
    )
    sender_jid = fields.Char(required=True, index=True)
    display_name = fields.Char()
    role = fields.Selection(
        [
            ("submitter", "Submitter"),
            ("approver", "Approver"),
            ("observer", "Observer"),
        ],
        required=True,
        default="submitter",
    )
    active = fields.Boolean(default=True)

    _source_sender_unique = models.Constraint(
        "unique(source_id, sender_jid)",
        "Sender already configured for this WhatsApp source.",
    )

    @api.constrains("sender_jid")
    def _check_sender_jid(self):
        for rec in self:
            jid = (rec.sender_jid or "").strip()
            if not (SENDER_JID_RE.fullmatch(jid) or jid.isdigit()):
                raise ValidationError("sender_jid must be a WhatsApp user JID or digits.")
