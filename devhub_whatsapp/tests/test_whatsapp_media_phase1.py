# -*- coding: utf-8 -*-
"""Phase 1 WhatsApp media retrieval: keys, store, jobs, safety."""
from __future__ import annotations

import base64
import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged, new_test_user

from odoo.addons.devhub_whatsapp.models.dev_whatsapp_media_utils import (
    classify_evolution_error,
    mime_family_ok,
    reconstruct_evolution_key,
    sha256_hex,
    sniff_mime,
)


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@tagged("post_install", "-at_install", "devhub_whatsapp")
class TestWhatsappMediaPhase1(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env,
            login="wa_media_mgr",
            groups="devhub_core.group_dev_hub_manager,base.group_user",
        )
        cls.service = new_test_user(
            cls.env,
            login="wa_media_svc",
            groups="devhub_whatsapp.group_dev_hub_wa_media_service,base.group_user",
        )
        cls.plain = new_test_user(
            cls.env,
            login="wa_media_plain",
            groups="base.group_user",
        )
        Project = cls.env["dev.project"].sudo()
        cls.project = Project.create(
            {
                "name": "WA Media Test Project",
                "code": "wa_media_test",
                "owner_id": cls.manager.id,
                "member_ids": [(4, cls.manager.id)],
                "production_policy": "Test only.",
                "analysis_source_mode": "work_item",
            }
        )
        Source = cls.env["dev.whatsapp.source"].sudo()
        cls.source = Source.create(
            {
                "name": "Media Test Group",
                "group_jid": "120363999888777099@g.us",
                "dev_project_id": cls.project.id,
                "ai_triage_enabled": False,
                "project_mapping_state": "confirmed",
                "project_mapping_confidence": 1.0,
                "project_mapping_evidence": "unit test",
            }
        )
        Conv = cls.env["whatsapp.conversation"].sudo()
        cls.conv = Conv.create(
            {
                "name": "Media Test Conv",
                "remote_jid": cls.source.group_jid,
                "conversation_type": "group",
                "purpose": "other",
            }
        )

    def _msg(self, **vals):
        import uuid as _uuid_mod

        token = _uuid_mod.uuid4().hex[:12]
        evo_id = vals.pop("evolution_message_id", f"EVO{token}")
        defaults = {
            "conversation_id": self.conv.id,
            "group_jid": self.source.group_jid,
            "direction": "in",
            "body": "[image]",
            "media_kind": "image",
            "has_media": True,
            "sender_jid": "201000000099@s.whatsapp.net",
            "inbox_state": "new",
            "message_timestamp": fields.Datetime.now(),
            "state": "received",
            "provider": "evolution",
            "instance_reference": "sabry min",
            "evolution_message_id": evo_id,
            "provider_message_id": evo_id,
            "dedupe_key": f"media-test:{evo_id}",
        }
        defaults.update(vals)
        defaults["provider_message_id"] = defaults.get("provider_message_id") or defaults[
            "evolution_message_id"
        ]
        defaults["dedupe_key"] = "media-test:%s:%s" % (
            defaults["evolution_message_id"],
            defaults.get("sender_jid"),
        )
        return self.env["whatsapp.message"].sudo().create(defaults)

    def test_reconstruct_key_inbound_group(self):
        msg = self._msg(evolution_message_id="TESTMEDIA001")
        key = reconstruct_evolution_key(msg)
        self.assertEqual(key["remoteJid"], self.source.group_jid)
        self.assertEqual(key["id"], "TESTMEDIA001")
        self.assertFalse(key["fromMe"])
        self.assertEqual(key["participant"], "201000000099@s.whatsapp.net")

    def test_reconstruct_key_from_me_outbound(self):
        msg = self._msg(direction="out", evolution_message_id="OUT001")
        key = reconstruct_evolution_key(msg)
        self.assertTrue(key["fromMe"])
        self.assertNotIn("participant", key)

    def test_mime_sniff_and_reject_zip(self):
        self.assertEqual(sniff_mime(PNG_1X1), "image/png")
        self.assertTrue(mime_family_ok("image", "image/png", "image/png"))
        self.assertFalse(mime_family_ok("image", "application/zip", "image/png"))
        self.assertFalse(mime_family_ok("document", "application/zip", "application/zip"))

    def test_size_rejection(self):
        msg = self._msg(evolution_message_id="SIZE1")
        media = self.env["dev.whatsapp.media"]._ensure_for_message(msg)
        huge = b"\xff\xd8\xff" + (b"0" * (16 * 1024 * 1024))
        with self.assertRaises(ValidationError):
            self.env["dev.whatsapp.media"]._store_downloaded_bytes(
                media, raw=huge, reported_mime="image/jpeg", filename="big.jpg"
            )

    def test_expired_classification(self):
        code = classify_evolution_error(
            400, "Failed to fetch stream from https://mmg.whatsapp.net/v/x"
        )
        self.assertEqual(code, "expired")

    def test_store_attachment_and_idempotent_ensure(self):
        msg = self._msg(evolution_message_id="STORE1", inbox_state="new")
        inbox_before = msg.inbox_state
        Media = self.env["dev.whatsapp.media"]
        m1 = Media._ensure_for_message(msg)
        m2 = Media._ensure_for_message(msg)
        self.assertEqual(m1.id, m2.id)
        result = Media._store_downloaded_bytes(
            m1,
            raw=PNG_1X1,
            reported_mime="image/png",
            filename="shot.png",
        )
        self.assertEqual(m1.retrieval_state, "downloaded")
        self.assertTrue(m1.attachment_id)
        self.assertEqual(m1.checksum, sha256_hex(PNG_1X1))
        self.assertEqual(result["file_size"], len(PNG_1X1))
        msg.invalidate_recordset()
        self.assertEqual(msg.inbox_state, inbox_before)

    def test_duplicate_checksum_reuses_attachment(self):
        msg1 = self._msg(evolution_message_id="DUP1")
        msg2 = self._msg(evolution_message_id="DUP2", sender_jid="201000000098@s.whatsapp.net")
        Media = self.env["dev.whatsapp.media"]
        a = Media._ensure_for_message(msg1)
        b = Media._ensure_for_message(msg2)
        Media._store_downloaded_bytes(a, raw=PNG_1X1, reported_mime="image/png")
        Media._store_downloaded_bytes(b, raw=PNG_1X1, reported_mime="image/png")
        self.assertEqual(a.attachment_id.id, b.attachment_id.id)
        self.assertNotEqual(a.id, b.id)

    def test_media_job_lease_and_complete(self):
        msg = self._msg(evolution_message_id="JOB1", inbox_state="pending")
        wi_count_before = self.env["dev.work.item"].sudo().search_count([])
        media = self.env["dev.whatsapp.media"]._ensure_for_message(msg)
        Job = self.env["dev.whatsapp.media.job"]
        job = Job._enqueue_download(media)
        self.assertEqual(job.state, "pending")
        JobS = Job.with_user(self.service)
        leased = JobS.service_lease(limit=1, lease_seconds=120, consumer_ref="t")
        self.assertEqual(len(leased["jobs"]), 1)
        j = leased["jobs"][0]
        JobS.service_start(j["job_id"], j["correlation_id"], j["lease_token"])
        out = JobS.service_complete(
            j["job_id"],
            j["correlation_id"],
            j["lease_token"],
            {
                "media_bytes_b64": base64.b64encode(PNG_1X1).decode(),
                "mime_type": "image/png",
                "filename": "x.png",
                "provider_meta": {"http_status": 201},
            },
        )
        self.assertTrue(out.get("attachment_id"))
        media.invalidate_recordset()
        self.assertEqual(media.retrieval_state, "downloaded")
        msg.invalidate_recordset()
        self.assertEqual(msg.inbox_state, "pending")
        self.assertEqual(
            self.env["dev.work.item"].sudo().search_count([]), wi_count_before
        )

    def test_service_fail_expired_no_attachment(self):
        msg = self._msg(evolution_message_id="FAIL1")
        media = self.env["dev.whatsapp.media"]._ensure_for_message(msg)
        Job = self.env["dev.whatsapp.media.job"].with_user(self.service)
        job = self.env["dev.whatsapp.media.job"]._enqueue_download(media)
        leased = Job.service_lease(limit=1, consumer_ref="t")["jobs"][0]
        Job.service_fail(
            leased["job_id"],
            leased["correlation_id"],
            leased["lease_token"],
            error_code="expired",
            error_summary="Failed to fetch stream from mmg.whatsapp.net",
            retryable=False,
        )
        media.invalidate_recordset()
        self.assertEqual(media.retrieval_state, "expired")
        self.assertFalse(media.attachment_id)

    def test_lease_requires_service_group(self):
        msg = self._msg(evolution_message_id="ACL1")
        media = self.env["dev.whatsapp.media"]._ensure_for_message(msg)
        self.env["dev.whatsapp.media.job"]._enqueue_download(media)
        with self.assertRaises(AccessError):
            self.env["dev.whatsapp.media.job"].with_user(self.plain).service_lease(
                limit=1
            )

    def test_lease_expiry_to_retry_then_dead_letter(self):
        msg = self._msg(evolution_message_id="LEASE1")
        media = self.env["dev.whatsapp.media"]._ensure_for_message(msg)
        job = self.env["dev.whatsapp.media.job"]._enqueue_download(media)
        Job = self.env["dev.whatsapp.media.job"].with_user(self.service)
        leased = Job.service_lease(limit=1, lease_seconds=60)["jobs"][0]
        job = self.env["dev.whatsapp.media.job"].browse(leased["job_id"])
        job.with_context(dev_wa_media_action=True).write(
            {
                "lease_expires_at": fields.Datetime.now() - timedelta(seconds=5),
                "max_attempts": 1,
                "attempt_count": 1,
            }
        )
        Job.service_lease(limit=1)
        job.invalidate_recordset()
        self.assertEqual(job.state, "dead_letter")

    def test_attachment_acl_plain_user(self):
        msg = self._msg(evolution_message_id="ACLATT1")
        media = self.env["dev.whatsapp.media"]._ensure_for_message(msg)
        self.env["dev.whatsapp.media"]._store_downloaded_bytes(
            media, raw=PNG_1X1, reported_mime="image/png"
        )
        att = media.attachment_id
        # plain internal user without hub access should not read attachment
        with self.assertRaises(AccessError):
            att.with_user(self.plain).check_access("read")

    def test_historical_flag_no_inbox_change(self):
        msg = self._msg(evolution_message_id="HIST1", inbox_state="ignored")
        media = self.env["dev.whatsapp.media"]._ensure_for_message(
            msg, is_historical_review=True
        )
        self.assertTrue(media.is_historical_review)
        self.env["dev.whatsapp.media"]._store_downloaded_bytes(
            media, raw=PNG_1X1, reported_mime="image/png"
        )
        msg.invalidate_recordset()
        self.assertEqual(msg.inbox_state, "ignored")

    def test_no_openproject_on_media_path(self):
        """Media complete must not call OpenProject helpers."""
        msg = self._msg(evolution_message_id="OP1")
        media = self.env["dev.whatsapp.media"]._ensure_for_message(msg)
        job = self.env["dev.whatsapp.media.job"]._enqueue_download(media)
        Job = self.env["dev.whatsapp.media.job"].with_user(self.service)
        leased = Job.service_lease(limit=1)["jobs"][0]
        Job.service_start(leased["job_id"], leased["correlation_id"], leased["lease_token"])
        # If an OpenProject outbox model exists, ensure count unchanged
        Outbox = self.env["ir.model"].sudo().search([("model", "=", "dev.external.outbox")])
        before = 0
        if Outbox:
            before = self.env["dev.external.outbox"].sudo().search_count([])
        Job.service_complete(
            leased["job_id"],
            leased["correlation_id"],
            leased["lease_token"],
            {
                "media_bytes_b64": base64.b64encode(PNG_1X1).decode(),
                "mime_type": "image/png",
            },
        )
        if Outbox:
            self.assertEqual(
                self.env["dev.external.outbox"].sudo().search_count([]), before
            )
