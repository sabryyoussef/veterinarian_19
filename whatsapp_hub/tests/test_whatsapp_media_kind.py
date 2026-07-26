# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "whatsapp_hub")
class TestWhatsappMediaKind(TransactionCase):
    def test_classify_image_placeholder(self):
        Message = self.env["whatsapp.message"]
        self.assertEqual(
            Message._classify_media_kind("[image]", "", ""),
            "image",
        )
        self.assertEqual(
            Message._classify_media_kind("", "media_type=audio", ""),
            "audio",
        )
        self.assertEqual(
            Message._classify_media_kind("hello", "", ""),
            "none",
        )
