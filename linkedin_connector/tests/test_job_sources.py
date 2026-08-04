# -*- coding: utf-8 -*-
"""Unit tests for job_sources adapters, SSRF, sanitize, and pipeline."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.linkedin_connector.services.job_sources import (
    ADAPTERS,
    ComplianceError,
    RateLimitError,
    SSRFError,
    description_fingerprint,
    get_adapter,
    process_normalized_jobs,
    sanitize_payload_for_storage,
    validate_http_url,
)
from odoo.addons.linkedin_connector.services.job_sources.adapters.adzuna import AdzunaAdapter
from odoo.addons.linkedin_connector.services.job_sources.adapters.arbeitnow import ArbeitnowAdapter
from odoo.addons.linkedin_connector.services.job_sources.adapters.greenhouse import GreenhouseAdapter
from odoo.addons.linkedin_connector.services.job_sources.adapters.jooble import JoobleAdapter
from odoo.addons.linkedin_connector.services.job_sources.adapters.jsearch import JsearchAdapter
from odoo.addons.linkedin_connector.services.job_sources.adapters.manual import ManualUrlAdapter
from odoo.addons.linkedin_connector.services.job_sources.adapters.remotive import RemotiveAdapter
from odoo.addons.linkedin_connector.services.job_sources.adapters.restricted import (
    RestrictedSourceAdapter,
)
from odoo.addons.linkedin_connector.services.job_sources.http_util import safe_get
from odoo.addons.linkedin_connector.services.job_sources.pipeline import (
    deterministic_dedupe,
    score_normalized_job,
)

FIXTURES = Path(__file__).parent / "fixtures" / "job_sources"


def _load_fixture(name: str):
    with open(FIXTURES / name, encoding="utf-8") as fh:
        return json.load(fh)


class TestJobSourcesUnit(unittest.TestCase):
    """Plain unittest coverage (no DB) for adapters / SSRF / sanitize / pipeline."""

    def test_registry_has_all_adapters(self):
        expected = {
            "jooble",
            "adzuna",
            "arbeitnow",
            "remotive",
            "remoteok",
            "jsearch",
            "greenhouse",
            "lever",
            "ashby",
            "workable",
            "smartrecruiters",
            "recruitee",
            "manual",
            "email_alert",
            "restricted",
        }
        self.assertTrue(expected.issubset(set(ADAPTERS)))
        for key in expected:
            adapter = get_adapter(key)
            self.assertEqual(adapter.adapter_key, key if key != "linkedin" else "restricted")

    def test_ssrf_blocks_metadata_and_loopback(self):
        with self.assertRaises(SSRFError):
            validate_http_url("https://169.254.169.254/latest/meta-data", resolve_dns=False)
        with self.assertRaises(SSRFError):
            validate_http_url("http://127.0.0.1/admin", resolve_dns=False)
        with self.assertRaises(SSRFError):
            validate_http_url("ftp://example.com/x", resolve_dns=False)
        ok = validate_http_url("https://boards-api.greenhouse.io/v1/boards/x/jobs", resolve_dns=False)
        self.assertTrue(ok.startswith("https://"))

    def test_sanitize_strips_secrets_and_query(self):
        payload = {
            "title": "Odoo",
            "api_key": "SECRET",
            "authorization": "Bearer x",
            "nested": {"token": "t", "ok": 1},
            "url": "https://api.example.com/jobs?app_key=abc&q=odoo",
        }
        clean = sanitize_payload_for_storage(payload)
        self.assertNotIn("api_key", clean)
        self.assertNotIn("authorization", clean)
        self.assertNotIn("token", clean["nested"])
        self.assertEqual(clean["nested"]["ok"], 1)
        self.assertIn("REDACTED", clean["url"])
        self.assertIn("q=odoo", clean["url"])

    def test_description_fingerprint_stable(self):
        a = description_fingerprint("Hello   World\n")
        b = description_fingerprint("hello world")
        self.assertEqual(a, b)
        self.assertEqual(len(a), 64)

    def test_jooble_normalize_fixture(self):
        data = _load_fixture("jooble_sample.json")
        adapter = JoobleAdapter(config={"keywords": "odoo"})
        job = adapter.normalize_job(data["jobs"][0])
        self.assertEqual(job["title"], "Senior Odoo Developer")
        self.assertTrue(job["apply_url"].startswith("http"))
        self.assertEqual(job["adapter_key"], "jooble")
        self.assertEqual(job["sponsorship"], "yes")
        self.assertTrue(job["source_uid"])

    def test_adzuna_normalize_fixture(self):
        data = _load_fixture("adzuna_sample.json")
        adapter = AdzunaAdapter()
        job = adapter.normalize_job(data["results"][0])
        self.assertEqual(job["company"], "Gulf Tech")
        self.assertEqual(job["salary_min"], 12000)
        self.assertIn("Dubai", job["location"])

    def test_arbeitnow_remotive_greenhouse_fixtures(self):
        an = ArbeitnowAdapter().normalize_job(_load_fixture("arbeitnow_sample.json")["data"][0])
        self.assertTrue(an["remote"])
        self.assertEqual(an["sponsorship"], "yes")

        rem = RemotiveAdapter().normalize_job(_load_fixture("remotive_sample.json")["jobs"][0])
        self.assertEqual(rem["adapter_key"], "remotive")
        self.assertTrue(rem["apply_url"])

        gh = GreenhouseAdapter(config={"board_token": "acme"}).normalize_job(
            _load_fixture("greenhouse_sample.json")["jobs"][0]
        )
        self.assertEqual(gh["external_id"], "9001")
        self.assertIn("greenhouse.io", gh["apply_url"])

    def test_jooble_fetch_mock(self):
        data = _load_fixture("jooble_sample.json")
        adapter = JoobleAdapter(config={"api_key": "test-key-not-real", "keywords": "odoo"})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"{}"
        mock_resp.json.return_value = data
        with patch(
            "odoo.addons.linkedin_connector.services.job_sources.adapters.jooble.safe_post",
            return_value=mock_resp,
        ) as mocked:
            result = adapter.fetch_jobs()
        mocked.assert_called_once()
        self.assertEqual(result.count, 1)
        self.assertEqual(result.http_status, 200)

    def test_arbeitnow_fetch_mock(self):
        data = _load_fixture("arbeitnow_sample.json")
        adapter = ArbeitnowAdapter(config={"keywords": "odoo"})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"{}"
        mock_resp.json.return_value = data
        with patch(
            "odoo.addons.linkedin_connector.services.job_sources.adapters.arbeitnow.safe_get",
            return_value=mock_resp,
        ):
            result = adapter.fetch_jobs()
        self.assertEqual(result.count, 1)

    def test_jsearch_stubs_without_key(self):
        with patch.dict(os.environ, {}, clear=False):
            for key in ("LINKEDIN_JSEARCH_RAPIDAPI_KEY", "JSEARCH_RAPIDAPI_KEY"):
                os.environ.pop(key, None)
            adapter = JsearchAdapter(config={})
            result = adapter.fetch_jobs()
        self.assertEqual(result.count, 0)
        self.assertEqual(result.meta.get("skipped"), "api_key_missing")

    def test_restricted_raises_compliance(self):
        adapter = RestrictedSourceAdapter(config={"restricted_source": "linkedin"})
        with self.assertRaises(ComplianceError):
            adapter.fetch_jobs()

    def test_manual_adapter(self):
        adapter = ManualUrlAdapter(
            config={
                "jobs": [
                    {
                        "title": "Odoo Dev",
                        "company": "X",
                        "apply_url": "https://example.com/jobs/1",
                        "description": "Odoo Python",
                    }
                ]
            }
        )
        result = adapter.fetch_jobs()
        self.assertEqual(result.count, 1)
        norm = adapter.normalize_job(result.jobs[0])
        self.assertEqual(norm["adapter_key"], "manual")

    def test_safe_get_rate_limit(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "slow down"
        with patch("odoo.addons.linkedin_connector.services.job_sources.http_util.requests.get", return_value=mock_resp):
            with self.assertRaises(RateLimitError):
                safe_get("https://example.com/api", validate_url=True)

    def test_pipeline_dedupe_filter_score(self):
        adapter = JoobleAdapter()
        raw = _load_fixture("jooble_sample.json")["jobs"][0]
        job = adapter.normalize_job(raw)
        dup = dict(job)
        dup["source_uid"] = job["source_uid"] + "-copy"
        # same apply url → duplicate
        batch = deterministic_dedupe([job, dup])
        self.assertFalse(batch[0]["is_duplicate"])
        self.assertTrue(batch[1]["is_duplicate"])

        scored = score_normalized_job(job, trust_level=80)
        self.assertIn("score_breakdown", scored)
        for key in (
            "role_fit",
            "technical_fit",
            "location_fit",
            "remote_fit",
            "authorization_fit",
            "salary_fit",
            "source_quality",
        ):
            self.assertIn(key, scored["score_breakdown"])
        self.assertGreaterEqual(scored["score"], 0)
        self.assertLessEqual(scored["score"], 100)

        processed = process_normalized_jobs(None, [job])
        self.assertEqual(len(processed), 1)
        self.assertIn(processed[0]["lifecycle_state"], {"discovered", "qualified", "rejected"})


@tagged("post_install", "-at_install")
class TestJobSourcesOdoo(TransactionCase):
    """Thin Odoo TransactionCase smoke — registry + pipeline with env."""

    def test_get_adapter_and_process_with_env(self):
        adapter = get_adapter("greenhouse", env=self.env, config={"board_token": "demo"})
        raw = _load_fixture("greenhouse_sample.json")["jobs"][0]
        job = adapter.normalize_job(raw)
        out = process_normalized_jobs(self.env, [job], trust_level=70, score_threshold=40)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].get("description_fingerprint"))
