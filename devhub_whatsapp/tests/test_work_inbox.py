# -*- coding: utf-8 -*-
"""WhatsApp Work Inbox triage, context window, and Create Work wizard tests."""
from datetime import datetime, timedelta
from uuid import uuid4

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged, new_test_user


@tagged("post_install", "-at_install", "devhub_whatsapp", "wa_work_inbox")
class TestWhatsappWorkInbox(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.triage = new_test_user(
            cls.env,
            login="wa_work_inbox_triage",
            groups="devhub_core.group_dev_hub_user,base.group_user",
        )
        cls.manager = new_test_user(
            cls.env,
            login="wa_work_inbox_manager",
            groups="devhub_core.group_dev_hub_manager,base.group_user",
        )
        cls.ingest = new_test_user(
            cls.env,
            login="wa_work_inbox_ingest",
            groups="whatsapp_hub.group_whatsapp_ingest_service,base.group_user",
        )
        cls.dev_project = cls.env.ref("dev_session_hub.dev_project_petspot")
        cls.dev_project.write(
            {
                "member_ids": [
                    (4, cls.triage.id),
                    (4, cls.manager.id),
                ]
            }
        )
        existing_work = cls.env["dev.work.item"].sudo().search(
            [("dev_project_id", "=", cls.dev_project.id)], limit=1
        )
        if existing_work:
            cls.odoo_project = existing_work.odoo_project_id
        else:
            cls.odoo_project = cls.env["project.project"].create(
                {"name": "WI Test Odoo Project"}
            )
        suffix = uuid4().hex[:8]
        cls.conv_a = cls.env["whatsapp.conversation"].sudo().create(
            {
                "name": "WI Conv A %s" % suffix,
                "remote_jid": "20101111%s" % suffix[:4],
                "conversation_type": "dm",
                "purpose": "other",
            }
        )
        cls.conv_b = cls.env["whatsapp.conversation"].sudo().create(
            {
                "name": "WI Conv B %s" % suffix,
                "remote_jid": "20102222%s" % suffix[:4],
                "conversation_type": "dm",
                "purpose": "other",
            }
        )

    def _msg(self, conv, body, **extra):
        token = uuid4().hex
        vals = {
            "conversation_id": conv.id,
            "direction": "in",
            "body": body,
            "message_timestamp": extra.pop("message_timestamp", False)
            or fields_now(self),
            "sender_jid": extra.pop("sender_jid", "201099999999@s.whatsapp.net"),
            "state": "received",
            "provider": "other",
            "provider_message_id": extra.pop("provider_message_id", "manual:%s" % token),
            "dedupe_key": extra.pop("dedupe_key", "wi-test:%s" % token),
        }
        vals.update(extra)
        return self.env["whatsapp.message"].sudo().create(vals)

    def test_historical_defaults_untriaged(self):
        msg = self._msg(self.conv_a, "historical body")
        self.assertEqual(msg.inbox_state, "untriaged")

    def test_ingest_sets_new_and_dedupe_preserves(self):
        Message = self.env["whatsapp.message"].with_user(self.ingest)
        payload = {
            "group_jid": "120363411424964076@g.us",
            "group_name": "wi-test-group",
            "chatwoot_account_id": 1,
            "chatwoot_inbox_id": 2,
            "chatwoot_conversation_id": 91001,
            "chatwoot_message_id": 910001 + int(uuid4().int % 100000),
            "text": "Inbox admit me please",
            "sender_jid": "201003670502@s.whatsapp.net",
        }
        first = Message.service_ingest_normalized(payload)
        msg = self.env["whatsapp.message"].browse(first["message_id"])
        self.assertEqual(msg.inbox_state, "new")
        msg.with_user(self.triage).action_inbox_set_pending()
        self.assertEqual(msg.inbox_state, "pending")
        second = Message.service_ingest_normalized(payload)
        self.assertTrue(second.get("duplicate"))
        msg.invalidate_recordset()
        self.assertEqual(msg.inbox_state, "pending")

    def test_ignore_restore_previous_pending(self):
        msg = self._msg(self.conv_a, "pending then ignore")
        msg.with_user(self.triage).action_inbox_add()
        self.assertEqual(msg.inbox_state, "new")
        msg.with_user(self.triage).action_inbox_set_pending()
        self.assertEqual(msg.inbox_state, "pending")
        msg.with_user(self.triage).action_inbox_ignore()
        self.assertEqual(msg.inbox_state, "ignored")
        self.assertEqual(msg.previous_inbox_state, "pending")
        msg.with_user(self.triage).action_inbox_restore()
        self.assertEqual(msg.inbox_state, "pending")

    def test_ignore_restore_previous_new(self):
        msg = self._msg(self.conv_a, "new then ignore")
        msg.with_user(self.triage).action_inbox_add()
        msg.with_user(self.triage).action_inbox_ignore()
        msg.with_user(self.triage).action_inbox_restore()
        self.assertEqual(msg.inbox_state, "new")

    def test_context_before_after_and_pagination(self):
        start = datetime(2026, 7, 1, 10, 0, 0)
        msgs = [
            self._msg(
                self.conv_a,
                "ctx-%02d" % i,
                message_timestamp=start + timedelta(minutes=i),
            )
            for i in range(50)
        ]
        focus = msgs[25]
        Message = self.env["whatsapp.message"].with_user(self.triage)
        ctx = Message.get_inbox_context(focus.id, before=20, after=20)
        self.assertEqual(ctx["focus_message_id"], focus.id)
        self.assertEqual(len(ctx["messages"]), 41)  # 20 + focus + 20
        bodies = [m["body"] for m in ctx["messages"]]
        self.assertEqual(bodies[0], "ctx-05")
        self.assertEqual(bodies[20], "ctx-25")
        self.assertEqual(bodies[-1], "ctx-45")
        self.assertTrue(ctx["has_older"])
        self.assertTrue(ctx["has_newer"])
        older = Message.load_inbox_context_older(
            ctx["conversation_id"], ctx["older_cursor"], 20
        )
        self.assertTrue(older["messages"])
        self.assertEqual(older["messages"][0]["body"], "ctx-00")
        newer = Message.load_inbox_context_newer(
            ctx["conversation_id"], ctx["newer_cursor"], 20
        )
        self.assertTrue(any(m["body"] == "ctx-49" for m in newer["messages"]))

    def test_inbox_rows_default_excludes_untriaged(self):
        hist = self._msg(self.conv_a, "stay out")
        active = self._msg(self.conv_a, "in inbox")
        active.with_user(self.triage).action_inbox_add()
        Message = self.env["whatsapp.message"].with_user(self.triage)
        rows = Message.get_work_inbox_rows({"inbox_state": "default"}, limit=50)
        ids = {r["id"] for r in rows["rows"]}
        self.assertIn(active.id, ids)
        self.assertNotIn(hist.id, ids)

    def test_mixed_conversation_rejected(self):
        a = self._msg(self.conv_a, "a")
        b = self._msg(self.conv_b, "b")
        with self.assertRaises(UserError):
            (a | b).with_user(self.triage).action_open_create_work_wizard()

    def test_create_work_multi_message_and_duplicate(self):
        start = datetime(2026, 7, 2, 11, 0, 0)
        m1 = self._msg(
            self.conv_a,
            "The quotation PDF fails",
            message_timestamp=start,
        )
        m2 = self._msg(
            self.conv_a,
            "KeyError on S00030",
            message_timestamp=start + timedelta(minutes=1),
        )
        m1.with_user(self.triage).action_inbox_add()
        m2.with_user(self.triage).action_inbox_add()
        Wizard = self.env["dev.whatsapp.create.work.wizard"].with_user(self.triage)
        wiz = Wizard.create(
            {
                "message_ids": [(6, 0, [m1.id, m2.id])],
                "primary_message_id": m1.id,
                "title": "Gulf: Fix Quotation PDF KeyError on S00030",
                "summary": "test summary",
                "dev_project_id": self.dev_project.id,
                "odoo_project_id": self.odoo_project.id,
                "responsible_user_id": self.triage.id,
                "post_create_inbox_state": "actioned",
            }
        )
        action = wiz.action_create_work()
        work = self.env["dev.work.item"].browse(action["res_id"])
        self.assertTrue(work.exists())
        self.assertEqual(len(work.source_message_ids), 2)
        self.assertTrue(all(s.whatsapp_message_id for s in work.source_message_ids))
        m1.invalidate_recordset()
        self.assertEqual(m1.inbox_state, "actioned")
        self.assertTrue(m1.has_work_item)
        wiz2 = Wizard.create(
            {
                "message_ids": [(6, 0, [m1.id, m2.id])],
                "primary_message_id": m1.id,
                "title": "dup",
                "summary": "dup",
                "dev_project_id": self.dev_project.id,
                "odoo_project_id": self.odoo_project.id,
                "responsible_user_id": self.triage.id,
            }
        )
        with self.assertRaises(UserError):
            wiz2.action_create_work()
        with self.assertRaises(AccessError):
            Wizard.create(
                {
                    "message_ids": [(6, 0, [m1.id])],
                    "primary_message_id": m1.id,
                    "title": "extra",
                    "summary": "extra",
                    "dev_project_id": self.dev_project.id,
                    "odoo_project_id": self.odoo_project.id,
                    "responsible_user_id": self.triage.id,
                    "allow_additional_work": True,
                }
            ).action_create_work()
        extra = (
            self.env["dev.whatsapp.create.work.wizard"]
            .with_user(self.manager)
            .create(
                {
                    "message_ids": [(6, 0, [m1.id])],
                    "primary_message_id": m1.id,
                    "title": "extra manager",
                    "summary": "extra",
                    "dev_project_id": self.dev_project.id,
                    "odoo_project_id": self.odoo_project.id,
                    "responsible_user_id": self.manager.id,
                    "allow_additional_work": True,
                }
            )
        )
        action2 = extra.action_create_work()
        self.assertNotEqual(action2["res_id"], work.id)
        nav = work.with_user(self.triage).action_open_whatsapp_context()
        self.assertEqual(nav["tag"], "devhub_whatsapp_work_inbox")
        self.assertIn(m1.id, nav["params"]["highlight_message_ids"])

    def test_media_kind_on_create(self):
        msg = self._msg(
            self.conv_a,
            "[image]",
            attachment_references="media_type=image",
        )
        self.assertEqual(msg.media_kind, "image")
        self.assertTrue(msg.has_media)
        self.assertEqual(msg.inbox_state, "untriaged")


def fields_now(case):
    from odoo import fields

    return fields.Datetime.now()
