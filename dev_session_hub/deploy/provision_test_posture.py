# -*- coding: utf-8 -*-
"""Idempotent Dev Hub *Test* safety-posture provisioner (ops/deployment-owned).

This is NOT part of the module install logic. It is intentionally kept out of
``__manifest__`` data files and out of ``__init__`` imports so that a normal
``-u dev_session_hub`` (or a fresh install) never runs it. It is wired into the
Test *activation/redeploy* flow instead (see ``provision_test_posture.sh``), and
run explicitly after the module upgrade.

Why it exists
-------------
``dev.environment._assert_dev_hub_safe`` fails closed unless the target machine
is marked non-production (``machine.production = False``). The shared seed keeps
``dev_machine_master.production = True`` (``noupdate="1"``) on purpose, so after a
redeploy/restore the Test DB can fall back to a fail-closed posture that blocks
Merge & Improve until it is restored by hand. This script restores exactly the
posture required by ``_assert_dev_hub_safe`` -- deterministically, idempotently,
and only for the hard-scoped Test target.

Hard safety scoping (any failure => NO writes are made)
-------------------------------------------------------
* the connected database must be ``pet_spot_elsahel_test``;
* the target must resolve to ``dev_environment_petspot_test``;
* the environment ``database_identifier`` must be ``pet_spot_elsahel_test``;
* ``environment_type`` must be ``test`` and ``is_production`` must be False;
* ``data_sensitivity`` must NOT be production-like;
* the machine trust zone must already be ``trusted_dev`` (never auto-trusted);
* the applied posture must NOT make any production-like environment on the same
  machine pass ``_assert_dev_hub_safe`` -- if it would, we roll back and refuse.

The last rule is the real safety net: Test and Production may share a machine, but
a production environment stays blocked by its own ``is_production`` / type /
sensitivity guards, so a genuine production environment can never be auto-marked
"safe" by this script.

Usage (via odoo shell)::

    odoo-bin shell -c <test-config> -d pet_spot_elsahel_test \
        --no-http < provision_test_posture.py

or, for a dry run that reports drift without writing::

    DEVHUB_PROVISION_APPLY=0 odoo-bin shell ... < provision_test_posture.py
"""

EXPECTED_DB = "pet_spot_elsahel_test"
ENV_XMLID = "dev_session_hub.dev_environment_petspot_test"
POLICY_XMLID = "dev_session_hub.dev_policy_petspot_test"

# data_sensitivity values that _assert_dev_hub_safe treats as unsafe.
PROD_SENSITIVITY = ("production", "restricted", "confidential")


class ProvisionRefused(Exception):
    """Raised when the target is not a safe, hard-scoped Test environment."""


def _is_production_like(environment):
    return bool(
        environment.is_production
        or environment.environment_type == "production"
        or environment.data_sensitivity in PROD_SENSITIVITY
    )


def _resolve_target(env, env_xmlid=ENV_XMLID, expected_db=EXPECTED_DB):
    if env.cr.dbname != expected_db:
        raise ProvisionRefused(
            "refusing: connected database %r is not the Test database %r"
            % (env.cr.dbname, expected_db)
        )
    environment = env.ref(env_xmlid, raise_if_not_found=False)
    if not environment:
        raise ProvisionRefused("refusing: %s not found in this database" % env_xmlid)
    return environment


def _assert_test_target(environment, expected_db=EXPECTED_DB):
    """Fail closed unless *environment* is unmistakably the non-prod Test target."""
    env = environment.env
    if environment.database_identifier != expected_db:
        raise ProvisionRefused(
            "refusing: environment database_identifier %r != %r"
            % (environment.database_identifier, expected_db)
        )
    if environment.environment_type != "test":
        raise ProvisionRefused(
            "refusing: environment_type is %r, not 'test'"
            % environment.environment_type
        )
    if environment.is_production:
        raise ProvisionRefused("refusing: environment is flagged production")
    if environment.data_sensitivity in PROD_SENSITIVITY:
        raise ProvisionRefused(
            "refusing: data_sensitivity %r is production-like"
            % environment.data_sensitivity
        )
    machine = environment.machine_id
    if not machine:
        raise ProvisionRefused("refusing: environment has no machine")
    if machine.trust_zone != "trusted_dev":
        # We never auto-promote trust; a non-dev machine must be fixed by a human.
        raise ProvisionRefused(
            "refusing: machine trust_zone %r != 'trusted_dev'" % machine.trust_zone
        )
    if _is_production_like(environment):  # defensive: target itself must be non-prod
        raise ProvisionRefused("refusing: target environment is production-like")
    return machine


def _assert_no_production_leak(machine, target):
    """Ensure the (already applied, in-memory) posture leaves every production-like
    environment on *machine* still blocked by ``_assert_dev_hub_safe``.
    """
    env = machine.env
    siblings = env["dev.environment"].search([("machine_id", "=", machine.id)])
    leaked = []
    for other in siblings - target:
        if not _is_production_like(other):
            continue
        try:
            other._assert_dev_hub_safe(other.project_id)
        except Exception:
            continue  # still blocked -> safe
        leaked.append(other.id)  # it PASSED the guard -> would be marked safe
    if leaked:
        raise ProvisionRefused(
            "refusing: posture would let production-like environment(s) %s pass the "
            "guard" % leaked
        )


def _desired(record, field, value, changes):
    current = record[field]
    if current != value:
        changes.append(
            {
                "model": record._name,
                "id": record.id,
                "field": field,
                "old": current,
                "new": value,
            }
        )
        record[field] = value


def provision_test_posture(env, apply=True):
    """Set/verify the Test execution posture required by ``_assert_dev_hub_safe``.

    Returns a report dict. Safe to run repeatedly: a second run against an
    already-compliant DB makes zero writes (``already_compliant=True``).
    Raises :class:`ProvisionRefused` (and writes nothing) for any non-Test or
    production-like target.
    """
    environment = _resolve_target(env)
    machine = _assert_test_target(environment)
    policy = env.ref(POLICY_XMLID, raise_if_not_found=False)

    changes = []
    _desired(machine, "active", True, changes)
    _desired(machine, "production", False, changes)
    _desired(environment, "active", True, changes)
    if policy:
        _desired(policy, "active", True, changes)
        _desired(policy, "development_allowed", True, changes)
        _desired(policy, "production_access_policy", "denied", changes)
        _desired(policy, "deploy_permission", False, changes)

    # Safety net: the applied (in-memory) posture must never let a production-like
    # environment on this machine pass the guard. If it would, undo everything.
    try:
        _assert_no_production_leak(machine, environment)
    except ProvisionRefused:
        env.cr.rollback()
        raise

    # Verify the Test target now satisfies the guard (raises UserError if not).
    verified = False
    verify_error = None
    try:
        environment._assert_dev_hub_safe(environment.project_id)
        verified = True
    except Exception as exc:  # pragma: no cover - reported, not swallowed
        verify_error = str(exc)

    if changes and not apply:
        # Dry run: report drift + verification, but persist nothing.
        env.cr.rollback()

    return {
        "database": env.cr.dbname,
        "environment": "%s (id=%s)" % (environment.name, environment.id),
        "machine": "%s (id=%s)" % (machine.name, machine.id),
        "policy": bool(policy),
        "applied": bool(apply and changes),
        "already_compliant": not changes,
        "changes": changes,
        "verified": verified,
        "verify_error": verify_error,
    }


def _run_from_shell():
    """Entry point when piped into ``odoo-bin shell`` (``env`` in globals)."""
    import json
    import os

    apply = os.environ.get("DEVHUB_PROVISION_APPLY", "1") != "0"
    try:
        report = provision_test_posture(env, apply=apply)  # noqa: F821 (shell env)
    except ProvisionRefused as exc:
        env.cr.rollback()  # noqa: F821
        print("PROVISION_REFUSED: %s" % exc)
        raise SystemExit(2)
    if report["applied"]:
        env.cr.commit()  # noqa: F821
    else:
        env.cr.rollback()  # noqa: F821
    print("PROVISION_REPORT " + json.dumps(report, default=str, indent=2))
    if not report["verified"]:
        print("PROVISION_VERIFY_FAILED")
        raise SystemExit(3)


if "env" in dir():  # executed inside odoo shell
    _run_from_shell()
