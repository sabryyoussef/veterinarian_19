# -*- coding: utf-8 -*-
from datetime import timedelta
import unittest

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.linkedin_connector.models.linkedin_caught_jobs_dashboard import (
    COMPANY_ACCOUNT_ID,
    PERSONAL_ACCOUNT_ID,
)


@tagged("post_install", "-at_install", "linkedin_dashboard")
class TestCaughtJobsDashboard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Account = cls.env["linkedin.account"]
        # Ensure personal id=2 and company id=1 shape when possible
        cls.company = Account.browse(COMPANY_ACCOUNT_ID)
        if not cls.company.exists():
            cls.company = Account.create(
                {
                    "name": "Company Dash Test",
                    "account_type": "company",
                    "linkedin_organization_id": "999001",
                }
            )
        else:
            if cls.company.account_type != "company":
                cls.company.account_type = "company"

        cls.personal = Account.browse(PERSONAL_ACCOUNT_ID)
        if not cls.personal.exists() or cls.personal.account_type != "personal":
            # Dashboard is hard-scoped to personal account id=2 (Production/TEST).
            raise unittest.SkipTest("linkedin.account id=2 personal is required")
        if cls.personal.account_type != "personal":
            cls.personal.account_type = "personal"

        cls.Dash = cls.env["linkedin.caught.jobs.dashboard"]
        cls.env.user.tz = "Africa/Cairo"

        # Seed personal jobs
        Job = cls.env["linkedin.job"].with_context(skip_application_create=True)
        now = fields.Datetime.now()
        cls.job_a = Job.create(
            {
                "account_id": cls.personal.id,
                "title": "Senior Odoo Developer Cairo",
                "company": "Alpha ERP",
                "location": "Cairo, Egypt",
                "score": 80,
                "apply_platform": "greenhouse",
                "apply_url": "https://boards.greenhouse.io/alpha/jobs/1",
                "discovery_class": "safe_canary_candidate",
                "listed_at": now,
                "source": "test",
            }
        )
        cls.job_b = Job.create(
            {
                "account_id": cls.personal.id,
                "title": "Junior Intern UniqueBetaSoftXYZ",
                "company": "Beta Soft UniqueXYZ",
                "location": "Dubai",
                "score": 40,
                "apply_platform": "lever",
                "apply_url": "https://jobs.lever.co/beta-unique-xyz/x",
                "listed_at": now - timedelta(days=3),
                "source": "test",
            }
        )
        cls.job_b.write(
            {
                "score": 40,
                "apply_platform": "lever",
                "discovery_class": "ineligible",
                "discovery_blocker": "score_below_65:40.0",
            }
        )
        cls.job_old = Job.create(
            {
                "account_id": cls.personal.id,
                "title": "Odoo Consultant Remote",
                "company": "Gamma",
                "location": "Remote",
                "remote": True,
                "score": 70,
                "apply_platform": "company_ats",
                "apply_url": "https://example.com/jobs/gamma-unique-1",
                "listed_at": now - timedelta(days=20),
                "source": "test",
            }
        )
        cls.job_old.write(
            {
                "score": 70,
                "discovery_class": "human_required",
                "discovery_blocker": "captcha",
            }
        )
        cls.job_a.write(
            {
                "score": 80,
                "apply_platform": "greenhouse",
                "discovery_class": "safe_canary_candidate",
                "discovery_blocker": "",
            }
        )
        # Company job must never appear
        cls.company_job = Job.create(
            {
                "account_id": cls.company.id,
                "title": "Company Leak Job",
                "company": "PetSpot",
                "location": "Cairo",
                "score": 99,
                "apply_platform": "company_ats",
                "apply_url": "https://example.com/company-leak",
                "discovery_class": "safe_canary_candidate",
                "listed_at": now,
                "source": "test",
            }
        )
        App = cls.env["linkedin.job.application"]
        cls.app_a = App.create(
            {
                "job_id": cls.job_a.id,
                "account_id": cls.personal.id,
                "state": "applied",
            }
        )

    def test_account_isolation_and_company_exclusion(self):
        data = self.Dash.get_dashboard_data(period="all")
        ids = {r["id"] for r in data["table"]["rows"]}
        self.assertIn(self.job_a.id, ids)
        self.assertNotIn(self.company_job.id, ids)
        self.assertEqual(data["account_id"], PERSONAL_ACCOUNT_ID)
        company_apps = self.env["linkedin.job.application"].search_count(
            [("account_id", "=", COMPANY_ACCOUNT_ID)]
        )
        self.assertEqual(data["kpis"]["company_account_apps"], company_apps)
        titles = {r["title"] for r in data["table"]["rows"]}
        self.assertNotIn("Company Leak Job", titles)

    def test_period_today_and_7d(self):
        today = self.Dash.get_dashboard_data(period="today")
        week = self.Dash.get_dashboard_data(period="7d")
        self.assertGreaterEqual(week["kpis"]["total_jobs"], today["kpis"]["total_jobs"])
        self.assertIn(self.job_a.id, {r["id"] for r in today["table"]["rows"]})

    def test_custom_range_validation(self):
        with self.assertRaises(ValidationError):
            self.Dash.get_dashboard_data(period="custom")
        with self.assertRaises(ValidationError):
            self.Dash.get_dashboard_data(
                period="custom", date_from="2026-08-10", date_to="2026-08-01"
            )
        ok = self.Dash.get_dashboard_data(
            period="custom",
            date_from="2020-01-01",
            date_to="2099-12-31",
        )
        self.assertTrue(ok["ok"])

    def test_cairo_utc_boundaries_custom(self):
        # A Cairo calendar day maps to UTC start 21:00 or 22:00 previous day depending on DST
        data = self.Dash.get_dashboard_data(
            period="custom",
            date_from=fields.Date.to_string(fields.Date.context_today(self.env.user)),
            date_to=fields.Date.to_string(fields.Date.context_today(self.env.user)),
        )
        self.assertEqual(data["period"]["user_tz"], "Africa/Cairo")
        self.assertTrue(data["period"]["utc_from"])
        self.assertTrue(data["period"]["utc_to"])

    def test_combined_filters_and_search(self):
        data = self.Dash.get_dashboard_data(
            period="all",
            discovery_class="ineligible",
            platform="lever",
            min_score=30,
            search="UniqueBetaSoftXYZ",
        )
        ids = {r["id"] for r in data["table"]["rows"]}
        self.assertEqual(ids, {self.job_b.id})
        self.assertEqual(data["kpis"]["total_jobs"], 1)

    def test_safe_canary_filter_and_kpis(self):
        data = self.Dash.get_dashboard_data(period="all", safe_canary_only=True)
        self.assertTrue(all(r["safe_canary"] for r in data["table"]["rows"]))
        all_data = self.Dash.get_dashboard_data(period="all")
        self.assertGreaterEqual(all_data["kpis"]["safe_canary"], 1)
        self.assertGreaterEqual(all_data["kpis"]["ineligible"], 1)
        self.assertGreaterEqual(all_data["kpis"]["hard_excluded"], 1)
        self.assertGreaterEqual(all_data["kpis"]["human_required"], 1)
        self.assertGreaterEqual(all_data["kpis"]["applied"], 1)
        self.assertGreaterEqual(all_data["kpis"]["auto_eligible"], 1)
        self.assertEqual(all_data["kpis"]["eligible"], all_data["kpis"]["auto_eligible"])
        self.assertTrue(all_data.get("score_informational_only"))

    def test_grouping_charts(self):
        data = self.Dash.get_dashboard_data(period="all")
        class_labels = {c["label"] for c in data["charts"]["by_class"]}
        self.assertTrue(class_labels)
        plat_labels = {c["label"] for c in data["charts"]["by_platform"]}
        self.assertIn("greenhouse", plat_labels)
        self.assertTrue(data["charts"]["by_day"])
        self.assertTrue(data["charts"]["by_score"])

    def test_pagination(self):
        page1 = self.Dash.get_dashboard_data(period="all", offset=0, limit=1)
        page2 = self.Dash.get_dashboard_data(period="all", offset=1, limit=1)
        self.assertEqual(len(page1["table"]["rows"]), 1)
        self.assertEqual(len(page2["table"]["rows"]), 1)
        self.assertNotEqual(page1["table"]["rows"][0]["id"], page2["table"]["rows"][0]["id"])
        self.assertGreaterEqual(page1["table"]["total"], 3)

    def test_app_state_filter(self):
        data = self.Dash.get_dashboard_data(period="all", app_state="applied")
        ids = {r["id"] for r in data["table"]["rows"]}
        self.assertIn(self.job_a.id, ids)
        self.assertTrue(all(r["app_state"] == "applied" for r in data["table"]["rows"]))

    def test_no_write_on_open_or_refresh(self):
        from unittest.mock import patch

        writes = {"count": 0}
        Job = self.env["linkedin.job"]
        App = self.env["linkedin.job.application"]
        Policy = self.env["linkedin.apply.policy"]

        original_job_write = Job.write
        original_app_write = App.write
        original_policy_write = Policy.write

        def job_write(records, vals):
            writes["count"] += 1
            return original_job_write(records, vals)

        def app_write(records, vals):
            writes["count"] += 1
            return original_app_write(records, vals)

        def policy_write(records, vals):
            writes["count"] += 1
            return original_policy_write(records, vals)

        with patch.object(type(Job), "write", job_write), patch.object(
            type(App), "write", app_write
        ), patch.object(type(Policy), "write", policy_write):
            self.Dash.get_dashboard_data(period="all")
            self.Dash.get_dashboard_data(period="7d")
        self.assertEqual(writes["count"], 0)

    def test_action_open_job_rejects_company(self):
        from odoo.exceptions import AccessError

        with self.assertRaises(AccessError):
            self.Dash.action_open_job(self.company_job.id)
        action = self.Dash.action_open_job(self.job_a.id)
        self.assertEqual(action["res_id"], self.job_a.id)

    def test_smart_actions_preserve_account(self):
        action = self.Dash.action_open_smart("auto_eligible")
        self.assertIn(("account_id", "=", PERSONAL_ACCOUNT_ID), action["domain"])
        self.assertIn(
            ("discovery_class", "=", "safe_canary_candidate"), action["domain"]
        )

    def test_empty_dataset(self):
        data = self.Dash.get_dashboard_data(
            period="all", search="zzz-no-such-job-qqq", min_score=99
        )
        self.assertEqual(data["kpis"]["total_jobs"], 0)
        self.assertEqual(data["table"]["rows"], [])

    def test_reconcile_total_against_orm(self):
        data = self.Dash.get_dashboard_data(period="all")
        orm_count = self.env["linkedin.job"].search_count(
            [
                ("account_id", "=", PERSONAL_ACCOUNT_ID),
                ("is_duplicate", "=", False),
            ]
        )
        self.assertEqual(data["kpis"]["total_jobs"], orm_count)
