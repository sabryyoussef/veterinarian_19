# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "linkedin_connector")
class TestZeroTouchAnswerLibrary(TransactionCase):
    def setUp(self):
        super().setUp()
        Account = self.env["linkedin.account"]
        self.personal = Account.browse(2).exists()
        if not self.personal:
            self.personal = Account.create(
                {
                    "name": "Personal Sabry",
                    "account_type": "personal",
                }
            )
            # Force id=2 when possible is hard; skip if not 2
        self.Answer = self.env["linkedin.answer.library"]

    def test_seed_and_map(self):
        if not self.personal or self.personal.id != 2:
            self.skipTest("Personal account id=2 required")
        self.Answer.seed_personal_account_defaults(account_id=2)
        data = self.Answer.get_verified_map(2)
        self.assertEqual(data.get("legal_name"), "Sabry Youssef")
        self.assertEqual(data.get("salary_expectation"), "USD 1000/month")
        self.assertEqual(data.get("eu_work_authorization"), "No")
        variants = self.Answer.get_variant_map(2)
        self.assertTrue(any(v["fact_key"] == "notice_period" for v in variants))

    def test_refuse_company_account(self):
        with self.assertRaises(UserError):
            self.Answer.get_verified_map(1)


@tagged("post_install", "-at_install", "linkedin_connector")
class TestEvidenceOnlyApplied(TransactionCase):
    def setUp(self):
        super().setUp()
        Account = self.env["linkedin.account"]
        self.personal = Account.search(
            [("account_type", "=", "personal"), ("id", "=", 2)], limit=1
        )
        if not self.personal:
            self.skipTest("Personal account id=2 required")
        self.job = (
            self.env["linkedin.job"]
            .with_context(skip_job_postprocess=True)
            .create(
                {
                    "title": "Senior Odoo Developer",
                    "company": "Evidence Co",
                    "score": 10,
                    "apply_url": "https://example.test/jobs/1",
                    "job_id": "zt_evidence_1",
                    "account_id": self.personal.id,
                }
            )
        )
        self.app = self.env["linkedin.job.application"].create(
            {
                "job_id": self.job.id,
                "account_id": self.personal.id,
                "state": "approved",
            }
        )

    def test_manual_applied_without_evidence(self):
        self.app.action_mark_confirmed_applied()
        self.assertEqual(self.app.state, "applied")
        self.assertEqual(self.app.submission_channel, "manual")
        self.assertEqual(self.app.evidence_kind, "manual_mark")

    def test_applied_with_evidence(self):
        self.app.write(
            {
                "confirmation_url": "https://example.test/thank-you",
                "confirmation_reference": "REF-ZT-1",
                "evidence_kind": "browser_thank_you_text",
            }
        )
        self.app.action_mark_confirmed_applied()
        self.assertEqual(self.app.state, "applied")

    def test_ambiguous_evidence_submission_unknown(self):
        result = self.app.action_record_submission_evidence(
            {
                "ok": False,
                "ambiguous": True,
                "kind": "ambiguous",
                "confirmation_url": "https://example.test/maybe",
                "channel": "browser",
            }
        )
        self.assertEqual(result["state"], "submission_unknown")
        self.assertEqual(self.app.state, "submission_unknown")
        self.assertFalse(result["applied"])
