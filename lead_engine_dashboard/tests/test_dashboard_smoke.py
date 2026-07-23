# -*- coding: utf-8 -*-
"""
Smoke tests for lead_engine_dashboard.

This module contains only view definitions (no custom Python models or
business logic). These tests verify that:
  - The models surfaced by the dashboard views are readable and carry the
    expected analytics fields.
  - crm.lead records expose le_channel, lead_score, and qualification fields
    (used by CRM analytics views).
  - lead.engine.intake.log records carry source_id, channel, status, and
    processing_stage (used by intake-log analytics views).
  - Multiple leads can be aggregated by channel and score (pivot / graph
    views rely on these fields being stored and groupable).
"""

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDashboardFieldsSmoke(TransactionCase):
    """Verify the fields used by dashboard views exist and hold expected data."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Lead = cls.env["crm.lead"]
        cls.Source = cls.env["lead.engine.source"]
        cls.Log = cls.env["lead.engine.intake.log"]
        cls.company = cls.env.company
        cls.source = cls.Source.create(
            {
                "name": "Dashboard Source",
                "code": "DASH_SRC",
                "channel": "api",
                "company_id": cls.company.id,
            }
        )

    # ── crm.lead analytics fields ─────────────────────────────────────────────

    def test_lead_score_field_readable(self):
        lead = self.Lead.create({"name": "Dash Lead 1", "lead_score": 42})
        self.assertEqual(lead.lead_score, 42)

    def test_lead_channel_field_readable(self):
        lead = self.Lead.create(
            {"name": "Dash Lead 2", "le_channel": "form", "lead_score": 10}
        )
        self.assertEqual(lead.le_channel, "form")

    def test_lead_source_link_readable(self):
        lead = self.Lead.create(
            {
                "name": "Dash Lead 3",
                "lead_engine_source_id": self.source.id,
                "le_channel": "api",
            }
        )
        self.assertEqual(lead.lead_engine_source_id.id, self.source.id)

    def test_lead_qualification_state_readable(self):
        lead = self.Lead.create({"name": "Dash Qual Lead"})
        # qualification_state is set by pipeline; default is falsy or 'new'
        _ = lead.qualification_state  # must not raise AttributeError

    def test_lead_duplicate_status_readable(self):
        lead = self.Lead.create({"name": "Dash Dup Lead"})
        _ = lead.duplicate_status  # must not raise AttributeError

    def test_lead_temperature_field_readable(self):
        lead = self.Lead.create(
            {"name": "Hot Lead", "lead_score": 90, "lead_temperature": "hot"}
        )
        self.assertEqual(lead.lead_temperature, "hot")

    # ── Grouping by le_channel (used in graph/pivot views) ───────────────────

    def test_leads_groupby_channel(self):
        self.Lead.create({"name": "Form Lead A", "le_channel": "form"})
        self.Lead.create({"name": "Form Lead B", "le_channel": "form"})
        self.Lead.create({"name": "API Lead C", "le_channel": "api"})
        grouped = self.Lead.read_group(
            domain=[("le_channel", "in", ("form", "api"))],
            fields=["le_channel"],
            groupby=["le_channel"],
        )
        channels = {g["le_channel"] for g in grouped}
        self.assertIn("form", channels)
        self.assertIn("api", channels)

    # ── lead.engine.intake.log analytics fields ───────────────────────────────

    def test_intake_log_status_field_readable(self):
        log = self.env["lead.engine.intake.log"].create(
            {
                "source_id": self.source.id,
                "channel": "api",
                "status": "success",
                "processing_stage": "completed",
            }
        )
        self.assertEqual(log.status, "success")
        self.assertEqual(log.processing_stage, "completed")

    def test_intake_log_groupby_status(self):
        for status in ("success", "success", "rejected", "error"):
            self.env["lead.engine.intake.log"].create(
                {
                    "source_id": self.source.id,
                    "channel": "api",
                    "status": status,
                    "processing_stage": "completed",
                }
            )
        grouped = self.env["lead.engine.intake.log"].read_group(
            domain=[("source_id", "=", self.source.id)],
            fields=["status"],
            groupby=["status"],
        )
        statuses = {g["status"] for g in grouped}
        self.assertIn("success", statuses)
        self.assertIn("rejected", statuses)

    def test_intake_log_channel_field(self):
        log = self.env["lead.engine.intake.log"].create(
            {
                "source_id": self.source.id,
                "channel": "webhook",
                "status": "pending",
                "processing_stage": "received",
            }
        )
        self.assertEqual(log.channel, "webhook")
