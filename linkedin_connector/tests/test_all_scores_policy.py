# -*- coding: utf-8 -*-
"""All-scores application policy: score informational only for account id=2."""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.linkedin_connector.services.ats_preflight import classify_preflight


@tagged("post_install", "-at_install", "linkedin_all_scores")
class TestAllScoresPolicy(TransactionCase):
    def setUp(self):
        super().setUp()
        self.personal = self.env["linkedin.account"].browse(2)
        if not self.personal.exists() or self.personal.account_type != "personal":
            self.skipTest("linkedin.account id=2 personal required")
        self.company = self.env["linkedin.account"].browse(1)
        self.Policy = self.env["linkedin.apply.policy"]
        self.Job = self.env["linkedin.job"].with_context(skip_application_create=True)
        self.App = self.env["linkedin.job.application"]

    def test_score_zero_can_qualify_as_safe_canary(self):
        html = (
            "<html><body><form>"
            "<input name='partner_name'/><input name='email'/>"
            "</form></body></html>"
        )
        with patch(
            "odoo.addons.linkedin_connector.services.ats_preflight.fetch_job_detail",
            return_value={
                "http_status": 200,
                "html": html,
                "final_url": "https://boards.greenhouse.io/acme/jobs/999",
                "description": "",
            },
        ):
            result = classify_preflight(
                title="Odoo Developer",
                location="Cairo, Egypt",
                description="Odoo Python PostgreSQL",
                apply_url="https://boards.greenhouse.io/acme/jobs/999",
                remote=False,
                score=0,
            )
        self.assertEqual(result["discovery_class"], "safe_canary_candidate")
        self.assertEqual(result["score"], 0.0)

    def test_captcha_routes_to_human_required(self):
        html = (
            "<html><body><div class='cf-turnstile' data-sitekey='x'></div>"
            "<form><input name='email'/></form></body></html>"
        )
        with patch(
            "odoo.addons.linkedin_connector.services.ats_preflight.fetch_job_detail",
            return_value={
                "http_status": 200,
                "html": html,
                "final_url": "https://boards.greenhouse.io/acme/jobs/captcha",
                "description": "",
            },
        ):
            result = classify_preflight(
                title="Odoo Developer",
                location="Cairo",
                description="Odoo Python",
                apply_url="https://boards.greenhouse.io/acme/jobs/captcha",
                remote=False,
                score=0,
            )
        self.assertEqual(result["discovery_class"], "human_required")
        self.assertIn("captcha", result["blocker"])

    def test_auth_no_sponsor_hard_excluded(self):
        result = classify_preflight(
            title="Odoo Developer",
            location="Berlin, Germany",
            description=(
                "Odoo Python role. Candidates must be authorized to work in the EU. "
                "No visa sponsorship."
            ),
            apply_url="https://boards.greenhouse.io/acme/jobs/eu",
            remote=False,
            score=90,
        )
        self.assertEqual(result["discovery_class"], "ineligible")
        self.assertTrue(
            "requires_existing_authorization_no_sponsor" in result["blocker"]
            or "eu_without_sponsorship" in result["blocker"]
        )

    def test_company_account_isolation(self):
        before = self.App.search_count([("account_id", "=", 1)])
        company_jobs_before = self.Job.search_count([("account_id", "=", 1)])
        result = self.Policy.apply_all_scores_policy()
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("new_min_score"), 0.0)
        after = self.App.search_count([("account_id", "=", 1)])
        company_jobs_after = self.Job.search_count([("account_id", "=", 1)])
        self.assertEqual(before, after)
        self.assertEqual(company_jobs_before, company_jobs_after)
        reprocess = result.get("reprocess") or {}
        self.assertTrue(reprocess.get("company_apps_unchanged", True))

    def test_policy_min_score_zero_and_caps_still_enforced(self):
        policy = self.Policy.get_policy_for_account(self.personal)
        policy.write(
            {
                "min_score": 0.0,
                "kill_switch": False,
                "browser_submit_enabled": True,
                "max_submits_per_day": 0,
            }
        )
        self.assertEqual(policy.min_score, 0.0)
        with self.assertRaises(UserError):
            policy.assert_submit_caps()
        # Restore safe defaults for other tests / DB
        policy.write(
            {
                "kill_switch": True,
                "browser_submit_enabled": False,
                "max_submits_per_day": 2,
            }
        )

    def test_score_only_blocker_reconsidered(self):
        job = self.Job.create(
            {
                "account_id": self.personal.id,
                "title": "Odoo Developer AllScores",
                "company": "AllScores Co",
                "location": "Cairo, Egypt",
                "description": "Odoo Python PostgreSQL ERP",
                "score": 10,
                "apply_platform": "greenhouse",
                "apply_url": "https://boards.greenhouse.io/allscores-unique/jobs/42",
                "discovery_class": "ineligible",
                "discovery_blocker": "score_below_65:10.0",
                "source": "test",
            }
        )
        html = (
            "<html><body><form>"
            "<input name='partner_name'/><input name='email'/>"
            "</form></body></html>"
        )
        with patch(
            "odoo.addons.linkedin_connector.services.ats_preflight.fetch_job_detail",
            return_value={
                "http_status": 200,
                "html": html,
                "final_url": job.apply_url,
                "description": "",
            },
        ):
            out = self.Job.reprocess_personal_jobs_all_scores()
        self.assertTrue(out.get("ok"))
        job.invalidate_recordset()
        self.assertNotIn("score_below_65", job.discovery_blocker or "")
        self.assertIn(
            job.discovery_class,
            ("safe_canary_candidate", "human_required", "ineligible", "unsupported_ats"),
        )
        if job.discovery_class == "safe_canary_candidate":
            self.assertTrue(
                self.App.search_count(
                    [("job_id", "=", job.id), ("account_id", "=", self.personal.id)]
                )
            )

    def test_dashboard_auto_eligible_ignores_score_floor(self):
        Dash = self.env["linkedin.caught.jobs.dashboard"]
        data = Dash.get_dashboard_data(period="all")
        self.assertTrue(data.get("score_informational_only"))
        self.assertEqual(data.get("min_application_score"), 0.0)
        kpis = data["kpis"]
        self.assertIn("auto_eligible", kpis)
        self.assertIn("queued", kpis)
        self.assertIn("hard_excluded", kpis)
        self.assertIn("capacity_daily_remaining", kpis)
        self.assertTrue(kpis.get("score_informational_only"))
        # auto_eligible must equal safe_canary (not score>=65)
        self.assertEqual(kpis["auto_eligible"], kpis["safe_canary"])
