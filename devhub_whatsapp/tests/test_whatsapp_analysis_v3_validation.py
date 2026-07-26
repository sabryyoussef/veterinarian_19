# -*- coding: utf-8 -*-
"""Schema v3 multi-item validation + server-side contains_multiple_tasks."""
from __future__ import annotations

import json

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.devhub_whatsapp.models.dev_whatsapp_analysis_utils import (
    validate_actionable_acceptance,
    validate_ai_response,
)


@tagged("post_install", "-at_install", "devhub_whatsapp")
class TestWhatsappAnalysisV3Validation(TransactionCase):
    def _v3(self, items, **overrides):
        data = {
            "schema_version": "3",
            "project": "Kafaat",
            "conversation_summary": "Multiple issues in student profile",
            "requires_human_review": True,
            "items": items,
        }
        data.update(overrides)
        return json.dumps(data)

    def test_empty_acceptance_criteria_rejected(self):
        batch = [101, 102]
        payload = self._v3(
            [
                {
                    "title": "Fix RPC error",
                    "classification": "bug",
                    "action": "create_work",
                    "description": "RPC_ERROR on save",
                    "current_behavior": "RPC_ERROR",
                    "expected_behavior": "Saves successfully",
                    "acceptance_criteria": [],
                    "test_requirements": ["Reproduce on test"],
                    "source_message_ids": [101],
                    "confidence": 0.9,
                }
            ]
        )
        with self.assertRaises(ValidationError) as err:
            validate_ai_response(payload, batch)
        self.assertIn("acceptance_criteria", str(err.exception))

    def test_multi_item_sets_contains_multiple_tasks_server_side(self):
        batch = [201, 202, 203]
        payload = self._v3(
            [
                {
                    "title": "Bug A",
                    "classification": "bug",
                    "action": "create_work",
                    "description": "First bug",
                    "current_behavior": "Fails",
                    "expected_behavior": "Works",
                    "acceptance_criteria": ["A passes"],
                    "test_requirements": [],
                    "source_message_ids": [201],
                    "confidence": 0.8,
                },
                {
                    "title": "Enhancement B",
                    "classification": "enhancement",
                    "action": "create_work",
                    "description": "Second item",
                    "current_behavior": "Missing",
                    "expected_behavior": "Present",
                    "acceptance_criteria": ["B ready"],
                    "test_requirements": ["UI check"],
                    "source_message_ids": [202, 203],
                    "confidence": 0.7,
                },
            ]
        )
        validated = validate_ai_response(payload, batch)
        self.assertEqual(validated["schema_version"], "3")
        self.assertTrue(validated["contains_multiple_tasks"])
        self.assertEqual(len(validated["analysis_items"]), 2)
        self.assertEqual(validated["work_title"], "Bug A")
        # LLM flag must not win over items length
        payload_false_flag = json.loads(payload)
        payload_false_flag["contains_multiple_tasks"] = False
        validated2 = validate_ai_response(json.dumps(payload_false_flag), batch)
        self.assertTrue(validated2["contains_multiple_tasks"])

    def test_validate_actionable_acceptance_helper(self):
        with self.assertRaises(ValidationError):
            validate_actionable_acceptance(
                {
                    "schema_version": "3",
                    "analysis_items": [
                        {
                            "action": "create_work",
                            "acceptance_criteria": [],
                        }
                    ],
                }
            )
        validate_actionable_acceptance(
            {
                "schema_version": "3",
                "analysis_items": [
                    {
                        "action": "create_work",
                        "acceptance_criteria": ["Done when green"],
                    }
                ],
            }
        )
        # Legacy v1 untouched
        validate_actionable_acceptance(
            {
                "schema_version": "1",
                "contains_work": True,
                "recommended_action": "create_work",
            }
        )

    def test_review_only_allows_empty_test_requirements(self):
        batch = [1]
        payload = self._v3(
            [
                {
                    "title": "Noise",
                    "classification": "unknown",
                    "action": "review_only",
                    "description": "Needs eyes",
                    "source_message_ids": [1],
                    "confidence": 0.4,
                }
            ]
        )
        validated = validate_ai_response(payload, batch)
        self.assertFalse(validated["contains_multiple_tasks"])
        self.assertEqual(validated["recommended_action"], "review")
