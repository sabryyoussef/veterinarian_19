# -*- coding: utf-8 -*-
"""Shared helpers for dev_session_hub test isolation."""


def find_dev_policy(env, project, environment):
    policy = env["dev.policy"].search(
        [
            ("project_id", "=", project.id),
            ("environment_id", "=", environment.id),
        ],
        limit=1,
    )
    if not policy:
        policy = env["dev.policy"].search([("project_id", "=", project.id)], limit=1)
    return policy


def snapshot_dev_policy(policy):
    return {
        "deploy_permission": policy.deploy_permission,
        "production_access_policy": policy.production_access_policy,
        "development_allowed": policy.development_allowed,
    }


def ensure_dev_hub_safe_policy(policy):
    """Temporary safe automation posture for tests calling _assert_dev_hub_safe."""
    policy.write(
        {
            "deploy_permission": False,
            "production_access_policy": "denied",
            "development_allowed": True,
        }
    )
