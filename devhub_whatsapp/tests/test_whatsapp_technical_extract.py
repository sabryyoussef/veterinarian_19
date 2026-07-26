# -*- coding: utf-8 -*-
"""Technical evidence extraction from mixed Arabic/English WhatsApp texts."""
from __future__ import annotations

from odoo.tests import TransactionCase, tagged

from odoo.addons.devhub_whatsapp.models.dev_whatsapp_technical_extract import (
    extract_technical_evidence,
)


@tagged("post_install", "-at_install", "devhub_whatsapp")
class TestWhatsappTechnicalExtract(TransactionCase):
    def test_arabic_english_rpc_paths_and_modules(self):
        texts = [
            "السلام عليكم — عندنا مشكلة في التقرير",
            "RPC_ERROR: Odoo Server Error\n"
            "PermissionError: Access denied\n"
            "Traceback (most recent call last):\n"
            '  File "/opt/odoo/addons/edafaa_student_profile/models/batch_intake.py", line 42, in action_confirm\n'
            "    raise PermissionError('no')\n"
            "PermissionError: no\n"
            "Please check index.html and html4css1.css under static/\n"
            "Also see edafaa_student_profile.view_batch_form and model student.profile\n"
            "Link: https://example.com/bug #123 OP #10 WI-55",
        ]
        evidence = extract_technical_evidence(texts)
        self.assertIn("RPC_ERROR", evidence["detected_errors"])
        self.assertTrue(
            any("PermissionError" in e for e in evidence["detected_errors"])
        )
        self.assertTrue(evidence["tracebacks"])
        self.assertTrue(
            any("index.html" in p for p in evidence["detected_paths"])
        )
        self.assertTrue(
            any("html4css1.css" in p for p in evidence["detected_paths"])
        )
        self.assertTrue(
            any(p.endswith(".py") for p in evidence["detected_paths"])
        )
        self.assertIn("edafaa_student_profile", evidence["detected_modules"])
        self.assertIn("batch_intake", evidence["detected_modules"])
        self.assertTrue(
            any("student.profile" in m for m in evidence["detected_models"])
        )
        self.assertTrue(evidence["detected_xml_ids"] or evidence["detected_urls"])
        self.assertTrue(evidence["detected_work_references"])
        self.assertFalse(evidence["missing_content"])

    def test_missing_encrypted_content(self):
        evidence = extract_technical_evidence(
            ["", "Content unavailable: encrypted or unsupported"]
        )
        self.assertTrue(evidence["missing_content"])

    def test_extract_from_messages_helper(self):
        Extract = self.env["dev.whatsapp.technical.extract"]
        result = Extract.extract_technical_evidence(
            ["RPC_ERROR in index.html for batch_intake"]
        )
        self.assertIn("RPC_ERROR", result["detected_errors"])
        self.assertTrue(any("index.html" in p for p in result["detected_paths"]))
