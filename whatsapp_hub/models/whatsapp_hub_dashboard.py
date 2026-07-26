# -*- coding: utf-8 -*-
"""KPI payloads for WhatsApp Hub OWL dashboards."""
from __future__ import annotations

from odoo import api, fields, models


class WhatsappHubDashboard(models.AbstractModel):
    _name = "whatsapp.hub.dashboard"
    _description = "WhatsApp Hub Dashboard"

    @api.model
    def get_general_dashboard_data(self):
        """Landing board: platform overview + entry to WhatsApp ops board."""
        counts = self._hub_counts()
        modules = self._module_tiles()
        return {
            "generated_at": fields.Datetime.to_string(fields.Datetime.now()),
            "title": "WhatsApp Platform",
            "subtitle": "Central hub for messages, campaigns, bridge & intake",
            "kpis": [
                {
                    "key": "messages",
                    "label": "Hub messages",
                    "value": counts["messages_total"],
                    "hint": f"{counts['messages_today']} today",
                },
                {
                    "key": "groups",
                    "label": "Groups",
                    "value": counts["groups"],
                    "hint": "active @g.us",
                },
                {
                    "key": "outbound",
                    "label": "Outbound queue",
                    "value": counts["outbound_open"],
                    "hint": f"{counts['outbound_failed']} failed",
                    "tone": "warn" if counts["outbound_failed"] else "ok",
                },
                {
                    "key": "instances",
                    "label": "Instances",
                    "value": counts["instances"],
                    "hint": "configured",
                },
            ],
            "primary_action": {
                "label": "Open WhatsApp Dashboard",
                "action_xmlid": "whatsapp_hub.action_whatsapp_hub_whatsapp_dashboard",
                "description": "Manage messages, queues, groups, and live ops",
            },
            "modules": modules,
            "quick_links": [
                {
                    "label": "Messages",
                    "action_xmlid": "whatsapp_hub.action_whatsapp_message",
                },
                {
                    "label": "Outbound Queue",
                    "action_xmlid": "whatsapp_hub.action_whatsapp_outbound",
                },
                {
                    "label": "Groups",
                    "action_xmlid": "whatsapp_hub.action_whatsapp_group",
                },
                {
                    "label": "Instances",
                    "action_xmlid": "whatsapp_hub.action_whatsapp_instance",
                },
            ],
        }

    @api.model
    def get_whatsapp_dashboard_data(self):
        """Ops board focused on WhatsApp traffic and queue health."""
        counts = self._hub_counts()
        recent = self._recent_messages(limit=8)
        return {
            "generated_at": fields.Datetime.to_string(fields.Datetime.now()),
            "title": "WhatsApp Dashboard",
            "subtitle": "Live traffic, queue health, and shortcuts",
            "back_action": {
                "label": "← General Dashboard",
                "action_xmlid": "whatsapp_hub.action_whatsapp_hub_general_dashboard",
            },
            "kpis": [
                {
                    "key": "in_today",
                    "label": "Inbound today",
                    "value": counts["inbound_today"],
                    "tone": "ok",
                },
                {
                    "key": "out_today",
                    "label": "Outbound today",
                    "value": counts["outbound_today"],
                    "tone": "ok",
                },
                {
                    "key": "pending",
                    "label": "Pending send",
                    "value": counts["outbound_pending"],
                    "tone": "warn" if counts["outbound_pending"] else "ok",
                },
                {
                    "key": "failed",
                    "label": "Failed send",
                    "value": counts["outbound_failed"],
                    "tone": "bad" if counts["outbound_failed"] else "ok",
                },
                {
                    "key": "conversations",
                    "label": "Conversations",
                    "value": counts["conversations"],
                },
                {
                    "key": "contacts",
                    "label": "Contacts",
                    "value": counts["contacts"],
                },
            ],
            "queue": {
                "pending": counts["outbound_pending"],
                "processing": counts["outbound_processing"],
                "failed": counts["outbound_failed"],
                "sent_today": counts["outbound_sent_today"],
            },
            "recent_messages": recent,
            "actions": [
                {
                    "label": "Conversations / Chat",
                    "action_xmlid": "whatsapp_hub.action_whatsapp_conversation",
                    "primary": True,
                },
                {
                    "label": "All Messages",
                    "action_xmlid": "whatsapp_hub.action_whatsapp_message",
                    "primary": True,
                },
                {
                    "label": "Outbound Queue",
                    "action_xmlid": "whatsapp_hub.action_whatsapp_outbound",
                    "primary": True,
                },
                {
                    "label": "Groups",
                    "action_xmlid": "whatsapp_hub.action_whatsapp_group",
                },
                {
                    "label": "Contacts",
                    "action_xmlid": "whatsapp_hub.action_whatsapp_contact",
                },
                {
                    "label": "Instances",
                    "action_xmlid": "whatsapp_hub.action_whatsapp_instance",
                },
            ]
            + self._optional_whatsapp_actions(),
        }

    def _optional_whatsapp_actions(self):
        actions = []
        if self.env["ir.module.module"].sudo().search_count(
            [("name", "=", "evolution_whatsapp_chat"), ("state", "=", "installed")]
        ):
            if self.env.ref(
                "evolution_whatsapp_chat.action_wa_campaign", raise_if_not_found=False
            ):
                actions.append(
                    {
                        "label": "Campaigns",
                        "action_xmlid": "evolution_whatsapp_chat.action_wa_campaign",
                    }
                )
            if self.env.ref(
                "evolution_whatsapp_chat.action_wa_message_log", raise_if_not_found=False
            ):
                actions.append(
                    {
                        "label": "Campaign Logs",
                        "action_xmlid": "evolution_whatsapp_chat.action_wa_message_log",
                    }
                )
        if self.env["ir.module.module"].sudo().search_count(
            [("name", "=", "devhub_whatsapp"), ("state", "=", "installed")]
        ):
            if self.env.ref(
                "devhub_whatsapp.action_devhub_whatsapp_work_inbox",
                raise_if_not_found=False,
            ):
                actions.append(
                    {
                        "label": "Work Inbox",
                        "action_xmlid": "devhub_whatsapp.action_devhub_whatsapp_work_inbox",
                        "primary": True,
                    }
                )
            if self.env.ref(
                "devhub_whatsapp.action_dev_whatsapp_intake", raise_if_not_found=False
            ):
                actions.append(
                    {
                        "label": "DH Intake",
                        "action_xmlid": "devhub_whatsapp.action_dev_whatsapp_intake",
                    }
                )
        return actions

    def _module_tiles(self):
        Module = self.env["ir.module.module"].sudo()

        def installed(name):
            return bool(
                Module.search_count([("name", "=", name), ("state", "=", "installed")])
            )

        tiles = [
            {
                "key": "work_inbox",
                "title": "Work Inbox",
                "description": "Triage WhatsApp messages and create Dev Hub Work",
                "action_xmlid": "devhub_whatsapp.action_devhub_whatsapp_work_inbox",
                "available": installed("devhub_whatsapp")
                and bool(
                    self.env.ref(
                        "devhub_whatsapp.action_devhub_whatsapp_work_inbox",
                        raise_if_not_found=False,
                    )
                ),
                "featured": True,
            },
            {
                "key": "whatsapp_ops",
                "title": "WhatsApp Ops",
                "description": "Messages, queues, groups & contacts",
                "action_xmlid": "whatsapp_hub.action_whatsapp_hub_whatsapp_dashboard",
                "available": True,
                "featured": False,
            },
            {
                "key": "campaign",
                "title": "Campaign & Chat",
                "description": "Bulk campaigns, templates, Discuss WA",
                "action_xmlid": "evolution_whatsapp_chat.action_wa_campaign",
                "available": installed("evolution_whatsapp_chat")
                and bool(
                    self.env.ref(
                        "evolution_whatsapp_chat.action_wa_campaign",
                        raise_if_not_found=False,
                    )
                ),
            },
            {
                "key": "bridge",
                "title": "Integration Bridge",
                "description": "Evolution instances, tokens, outbound bridge",
                "action_xmlid": "integration_bridge_core.action_evolution_instance"
                if self.env.ref(
                    "integration_bridge_core.action_evolution_instance",
                    raise_if_not_found=False,
                )
                else "whatsapp_hub.action_whatsapp_instance",
                "available": installed("integration_bridge_core")
                or installed("whatsapp_hub"),
            },
            {
                "key": "dh",
                "title": "DH WhatsApp",
                "description": "Dev Hub group intake & backfill",
                "action_xmlid": "devhub_whatsapp.action_dev_whatsapp_intake",
                "available": installed("devhub_whatsapp")
                and bool(
                    self.env.ref(
                        "devhub_whatsapp.action_dev_whatsapp_intake",
                        raise_if_not_found=False,
                    )
                ),
            },
            {
                "key": "intake",
                "title": "WA Intake",
                "description": "Clinic pet WhatsApp intakes",
                "action_xmlid": "petspot_wa_intake.action_petspot_wa_intake",
                "available": installed("petspot_wa_intake")
                and bool(
                    self.env.ref(
                        "petspot_wa_intake.action_petspot_wa_intake",
                        raise_if_not_found=False,
                    )
                ),
            },
        ]
        return tiles

    def _hub_counts(self):
        Message = self.env["whatsapp.message"].sudo()
        Outbound = self.env["whatsapp.outbound.message"].sudo()
        now = fields.Datetime.now()
        start_today = fields.Datetime.to_string(now.replace(hour=0, minute=0, second=0))
        return {
            "messages_total": Message.search_count([]),
            "messages_today": Message.search_count(
                [("message_timestamp", ">=", start_today)]
            ),
            "inbound_today": Message.search_count(
                [
                    ("direction", "=", "in"),
                    ("message_timestamp", ">=", start_today),
                ]
            ),
            "outbound_today": Message.search_count(
                [
                    ("direction", "=", "out"),
                    ("message_timestamp", ">=", start_today),
                ]
            ),
            "groups": self.env["whatsapp.group"].sudo().search_count([("active", "=", True)]),
            "contacts": self.env["whatsapp.contact"].sudo().search_count([]),
            "conversations": self.env["whatsapp.conversation"].sudo().search_count([]),
            "instances": self.env["whatsapp.instance"].sudo().search_count([]),
            "outbound_pending": Outbound.search_count([("state", "=", "pending")]),
            "outbound_processing": Outbound.search_count(
                [("state", "=", "processing")]
            ),
            "outbound_failed": Outbound.search_count([("state", "=", "failed")]),
            "outbound_open": Outbound.search_count(
                [("state", "in", ("pending", "processing"))]
            ),
            "outbound_sent_today": Outbound.search_count(
                [
                    ("state", "=", "sent"),
                    ("write_date", ">=", start_today),
                ]
            ),
        }

    def _recent_messages(self, limit=8):
        Message = self.env["whatsapp.message"].sudo()
        rows = []
        for msg in Message.search([], limit=limit, order="message_timestamp desc, id desc"):
            body = (msg.body or "").strip().replace("\n", " ")
            if len(body) > 90:
                body = body[:87] + "…"
            rows.append(
                {
                    "id": msg.id,
                    "direction": msg.direction or "",
                    "when": fields.Datetime.to_string(msg.message_timestamp)
                    if msg.message_timestamp
                    else "",
                    "who": msg.group_jid or msg.remote_jid or msg.sender_jid or "",
                    "body": body or "(empty)",
                    "state": msg.state or "",
                }
            )
        return rows
