# -*- coding: utf-8 -*-
"""Apply all-scores submission policy for personal account id=2."""


def migrate(cr, version):
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    # Floor ICP even if ORM method fails on incomplete registry mid-upgrade edge cases
    env["ir.config_parameter"].sudo().set_param(
        "linkedin_connector.job_score_threshold", "0"
    )
    Policy = env["linkedin.apply.policy"].sudo()
    if hasattr(Policy, "apply_all_scores_policy"):
        Policy.apply_all_scores_policy()
    else:
        personal = env["linkedin.account"].browse(2).exists()
        if personal and personal.account_type == "personal":
            policies = Policy.search([("account_id", "=", personal.id)])
            if policies:
                policies.write({"min_score": 0.0})
