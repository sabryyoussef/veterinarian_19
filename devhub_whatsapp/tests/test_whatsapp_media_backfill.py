# -*- coding: utf-8 -*-
"""Controlled seven-day WhatsApp media backfill selection and safety tests."""
from __future__ import annotations

import uuid
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install", "devhub_whatsapp")
class TestWhatsappMediaBackfill(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env,
            login="wa_backfill_mgr",
            groups="devhub_core.group_dev_hub_manager,base.group_user",
        )
        cls.project = cls.env["dev.project"].sudo().create(
            {
                "name": "WA Backfill Project",
                "code": "WA_BACKFILL",
                "owner_id": cls.manager.id,
                "member_ids": [(4, cls.manager.id)],
                "production_policy": "Test only.",
                "analysis_source_mode": "work_item",
            }
        )
        Source = cls.env["dev.whatsapp.source"].sudo()
        cls.confirmed = Source.create(
            {
                "name": "Backfill Confirmed",
                "group_jid": "120363999100000001@g.us",
                "dev_project_id": cls.project.id,
                "active": True,
                "historical_review_enabled": True,
                "historical_review_lane": "confirmed_single",
                "project_mapping_state": "confirmed",
                "project_mapping_confidence": 1.0,
                "project_mapping_evidence": "test",
                "require_human_confirm": True,
            }
        )
        cls.multi = Source.create(
            {
                "name": "Backfill Dev Needed",
                "group_jid": "120363999100000002@g.us",
                "dev_project_id": cls.project.id,
                "active": True,
                "historical_review_enabled": True,
                "historical_review_lane": "multi_project",
                "project_mapping_state": "ambiguous",
                "project_mapping_evidence": "test multi-project",
                "ai_triage_enabled": False,
                "require_human_confirm": True,
            }
        )
        cls.alzaeem = Source.create(
            {
                "name": "Alzaeem Backfill Excluded",
                "group_jid": "120363999100000003@g.us",
                "dev_project_id": cls.project.id,
                "active": True,
                "historical_review_enabled": False,
                "historical_review_lane": "excluded",
                "project_mapping_state": "unmapped",
                "project_mapping_evidence": "not approved",
                "ai_triage_enabled": False,
                "require_human_confirm": True,
            }
        )
        cls.conversations = {}
        for source in (cls.confirmed, cls.multi, cls.alzaeem):
            cls.conversations[source.id] = (
                cls.env["whatsapp.conversation"]
                .sudo()
                .create(
                    {
                        "name": source.name,
                        "remote_jid": source.group_jid,
                        "conversation_type": "group",
                        "purpose": "other",
                    }
                )
            )
        cls.start = fields.Datetime.now() - timedelta(days=7)
        cls.end = fields.Datetime.now()

    def _message(self, source, when=None, media_kind="image", has_media=True):
        token = uuid.uuid4().hex
        return (
            self.env["whatsapp.message"]
            .sudo()
            .create(
                {
                    "conversation_id": self.conversations[source.id].id,
                    "dh_source_id": source.id,
                    "group_jid": source.group_jid,
                    "direction": "in",
                    "body": "[%s]" % media_kind,
                    "media_kind": media_kind,
                    "has_media": has_media,
                    "sender_jid": "201000000097@s.whatsapp.net",
                    "inbox_state": "new",
                    "message_timestamp": when or (self.end - timedelta(seconds=1)),
                    "state": "received",
                    "provider": "evolution",
                    "instance_reference": "sabry min",
                    "evolution_message_id": token[:24],
                    "provider_message_id": token[:24],
                    "dedupe_key": "wa-backfill:%s" % token,
                }
            )
        )

    def _service(self):
        return self.env["dev.whatsapp.media.backfill"].with_user(self.manager)

    def test_date_filter_is_inclusive_and_limited_to_seven_days(self):
        at_start = self._message(self.confirmed, when=self.start)
        at_end = self._message(self.confirmed, when=self.end)
        outside = self._message(
            self.confirmed, when=self.start - timedelta(seconds=1)
        )
        dry = self._service().dry_run(
            self.start, self.end, source_ids=[self.confirmed.id]
        )
        selected_ids = {item["message_id"] for item in dry["selected"]}
        self.assertIn(at_start.id, selected_ids)
        self.assertIn(at_end.id, selected_ids)
        self.assertNotIn(outside.id, selected_ids)

    def test_confirmed_and_multi_included_but_alzaeem_excluded(self):
        confirmed_msg = self._message(self.confirmed)
        multi_msg = self._message(self.multi)
        excluded_msg = self._message(self.alzaeem)
        dry = self._service().dry_run(self.start, self.end)
        selected_ids = {item["message_id"] for item in dry["selected"]}
        self.assertIn(confirmed_msg.id, selected_ids)
        self.assertIn(multi_msg.id, selected_ids)
        self.assertNotIn(excluded_msg.id, selected_ids)
        self.assertEqual(self.multi.project_mapping_state, "ambiguous")
        self.assertFalse(self.multi.ai_triage_enabled)

    def test_unsupported_document_is_not_selected(self):
        document = self._message(self.confirmed, media_kind="document")
        dry = self._service().dry_run(
            self.start, self.end, source_ids=[self.confirmed.id]
        )
        self.assertNotIn(
            document.id, {item["message_id"] for item in dry["selected"]}
        )

    def test_enqueue_is_idempotent_and_non_mutating(self):
        message = self._message(self.confirmed)
        inbox_before = message.inbox_state
        work_before = message.work_item_ids.ids
        Work = self.env["dev.work.item"].sudo()
        work_count_before = Work.search_count([])

        first = self._service().enqueue_batch(
            self.start,
            self.end,
            [self.confirmed.id],
            "image",
            run_ref="unit-test",
        )
        self.assertEqual(first["enqueued_count"], 1)
        media = self.env["dev.whatsapp.media"].sudo().browse(
            first["enqueued"][0]["media_id"]
        )
        self.assertTrue(media.is_historical_review)
        self.assertEqual(media.company_id, self.env.company)
        self.assertEqual(
            self.env["dev.whatsapp.media.job"]
            .sudo()
            .search_count(
                [
                    ("media_id", "=", media.id),
                    ("kind", "=", "media_download"),
                ]
            ),
            1,
        )

        second = self._service().enqueue_batch(
            self.start,
            self.end,
            [self.confirmed.id],
            "image",
            run_ref="unit-test-repeat",
        )
        self.assertEqual(second["enqueued_count"], 0)
        self.assertEqual(
            self.env["dev.whatsapp.media"].sudo().search_count(
                [("whatsapp_message_id", "=", message.id)]
            ),
            1,
        )
        message.invalidate_recordset()
        self.assertEqual(message.inbox_state, inbox_before)
        self.assertEqual(message.work_item_ids.ids, work_before)
        self.assertEqual(Work.search_count([]), work_count_before)

    def test_terminal_media_is_never_retried(self):
        message = self._message(self.confirmed)
        Media = self.env["dev.whatsapp.media"].sudo()
        media = Media._ensure_for_message(message, is_historical_review=True)
        Media._mark_retrieval_failure(media, "expired", "WhatsApp CDN expired")
        dry = self._service().dry_run(
            self.start, self.end, source_ids=[self.confirmed.id]
        )
        excluded = {
            item["message_id"]: item["reason"] for item in dry["excluded"]
        }
        self.assertEqual(excluded[message.id], "terminal_expired")

    def test_media_only_failed_payload_cannot_create_work(self):
        message = self._message(self.multi)
        Media = self.env["dev.whatsapp.media"].sudo()
        media = Media._ensure_for_message(message, is_historical_review=True)
        Media._mark_retrieval_failure(media, "expired", "WhatsApp CDN expired")
        payload = Media.message_media_payload(message)
        self.assertEqual(payload["media_status"], "expired")
        self.assertTrue(payload["needs_manual_review"])
        self.assertEqual(payload["media_items"], [])
