# -*- coding: utf-8 -*-
"""Tests for account isolation, scoring, dedupe, and application approval gate."""

import base64

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLinkedinJobHunt(TransactionCase):

    def setUp(self):
        super().setUp()
        self.personal = self.env["linkedin.account"].create(
            {
                "name": "Personal Job Hunt",
                "account_type": "personal",
                "client_id": "personal-client",
                "client_secret": "secret",
                "profile_url": "https://www.linkedin.com/in/sabry-youssef-56a878185/",
            }
        )
        self.company = self.env["linkedin.account"].create(
            {
                "name": "PetSpot Company",
                "account_type": "company",
                "client_id": "company-client",
                "client_secret": "secret",
                "linkedin_organization_id": "129944345",
            }
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "linkedin_connector.job_score_threshold", "50"
        )
        # Admin in job hunt group for approve/open
        group = self.env.ref("linkedin_connector.group_linkedin_job_hunt")
        self.env.user.group_ids = [(4, group.id)]

    def _pdf_attachment(self):
        return self.env["ir.attachment"].create(
            {
                "name": "cv.pdf",
                "type": "binary",
                "datas": base64.b64encode(b"%PDF-1.4 test"),
                "mimetype": "application/pdf",
            }
        )

    def test_account_isolation_personal_no_org(self):
        with self.assertRaises(ValidationError):
            self.personal.write({"linkedin_organization_id": "999"})

    def test_account_isolation_company_requires_org(self):
        with self.assertRaises(ValidationError):
            self.env["linkedin.account"].create(
                {
                    "name": "Broken Company",
                    "account_type": "company",
                    "client_id": "x",
                    "client_secret": "y",
                }
            )

    def test_account_isolation_fallback_forbidden(self):
        with self.assertRaises(ValidationError):
            self.personal.write({"fallback_personal_post": True})

    def test_post_purpose_cross_blocked(self):
        with self.assertRaises(ValidationError):
            self.env["linkedin.post"].create(
                {
                    "account_id": self.company.id,
                    "content_purpose": "job_branding",
                    "message": "Should fail",
                }
            )
        with self.assertRaises(ValidationError):
            self.env["linkedin.post"].create(
                {
                    "account_id": self.personal.id,
                    "content_purpose": "company_marketing",
                    "message": "Should fail",
                }
            )

    def test_tips_batch_requires_personal(self):
        with self.assertRaises(UserError):
            self.env["linkedin.post"].create_odoo_tips_schedule_batch(
                account_id=self.company.id
            )

    def test_author_urn_by_type(self):
        self.personal.write(
            {
                "access_token": "tok",
                "linkedin_member_urn": "urn:li:person:abc",
            }
        )
        self.company.write(
            {
                "access_token": "tok",
                "linkedin_member_urn": "urn:li:person:abc",
            }
        )
        self.assertEqual(
            self.personal._get_post_author_urn(), "urn:li:person:abc"
        )
        self.assertEqual(
            self.company._get_post_author_urn(), "urn:li:organization:129944345"
        )

    def test_job_scoring_senior_odoo_high(self):
        score, breakdown, flags = self.env["linkedin.job"].score_job_dict_for_tests(
            {
                "title": "Senior Odoo Developer",
                "company": "Acme",
                "location": "Remote",
                "remote": True,
                "description": "<p>Odoo Python ERP implementation Easy Apply</p>",
            }
        )
        self.assertGreaterEqual(score, 50)
        self.assertTrue(flags["odoo_match"])
        self.assertTrue(flags["seniority_match"])
        self.assertIn("odoo", breakdown)

    def test_job_scoring_junior_low(self):
        score, _breakdown, flags = self.env["linkedin.job"].score_job_dict_for_tests(
            {
                "title": "Junior Java Developer",
                "company": "Acme",
                "location": "Berlin",
                "description": "<p>Java developer only</p>",
            }
        )
        self.assertLess(score, 50)
        self.assertFalse(flags["odoo_match"])

    def test_dedupe_fingerprint(self):
        vals = {
            "title": "Senior Odoo Developer",
            "company": "Acme Corp",
            "job_id": "li_12345",
            "location": "Remote",
            "remote": True,
            "description": "<p>Odoo senior role Python ERP</p>",
            "apply_url": "https://www.linkedin.com/jobs/view/12345/",
        }
        j1 = self.env["linkedin.job"].create(vals)
        j2 = self.env["linkedin.job"].create(dict(vals, job_id="li_12345_dup"))
        # Same company+title+url path → same fingerprint if job_id differs but URL path same
        # Force same fingerprint for the test
        fp = j1.fingerprint
        j2.with_context(skip_job_postprocess=True).write({"fingerprint": fp})
        (j1 | j2)._mark_duplicates()
        group = j1 | j2
        canonical = group.sorted(key=lambda r: (r.score, r.id), reverse=True)[0]
        for job in group:
            if job == canonical:
                self.assertFalse(job.is_duplicate)
            else:
                self.assertTrue(job.is_duplicate)
                self.assertEqual(job.duplicate_of_id, canonical)

    def test_application_created_above_threshold(self):
        job = self.env["linkedin.job"].create(
            {
                "account_id": self.personal.id,
                "title": "Senior Odoo Developer",
                "company": "Acme",
                "location": "Remote",
                "remote": True,
                "description": "<p>Odoo Python ERP Lead</p>",
                "apply_url": "https://www.linkedin.com/jobs/view/999/",
                "job_id": "li_999",
            }
        )
        self.assertGreaterEqual(job.score, 50)
        self.assertEqual(len(job.application_ids), 1)
        self.assertEqual(job.application_ids.state, "discovered")
        self.assertEqual(job.application_ids.account_id, self.personal)

    def test_application_approval_gate(self):
        job = self.env["linkedin.job"].create(
            {
                "account_id": self.personal.id,
                "title": "Senior Odoo Developer",
                "company": "Acme",
                "location": "Egypt",
                "description": "<p>Odoo Senior Python</p>",
                "apply_url": "https://www.linkedin.com/jobs/view/1001/",
                "job_id": "li_1001",
            }
        )
        app = job.application_ids
        self.assertTrue(app)
        cv = self.env["linkedin.cv.version"].create(
            {
                "name": "CV Senior 2026",
                "account_id": self.personal.id,
                "attachment_id": self._pdf_attachment().id,
                "is_default": True,
            }
        )
        app.cv_version_id = cv.id
        with self.assertRaises(UserError):
            app.action_open_application()
        app.action_prepare_pack()
        self.assertEqual(app.state, "pack_ready")
        self.assertTrue(app.cover_letter)
        with self.assertRaises(UserError):
            app.action_open_application()
        app.action_approve()
        self.assertEqual(app.state, "approved")
        action = app.action_open_application()
        self.assertEqual(action["type"], "ir.actions.act_url")
        self.assertIn("linkedin.com", action["url"])
        app.action_mark_applied()
        self.assertEqual(app.state, "applied")

    def test_job_direct_apply_blocked_without_app(self):
        job = self.env["linkedin.job"].with_context(skip_job_postprocess=True).create(
            {
                "title": "Intern",
                "company": "X",
                "score": 0,
                "apply_url": "https://www.linkedin.com/jobs/view/1/",
                "job_id": "li_low",
            }
        )
        with self.assertRaises(UserError):
            job.action_open_apply()

    def test_digest_skips_when_live_disabled(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "linkedin_connector.live_job_search_enabled", "False"
        )
        # Must not raise / call network
        self.env["linkedin.job"]._cron_daily_job_digest()

    def test_personal_post_ok(self):
        post = self.env["linkedin.post"].create(
            {
                "account_id": self.personal.id,
                "content_purpose": "job_branding",
                "message": "Senior Odoo tip test",
            }
        )
        self.assertEqual(post.state, "draft")

    def test_post_write_isolation_blocked(self):
        post = self.env["linkedin.post"].create(
            {
                "account_id": self.personal.id,
                "content_purpose": "job_branding",
                "message": "Write isolation test",
            }
        )
        with self.assertRaises(ValidationError):
            post.write({"content_purpose": "company_marketing"})
        with self.assertRaises(ValidationError):
            post.write({"account_id": self.company.id})
        with self.assertRaises(ValidationError):
            post.write(
                {
                    "account_id": self.company.id,
                    "content_purpose": "job_branding",
                }
            )
