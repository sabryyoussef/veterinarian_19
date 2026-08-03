# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase

from odoo.addons.linkedin_connector.services.ats_preflight import (
    classify_preflight,
    location_allowed,
)
from odoo.addons.linkedin_connector.services.platform_classifier import classify_apply_url


class TestAtsDiscovery(TransactionCase):
    def test_platform_classifier_ats(self):
        self.assertEqual(
            classify_apply_url("https://boards.greenhouse.io/acme/jobs/1"), "greenhouse"
        )
        self.assertEqual(
            classify_apply_url("https://jobs.lever.co/acme/abcd"), "lever"
        )
        self.assertEqual(
            classify_apply_url("https://jobs.ashbyhq.com/acme/xyz"), "ashby"
        )
        self.assertEqual(
            classify_apply_url("https://apply.workable.com/acme/j/ABC/"), "workable"
        )
        self.assertEqual(classify_apply_url("https://www.linkedin.com/jobs/view/1"), "linkedin")

    def test_location_policy_gulf_requires_sponsor(self):
        ok, reason = location_allowed("Manama, Bahrain", "Senior Odoo role", False)
        self.assertFalse(ok)
        self.assertEqual(reason, "gulf_without_sponsorship")
        ok2, reason2 = location_allowed(
            "Manama, Bahrain", "We offer visa sponsorship and relocation", False
        )
        self.assertTrue(ok2)
        self.assertEqual(reason2, "gulf_with_sponsorship")

    def test_location_egypt_uae_remote(self):
        self.assertTrue(location_allowed("Cairo, Egypt", "Odoo", False)[0])
        self.assertTrue(location_allowed("Dubai", "Odoo Developer", False)[0])
        self.assertTrue(location_allowed("Anywhere", "Fully remote Odoo", True)[0])
        self.assertTrue(location_allowed("دبي", "Odoo", False)[0])
        self.assertTrue(location_allowed("أبو ظبي", "Odoo Developer", False)[0])

    def test_classify_ineligible_linkedin(self):
        result = classify_preflight(
            title="Senior Odoo Developer",
            location="Remote",
            description="Odoo Python ERP",
            apply_url="https://www.linkedin.com/jobs/view/123",
            remote=True,
            score=80,
        )
        self.assertEqual(result["discovery_class"], "ineligible")
        self.assertIn("blocked_platform", result["blocker"])

    def test_classify_score_informational_only(self):
        """Score 0 must not block when hard gates would otherwise pass (mocked fetch)."""
        from unittest.mock import patch

        html = "<html><body><form><input name='partner_name'/><input name='email'/></form></body></html>"
        with patch(
            "odoo.addons.linkedin_connector.services.ats_preflight.fetch_job_detail",
            return_value={"http_status": 200, "html": html, "final_url": "https://boards.greenhouse.io/x/jobs/1", "description": ""},
        ):
            result = classify_preflight(
                title="Senior Odoo Developer",
                location="Cairo",
                description="Odoo Python PostgreSQL",
                apply_url="https://boards.greenhouse.io/x/jobs/1",
                remote=False,
                score=0,
            )
        self.assertEqual(result["discovery_class"], "safe_canary_candidate")
        self.assertFalse(result.get("blocker"))
        self.assertEqual(result.get("score"), 0.0)

    def test_classify_score_no_longer_blocks(self):
        result = classify_preflight(
            title="Senior Odoo Developer",
            location="Cairo",
            description="Odoo Python",
            apply_url="https://boards.greenhouse.io/x/jobs/1",
            remote=False,
            score=0,
        )
        # Without mocked fetch may human_required or safe — but never score_below_65
        self.assertNotIn("score_below_65", result.get("blocker") or "")
        self.assertFalse((result.get("blocker") or "").startswith("score_below"))

    def test_ats_source_model_and_isolation(self):
        personal = self.env["linkedin.account"].browse(2)
        if not personal.exists():
            personal = self.env["linkedin.account"].create(
                {
                    "name": "Personal Test",
                    "account_type": "personal",
                }
            )
            # Force id only when possible — skip if not 2
        src = self.env["linkedin.ats.source"].create(
            {
                "name": "Unit Greenhouse Probe",
                "ats_type": "greenhouse",
                "board_token": "this-board-should-404-zzzz",
                "company": "ProbeCo",
                "region": "remote",
                "enabled": True,
            }
        )
        # Running discovery against 404 board should not touch account 1
        before = self.env["linkedin.job.application"].search_count(
            [("account_id", "=", 1)]
        )
        result = self.env["linkedin.ats.source"].run_discovery_cycle(
            source_ids=src.ids, try_canary=False
        )
        self.assertTrue(result.get("ok"))
        after = self.env["linkedin.job.application"].search_count(
            [("account_id", "=", 1)]
        )
        self.assertEqual(before, after)
        self.assertEqual(after, 0)
        src.invalidate_recordset()
        self.assertTrue(src.last_check_at)
        self.assertEqual(result.get("operating_state"), "ALL_SCORES_POLICY_ACTIVE_WAITING_FOR_SAFE_CANARY")
