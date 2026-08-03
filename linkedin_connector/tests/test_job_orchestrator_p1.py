# -*- coding: utf-8 -*-
import hashlib
import hmac
import json
import time
from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.linkedin_connector.services.platform_classifier import classify_apply_url


@tagged("post_install", "-at_install", "linkedin_orchestrator")
class TestJobOrchestratorP1(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Acc = cls.env["linkedin.account"]
        cls.company = Acc.create(
            {
                "name": "Co",
                "account_type": "company",
                "client_id": "c1",
                "client_secret": "s1",
                "linkedin_organization_id": "129944345",
            }
        )
        cls.personal = Acc.create(
            {
                "name": "Personal",
                "account_type": "personal",
                "client_id": "p1",
                "client_secret": "s1",
            }
        )
        # Force id isolation checks use account_type; also ensure company id exists
        cls.env["ir.config_parameter"].sudo().set_param(
            "linkedin_connector.auto_create_applications", "False"
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "linkedin_connector.orchestrator_webhook_secret", "uat-test-secret"
        )

    def test_platform_classification(self):
        self.assertEqual(classify_apply_url("https://www.linkedin.com/jobs/view/1"), "linkedin")
        self.assertEqual(classify_apply_url("https://ae.indeed.com/viewjob?jk=x"), "indeed")
        self.assertEqual(classify_apply_url("https://bebee.com/ae/jobs/x"), "bebee")
        self.assertEqual(
            classify_apply_url("https://boards.greenhouse.io/acme/jobs/1"), "greenhouse"
        )
        self.assertEqual(classify_apply_url("https://jobs.lever.co/acme/1"), "lever")
        self.assertEqual(classify_apply_url("mailto:hr@example.com"), "email")
        self.assertEqual(classify_apply_url("https://ae.jobrapido.com/x"), "aggregator")

    def test_job_sets_platform_on_create(self):
        job = self.env["linkedin.job"].with_context(skip_job_postprocess=True).create(
            {
                "account_id": self.personal.id,
                "title": "Odoo Dev",
                "company": "Acme",
                "apply_url": "https://bebee.com/ae/jobs/odoo",
                "job_id": "uat_plat_1",
            }
        )
        self.assertEqual(job.apply_platform, "bebee")

    def test_application_rejects_company_account(self):
        job = self.env["linkedin.job"].with_context(skip_job_postprocess=True).create(
            {
                "account_id": self.company.id,
                "title": "X",
                "company": "Co",
                "apply_url": "https://example.com/jobs/1",
                "job_id": "uat_co_1",
            }
        )
        with self.assertRaises(ValidationError):
            self.env["linkedin.job.application"].create(
                {
                    "job_id": job.id,
                    "account_id": self.company.id,
                    "state": "discovered",
                }
            )

    def test_policy_defaults_and_caps(self):
        policy = self.env["linkedin.apply.policy"].get_policy_for_account(self.personal)
        self.assertTrue(policy.kill_switch)
        self.assertFalse(policy.browser_submit_enabled)
        self.assertFalse(policy.email_submit_enabled)
        self.assertFalse(policy.auto_track_enabled)
        with self.assertRaises(UserError):
            policy.assert_orchestration_allowed(for_submit=True)
        policy.kill_switch = False
        with self.assertRaises(UserError):
            policy.assert_orchestration_allowed(platform="linkedin", for_submit=False)

    def test_pack_write_state_gate(self):
        job = self.env["linkedin.job"].with_context(skip_job_postprocess=True).create(
            {
                "account_id": self.personal.id,
                "title": "Senior Odoo",
                "company": "Acme",
                "apply_url": "https://boards.greenhouse.io/acme/jobs/1",
                "job_id": "uat_pack_1",
                "description": "<p>Odoo Python</p>",
            }
        )
        app = self.env["linkedin.job.application"].create(
            {
                "job_id": job.id,
                "account_id": self.personal.id,
                "state": "discovered",
            }
        )
        app.write_pack_from_orchestrator(
            {
                "match_decision": "shortlist",
                "exclusion_flags": [],
                "cover_letter": "Hello",
                "screening_qa": [],
                "missing_facts": ["salary_expectation"],
                "risk_notes": "missing salary",
                "recommended_channel": "browser_dry_run",
            }
        )
        self.assertEqual(app.state, "pack_ready")
        self.assertIn("salary_expectation", app.missing_facts)

    def test_attempt_idempotency(self):
        job = self.env["linkedin.job"].with_context(skip_job_postprocess=True).create(
            {
                "account_id": self.personal.id,
                "title": "Odoo",
                "company": "Acme",
                "apply_url": "https://bebee.com/x",
                "job_id": "uat_att_1",
            }
        )
        app = self.env["linkedin.job.application"].create(
            {
                "job_id": job.id,
                "account_id": self.personal.id,
            }
        )
        a1 = self.env["linkedin.apply.attempt"].create(
            {
                "application_id": app.id,
                "idempotency_key": "idem-1",
                "dry_run": True,
                "state": "drafted",
            }
        )
        a2 = self.env["linkedin.apply.attempt"].create(
            {
                "application_id": app.id,
                "idempotency_key": "idem-1",
                "dry_run": True,
                "state": "pending",
            }
        )
        self.assertEqual(a1.id, a2.id)

    def test_hmac_signature_helper(self):
        secret = "uat-test-secret"
        ts = str(int(time.time()))
        body = b'{"ping":true}'
        sig = hmac.new(
            secret.encode(), (ts + ".").encode() + body, hashlib.sha256
        ).hexdigest()
        payload = (ts + ".").encode() + body
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        self.assertEqual(sig, expected)

    def test_candidate_profile_omits_unset_sensitive(self):
        profile = self.env["linkedin.candidate.profile"].create(
            {
                "name": "UAT Profile",
                "account_id": self.personal.id,
                "years_odoo_experience": 8,
                "uae_relocation": "unset",
                "visa_sponsorship": "unset",
            }
        )
        data = profile.to_sanitized_json()
        self.assertNotIn("salary_expectation", data)
        self.assertNotIn("uae_relocation", data)
        self.assertEqual(data["years_odoo_experience"], 8.0)
