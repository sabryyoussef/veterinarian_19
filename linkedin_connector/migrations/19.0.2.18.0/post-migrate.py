# -*- coding: utf-8 -*-
"""Multi-channel discovery: backfill source_channel + expand JSearch geo pack."""


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    import json

    env = api.Environment(cr, SUPERUSER_ID, {})
    ICP = env["ir.config_parameter"].sudo()

    queries = [
        {"query": "Odoo Developer in UAE", "country": "ae", "remote": False},
        {"query": "Odoo Developer in Egypt", "country": "eg", "remote": False},
        {"query": "Odoo Developer in Saudi Arabia", "country": "sa", "remote": False},
        {"query": "Remote Odoo Developer", "country": "", "remote": True},
        {"query": "Python ERP Developer Remote", "country": "", "remote": True},
        {"query": "Odoo Consultant UAE", "country": "ae", "remote": False},
    ]
    ICP.set_param(
        "linkedin_connector.jsearch_daily_queries_json",
        json.dumps(queries, separators=(",", ":")),
    )
    # Slightly raise caps for AE/EG/SA/remote pack (still fail-closed)
    ICP.set_param("linkedin_connector.jsearch_max_requests_per_day", "4")
    ICP.set_param("linkedin_connector.jsearch_max_jobs_per_day", "40")

    Job = env["linkedin.job"].sudo()
    # Backfill source_channel from source / apply_platform / ats_source
    for job in Job.search([("source_channel", "in", (False, "unknown"))]):
        channel = Job._normalize_source_channel(
            source=job.source,
            apply_platform=job.apply_platform,
            ats_type=job.ats_source_id.ats_type if job.ats_source_id else None,
        )
        if channel and channel != "unknown":
            job.with_context(skip_job_postprocess=True, skip_application_create=True).write(
                {"source_channel": channel}
            )

    # Keep live submit off until UAT canary (kill switch discipline)
    if ICP.get_param("linkedin_connector.live_submit_enabled", "False").lower() in (
        "1",
        "true",
        "yes",
    ):
        # Do not force-disable if already intentionally live; leave as-is
        pass
